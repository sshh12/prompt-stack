from pydantic import BaseModel
from typing import List
import re
import asyncio

from sandbox.sandbox import DevSandbox
from agents.prompts import chat_complete


class FileChange(BaseModel):
    path: str
    diff: str
    content: str


_CODE_BLOCK_PATTERNS = [
    r"```[\w.]+\n[#/]+ (\S+)\n([\s\S]+?)```",  # Python-style comments (#)
    r"```[\w.]+\n[/*]+ (\S+) \*/\n([\s\S]+?)```",  # C-style comments (/* */)
    r"```[\w.]+\n<!-- (\S+) -->\n([\s\S]+?)```",  # HTML-style comments <!-- -->
]

_DIFF_TIPS = {
    r"<Link[^>]*>[\S\s]*?<a[^>]*>": "All <Link> tags should be free of <a> tags. Remove all <a> tags from <Link> tags.",
    "<CardBody": "Ensure in Shadcn UI, <Card>s use <CardContent> instead of <CardBody>.",
    "<Slider": "Ensure <Slider />s in Shadcn have at least values= or a min= and a max= attribute.",
    r"Layout\(": "Ensure Layouts in Next.js retain <html> and <body> tags.",
    "use-toast": "Ensure the import is from \"@/hooks/use-toast\" (rather than components)",
}


async def _apply_smart_diff(original_content: str, diff: str, tips: str) -> str:
    return await chat_complete(
        """
You are a senior software engineer that applies code changes to a file. Given the <original-content>, the <diff>, and the <adjustments>, apply the changes to the content. 

- You must apply the <adjustments> provided even if this conflicts with the original diff
- You must follow instructions from within comments in <diff> (e.g. <!-- remove this -->)
- You must maintain the layout of the file especially in languages/formats where it matters
- Ensure you maintain sections of the original file IF the diff denotes them with "... existing code ..." or other similar comment-based instructions

Respond ONLY with the updated content (no code blocks or other formatting).
""".strip(),
        f"<original-content>\n{original_content}\n</original-content>\n\n<diff>\n{diff}\n</diff>\n\n<adjustments>\n{tips}\n</adjustments>",
    )


async def parse_file_changes(sandbox: DevSandbox, content: str) -> List[FileChange]:
    changes = []

    for pattern in _CODE_BLOCK_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            file_path = match.group(1)
            diff = match.group(2).strip()
            changes.append(FileChange(path=file_path, diff=diff, content=diff))

    # Deduplicate changes by file path, keeping the last occurrence
    seen_paths = {}
    for change in changes:
        seen_paths[change.path] = change
    changes = list(seen_paths.values())

    async def _render_diff(change: FileChange) -> FileChange:
        tips = []
        for pattern, tip in _DIFF_TIPS.items():
            if re.search(pattern, change.diff):
                tips.append(tip)
        skip_conditions = [
            "... keep" not in change.diff,
            "... existing" not in change.diff,
            "... rest" not in change.diff,
            "the same..." not in change.diff,
            len(tips) == 0
        ]
        if all(skip_conditions):
            return change
        try:
            original_content = await sandbox.read_file_contents(change.path)
        except Exception:
            original_content = "(file does not yet exist)"
        new_content = await _apply_smart_diff(
            original_content, change.diff, "\n".join([f" - {t}" for t in tips])
        )
        print(f"Applying smart diff to {change.path}, reasons: {skip_conditions}")
        return FileChange(
            path=change.path,
            diff=change.diff,
            content=new_content,
        )

    changes = await asyncio.gather(*[_render_diff(change) for change in changes])

    return changes


def remove_file_changes(content: str) -> str:
    for pattern in _CODE_BLOCK_PATTERNS:
        content = re.sub(pattern, "", content)
    return content
