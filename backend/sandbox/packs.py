from pydantic import BaseModel


class StackPack(BaseModel):
    id: str
    title: str
    description: str
    from_registry: str
    sandbox_start_cmd: str
    stack_description: str


PACKS = [
    StackPack(
        id="vanilla-react",
        title="Vanilla React",
        description="A simple JS React App. Best for starting from scratch with minimal dependencies.",
        from_registry="ghcr.io/sshh12/prompt-stack-pack-vanilla-react:latest",
        sandbox_start_cmd="cd /app && if [ ! -d 'frontend' ]; then cp -r /frontend .; fi && cd frontend && npm start",
        stack_description="""
You are building a vanilla React app.

The user choose to use a vanilla app so avoid adding any additional dependencies unless they are explicitly asked for.

Included:
- react-router-dom (use for all routing needs, note this is v6.xx)
- The react app is already created in /app/frontend (do not run `create-react-app`)

Tips:
- Use react-leaflet for maps
- Use https://random.imagecdn.app/<width>/<height> for random images
""".strip(),
    )
]

DEFAULT_STACK_PACK_ID = "vanilla-react"


def get_pack_by_id(id: str) -> StackPack:
    return next((pack for pack in PACKS if pack.id == id), None)
