"""Terminal-Tool — Shell-Kommandos in der Sandbox ausführen."""

from __future__ import annotations

import os

from .base import Tool, ToolContext, ToolResult
from .sandbox import run_sandboxed


class TerminalTool(Tool):
    name = "terminal"
    description = "Führt ein Shell-Kommando in einer Sandbox aus."
    permission = "confirm"  # risikoreich → Bestätigung/Approve-Gate
    schema = {"command": "string", "timeout": "int?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        cmd = (args.get("command") or "").strip()
        if not cmd:
            return ToolResult(False, "", "Kein Kommando angegeben")
        cwd = ctx.project_root or os.getcwd()
        timeout = int(args.get("timeout", 30))
        code, out, err, kind = run_sandboxed(cmd, cwd, timeout, sandbox=ctx.sandbox)
        ok = code == 0
        return ToolResult(
            ok=ok,
            output=out,
            error=err if not ok else "",
            meta={"returncode": code, "sandbox": kind, "cwd": cwd},
        )
