from fastapi import APIRouter, WebSocket, WebSocketException
from typing import Dict, List, Callable, Optional
from enum import Enum
from asyncio import create_task
from pydantic import BaseModel
import datetime
import asyncio

from sandbox.sandbox import DevSandbox
from agents.agent import Agent, ChatMessage, parse_file_changes
from db.database import get_db
from db.models import Project, Message as DbChatMessage, Chat, Stack
from db.queries import get_chat_for_user
from routers.auth import get_current_user_from_token
from sqlalchemy.orm import Session


class SandboxStatus(str, Enum):
    OFFLINE = "OFFLINE"
    BUILDING = "BUILDING"
    READY = "READY"
    WORKING = "WORKING"


class ProjectStatusResponse(BaseModel):
    for_type: str = "status"
    project_id: int
    sandbox_status: SandboxStatus
    tunnels: Dict[int, str]
    file_paths: Optional[List[str]] = None


class ChatUpdateResponse(BaseModel):
    for_type: str = "chat_update"
    chat_id: int
    message: ChatMessage
    follow_ups: Optional[List[str]] = None


class ChatChunkResponse(BaseModel):
    for_type: str = "chat_chunk"
    role: str
    content: str


def _message_to_db_message(message: ChatMessage, chat_id: int) -> DbChatMessage:
    return DbChatMessage(
        role=message.role,
        content=message.content,
        chat_id=chat_id,
    )


def _db_message_to_message(db_message: DbChatMessage) -> ChatMessage:
    return ChatMessage(
        id=db_message.id,
        role=db_message.role,
        content=db_message.content,
    )


router = APIRouter(tags=["websockets"])


async def _apply_file_changes(agent: Agent, total_content: str):
    if agent.sandbox:
        changes = parse_file_changes(agent.sandbox, total_content)
        if len(changes) > 0:
            print("Applying Changes", [f.path for f in changes])
            await agent.sandbox.write_file_contents(
                [(change.path, change.content) for change in changes]
            )


class ProjectManager:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id
        self.chat_sockets: Dict[int, List[WebSocket]] = {}
        self.chat_agents: Dict[int, Agent] = {}
        self.sandbox_status = SandboxStatus.OFFLINE
        self.sandbox = None
        self.tunnels = {}

    async def _manage_sandbox_task(self):
        print(f"Managing sandbox for project {self.project_id}...")
        self.sandbox_status = SandboxStatus.BUILDING
        await self.emit_project(await self._get_project_status())
        self.sandbox = await DevSandbox.get_or_create(self.project_id)
        await self.sandbox.wait_for_up()
        self.sandbox_status = SandboxStatus.READY
        tunnels = await self.sandbox.sb.tunnels.aio()
        self.tunnels = {port: tunnel.url for port, tunnel in tunnels.items()}
        await self.emit_project(await self._get_project_status())
        for agent in self.chat_agents.values():
            agent.sandbox = self.sandbox

    def start(self):
        create_task(self._manage_sandbox_task())

    async def _get_project_status(self):
        file_paths = None
        if self.sandbox:
            file_paths = await self.sandbox.get_file_paths()
        return ProjectStatusResponse(
            project_id=self.project_id,
            sandbox_status=self.sandbox_status,
            tunnels=self.tunnels,
            file_paths=file_paths,
        )

    async def add_chat_socket(self, chat_id: int, websocket: WebSocket):
        if chat_id not in self.chat_sockets:
            project = (
                self.db.query(Project).filter(Project.id == self.project_id).first()
            )
            stack = self.db.query(Stack).filter(Stack.id == project.stack_id).first()
            self.chat_agents[chat_id] = Agent(project, stack)
            self.chat_sockets[chat_id] = []
        self.chat_sockets[chat_id].append(websocket)
        await self.emit_project(await self._get_project_status())

    def remove_chat_socket(self, chat_id: int, websocket: WebSocket):
        self.chat_sockets[chat_id].remove(websocket)
        if len(self.chat_sockets[chat_id]) == 0:
            del self.chat_sockets[chat_id]
            del self.chat_agents[chat_id]

    async def on_chat_message(self, chat_id: int, message: ChatMessage):
        self.sandbox_status = SandboxStatus.WORKING
        await self.emit_project(await self._get_project_status())

        db_message = _message_to_db_message(message, chat_id)
        self.db.add(db_message)
        self.db.commit()
        self.db.refresh(db_message)
        await self.emit_chat(
            chat_id,
            ChatUpdateResponse(
                chat_id=chat_id, message=_db_message_to_message(db_message)
            ),
        )

        agent = self.chat_agents[chat_id]
        db_messages = (
            self.db.query(DbChatMessage)
            .filter(DbChatMessage.chat_id == chat_id)
            .order_by(DbChatMessage.created_at)
            .all()
        )
        messages = [_db_message_to_message(m) for m in db_messages]
        total_content = ""
        async for partial_message in agent.step(messages):
            total_content += partial_message.delta_content
            await self.emit_chat(
                chat_id,
                ChatChunkResponse(
                    role="assistant", content=partial_message.delta_content
                ),
            )

        resp_message = ChatMessage(role="assistant", content=total_content)
        db_resp_message = _message_to_db_message(resp_message, chat_id)
        self.db.add(db_resp_message)
        self.db.commit()

        await _apply_file_changes(agent, total_content)

        follow_ups = await agent.suggest_follow_ups(messages + [resp_message])

        await self.emit_chat(
            chat_id,
            ChatUpdateResponse(
                chat_id=chat_id,
                message=_db_message_to_message(db_resp_message),
                follow_ups=follow_ups,
            ),
        )

        self.sandbox_status = SandboxStatus.READY
        await self.emit_project(await self._get_project_status())

    async def emit_project(self, data: BaseModel):
        for chat_id in self.chat_sockets:
            await self.emit_chat(chat_id, data)

    async def emit_chat(self, chat_id: int, data: BaseModel):
        sockets = list(self.chat_sockets[chat_id])
        for socket in sockets:
            try:
                await socket.send_json(data.model_dump())
            except RuntimeError:
                self.chat_sockets[chat_id].remove(socket)


project_managers: Dict[int, ProjectManager] = {}


@router.websocket("/api/ws/chat/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: int):
    db = next(get_db())
    token = websocket.query_params.get("token")
    current_user = await get_current_user_from_token(token, db)
    chat = get_chat_for_user(db, chat_id, current_user)
    if chat is None:
        raise WebSocketException(code=404, reason="Chat not found")

    project = chat.project
    if project is None:
        raise WebSocketException(code=404, reason="Project not found")

    if project.id not in project_managers:
        pm = ProjectManager(db, project.id)
        pm.start()
        project_managers[project.id] = pm
    else:
        pm = project_managers[project.id]

    await websocket.accept()
    await pm.add_chat_socket(chat_id, websocket)

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = ChatMessage.model_validate_json(raw_data)
            await pm.on_chat_message(chat_id, data)
    except Exception as e:
        print("websocket loop error", e)
    finally:
        pm.remove_chat_socket(chat_id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass
