import modal
import aiohttp
import asyncio
import base64
import datetime
from typing import List, Optional, Tuple
from modal.volume import FileEntryType
from asyncio import Lock

from db.database import get_db
from db.models import Project
from sandbox.packs import get_pack_by_id

app = modal.App.lookup("prompt-stack-sandbox", create_if_missing=True)


IGNORE_PATHS = ["node_modules", ".git", ".next", "build"]

_sandbox_locks = {}


async def _wait_for_up(url: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return response.status < 500
    except:
        return False


async def _vol_to_paths(vol: modal.Volume):
    paths = []
    entries = await vol.listdir.aio("/", recursive=False)

    def _ends_with_ignore_path(path: str):
        path_parts = path.split("/")
        return any(
            part == ignore_path for ignore_path in IGNORE_PATHS for part in path_parts
        )

    async def _recurse(path: str):
        entries = await vol.listdir.aio(path, recursive=False)
        for entry in entries:
            if _ends_with_ignore_path(entry.path):
                continue
            if entry.type == FileEntryType.DIRECTORY:
                await _recurse(entry.path)
            else:
                paths.append(entry.path)

    for entry in entries:
        if _ends_with_ignore_path(entry.path):
            continue
        if entry.type == FileEntryType.DIRECTORY:
            await _recurse(entry.path)
        else:
            paths.append(entry.path)

    return paths


class DevSandbox:
    def __init__(self, project_id: int, sb: modal.Sandbox, vol: modal.Volume):
        self.project_id = project_id
        self.sb = sb
        self.vol = vol
        self.ready = False

    async def wait_for_up(self):
        while True:
            print("Polling sandbox", self.project_id, self.sb)
            tunnels = await self.sb.tunnels.aio()
            tunnel_url = tunnels[3000].url
            if await _wait_for_up(tunnel_url):
                break

            await asyncio.sleep(3)
        self.ready = True

    async def get_file_paths(self) -> List[str]:
        paths = await _vol_to_paths(self.vol)
        return sorted(["/app/" + path for path in paths])

    async def run_command(self, command: str, workdir: Optional[str] = None) -> str:
        try:
            proc = await self.sb.exec.aio(
                "sh", "-c", command, workdir=workdir or "/app"
            )
            await proc.wait.aio()
            return (await proc.stdout.read.aio()) + (await proc.stderr.read.aio())
        except Exception as e:
            return f"Error: {e}"

    async def write_file_contents(self, files: List[Tuple[str, str]]):
        # Create a single Python command that writes all files at once
        files_data = []
        for path, content in files:
            encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            files_data.append((path, encoded_content))

        python_cmd = """
import os
import base64

files = %s

for path, base64_content in files:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(base64.b64decode(base64_content).decode('utf-8'))
""" % str(
            files_data
        )

        proc = await self.sb.exec.aio(
            "python3",
            "-c",
            python_cmd,
            workdir="/app",
        )
        await proc.wait.aio()

    async def read_file_contents(self, path: str) -> str:
        if path.startswith("/app/"):
            path = path[len("/app/") :]
        content = []
        async for chunk in self.vol.read_file.aio(path):
            content.append(chunk.decode("utf-8"))
        return "".join(content)

    @classmethod
    async def delete(cls, project_id: int):
        try:
            async for sb in modal.Sandbox.list.aio(
                tags={"project_id": str(project_id)}
            ):
                await sb.terminate.aio()
        except:
            pass
        try:
            await modal.Volume.delete.aio(f"prompt-stack-vol-project-{project_id}")
        except:
            pass

    @classmethod
    async def get_or_create(cls, project_id: int) -> "DevSandbox":
        # Get or create a lock for this project
        if project_id not in _sandbox_locks:
            _sandbox_locks[project_id] = Lock()

        async with _sandbox_locks[project_id]:
            db = next(get_db())
            project = db.query(Project).filter(Project.id == project_id).first()

            vol = modal.Volume.from_name(
                f"prompt-stack-vol-project-{project_id}", create_if_missing=True
            )
            if project.modal_active_sandbox_id:
                sb = await modal.Sandbox.from_id.aio(project.modal_active_sandbox_id)
                poll_code = await sb.poll.aio()
                return_code = sb.returncode
                sb_is_up = ((poll_code is None) or (return_code is None)) or (
                    poll_code == 0 and return_code == 0
                )
            else:
                sb_is_up = False
            if not sb_is_up:
                print(
                    "Creating sandbox for project",
                    project.id,
                    project.modal_active_sandbox_id,
                )
                pack = get_pack_by_id(project.stack_pack_id)
                image = modal.Image.from_registry(pack.from_registry, add_python=None)
                sb = await modal.Sandbox.create.aio(
                    "sh",
                    "-c",
                    pack.sandbox_start_cmd,
                    app=app,
                    volumes={"/app": vol},
                    image=image,
                    encrypted_ports=[3000],
                    timeout=3 * 60 * 60,
                    cpu=1,
                    memory=1024,
                )
                project.modal_active_sandbox_id = sb.object_id
                project.modal_active_sandbox_last_used_at = datetime.datetime.now()
                db.commit()
                await sb.set_tags.aio({"project_id": str(project_id)})
            else:
                print("Using existing sandbox for project", project.id)
                sb = await modal.Sandbox.from_id.aio(project.modal_active_sandbox_id)

            return cls(project_id, sb, vol)
