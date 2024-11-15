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
from db.models import Project, ChatMessage as DbChatMessage
from routers.auth import get_current_user_from_token
from sqlalchemy.orm import Session


class SandboxStatus(str, Enum):
    BUILDING = "BUILDING"
    READY = "READY"


class SandboxStatusResponse(BaseModel):
    for_type: str = "sandbox_status"
    status: SandboxStatus
    tunnels: Dict[int, str]


class SandboxFileTreeResponse(BaseModel):
    for_type: str = "sandbox_file_tree"
    paths: List[str]


class ChatChunkResponse(BaseModel):
    for_type: str = "chat_chunk"
    content: str
    complete: bool
    suggested_follow_ups: Optional[List[str]] = None


class ChatRequest(BaseModel):
    chat: List[ChatMessage]


router = APIRouter(tags=["websockets"])


async def _save_chat_messages(
    db: Session,
    project_id: int,
    chat_messages: List[ChatMessage],
):
    db.query(DbChatMessage).filter(DbChatMessage.project_id == project_id).delete()

    for chat_message in chat_messages:
        db_message = DbChatMessage(
            role=chat_message.role,
            content=chat_message.content,
            project_id=project_id,
        )
        db.add(db_message)

    db.query(Project).filter(Project.id == project_id).update(
        {"modal_active_sandbox_last_used_at": datetime.datetime.now()}
    )

    db.commit()


async def _apply_file_changes(agent: Agent, total_content: str):
    if agent.sandbox:
        changes = parse_file_changes(agent.sandbox, total_content)
        if len(changes) > 0:
            print("Applying Changes", [f.path for f in changes])
            await agent.sandbox.write_file_contents(
                [(change.path, change.content) for change in changes]
            )


async def _get_follow_ups(agent: Agent, chat_messages: List[ChatMessage]):
    return await agent.suggest_follow_ups(chat_messages)


async def _create_sandbox(
    send_json: Callable[[BaseModel], None], agent: Agent, project_id: int
):
    try:
        await send_json(
            SandboxStatusResponse(status=SandboxStatus.BUILDING, tunnels={})
        )

        sandbox = await DevSandbox.get_or_create(project_id)
        agent.set_sandbox(sandbox)
        await sandbox.wait_for_up()

        paths = await sandbox.get_file_paths()
        await send_json(SandboxFileTreeResponse(paths=paths))

        tunnels = await sandbox.sb.tunnels.aio()
        await send_json(
            SandboxStatusResponse(
                status=SandboxStatus.READY,
                tunnels={port: tunnel.url for port, tunnel in tunnels.items()},
            )
        )
    except Exception as e:
        print("create_sandbox() error", e)


@router.websocket("/api/ws/project-chat/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: int):
    db = next(get_db())

    token = websocket.query_params.get("token")
    current_user = await get_current_user_from_token(token, db)
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise WebSocketException(code=404, reason="Project not found")

    await websocket.accept()

    async def send_json(data: BaseModel):
        await websocket.send_json(data.model_dump())

    agent = Agent(project)

    sandbox_task = create_task(_create_sandbox(send_json, agent, project_id))

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = ChatRequest.model_validate_json(raw_data)
            await _save_chat_messages(db, project_id, data.chat)

            while not agent.sandbox or not agent.sandbox.ready:
                await asyncio.sleep(1)

            total_content = ""
            async for partial_message in agent.step(data.chat):
                total_content += partial_message.delta_content
                await send_json(
                    ChatChunkResponse(
                        content=partial_message.delta_content, complete=False
                    )
                )

            _, _, follow_ups = await asyncio.gather(
                _save_chat_messages(
                    db,
                    project_id,
                    data.chat + [ChatMessage(role="assistant", content=total_content)],
                ),
                _apply_file_changes(agent, total_content),
                _get_follow_ups(
                    agent,
                    data.chat + [ChatMessage(role="assistant", content=total_content)],
                ),
            )

            await send_json(
                SandboxFileTreeResponse(paths=await agent.sandbox.get_file_paths())
            )

            await send_json(
                ChatChunkResponse(
                    content="", complete=True, suggested_follow_ups=follow_ups
                )
            )

    except Exception as e:
        print("websocket loop error", e)
    finally:
        sandbox_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
