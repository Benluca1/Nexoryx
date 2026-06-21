"""FileSystem-Tool mit FS-Jail (Schreiben nur unter project_root)."""

from __future__ import annotations

import os
from pathlib import Path

from .base import Tool, ToolContext, ToolResult


def _resolve_in_jail(path: str, root: str) -> Path | None:
    """Pfad kanonisieren und sicherstellen, dass er unter root bleibt."""
    base = Path(root or os.getcwd()).resolve()
    target = (base / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


class FileReadTool(Tool):
    name = "fs_read"
    description = "Liest eine Datei (nur unterhalb des Projekt-Roots)."
    permission = "auto"  # read-only
    schema = {"path": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        target = _resolve_in_jail(args.get("path", ""), ctx.project_root)
        if target is None:
            return ToolResult(False, "", "Pfad außerhalb des erlaubten Roots")
        try:
            return ToolResult(True, target.read_text(encoding="utf-8", errors="replace")[:20000])
        except OSError as exc:
            return ToolResult(False, "", str(exc))


class FileWriteTool(Tool):
    name = "fs_write"
    description = "Schreibt eine Datei (nur unterhalb des Projekt-Roots)."
    permission = "confirm"
    schema = {"path": "string", "content": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        target = _resolve_in_jail(args.get("path", ""), ctx.project_root)
        if target is None:
            return ToolResult(False, "", "Schreiben außerhalb des Jails blockiert")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get("content", ""), encoding="utf-8")
            return ToolResult(True, f"{target} geschrieben ({len(args.get('content',''))} Zeichen)")
        except OSError as exc:
            return ToolResult(False, "", str(exc))
