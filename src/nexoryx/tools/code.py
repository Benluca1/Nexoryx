"""Code-Navigation: glob, grep, git (read-only) — alle im Projekt-Jail."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", ".nexoryx"}


def _root(ctx: ToolContext) -> Path:
    return Path(ctx.project_root or os.getcwd()).resolve()


class GlobTool(Tool):
    name = "glob"
    description = "Findet Dateien per Glob-Muster (z. B. **/*.py) im Projekt."
    permission = "auto"
    schema = {"pattern": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern", "**/*")
        root = _root(ctx)
        hits = [str(p.relative_to(root)) for p in root.glob(pattern)
                if p.is_file() and not (set(p.parts) & _SKIP)]
        return ToolResult(True, "\n".join(sorted(hits)[:200]) or "(keine Treffer)")


class GrepTool(Tool):
    name = "grep"
    description = "Sucht einen Regex in Projektdateien (Datei:Zeile:Treffer)."
    permission = "auto"
    schema = {"pattern": "string", "glob": "string?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            rx = re.compile(args.get("pattern", ""))
        except re.error as exc:
            return ToolResult(False, "", f"Ungültiger Regex: {exc}")
        root = _root(ctx)
        glob = args.get("glob", "**/*")
        out: list[str] = []
        for p in root.glob(glob):
            if not p.is_file() or (set(p.parts) & _SKIP):
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{p.relative_to(root)}:{i}: {line.strip()[:160]}")
                        if len(out) >= 200:
                            break
            except OSError:
                continue
            if len(out) >= 200:
                break
        return ToolResult(True, "\n".join(out) or "(keine Treffer)")


class GitTool(Tool):
    name = "git"
    description = "Git read-only (status|log|diff|show|branch) im Projekt."
    permission = "auto"
    schema = {"args": "string"}
    _ALLOWED = {"status", "log", "diff", "show", "branch", "ls-files"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        parts = (args.get("args") or "status").split()
        if not parts or parts[0] not in self._ALLOWED:
            return ToolResult(False, "", f"Nur erlaubt: {', '.join(sorted(self._ALLOWED))}")
        try:
            proc = subprocess.run(
                ["git", *parts], cwd=str(_root(ctx)), capture_output=True,
                text=True, timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ToolResult(False, "", str(exc))
        return ToolResult(proc.returncode == 0, proc.stdout[:12_000], proc.stderr[:2000])
