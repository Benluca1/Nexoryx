"""Tool-Basis-Typen."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolContext:
    role: str = "user"           # owner/admin | user | guest
    project_root: str = ""       # FS-Jail-Wurzel
    actor: str = "cli"           # cli | telegram:<id>
    auto_approve: bool = False   # confirm-Tools ohne Rückfrage (alle Rollen außer guest)
    sandbox: bool = True         # False = direkter subprocess (kein bwrap/firejail)
    allow_computer: bool = False # Maus/Tastatur-Injection explizit erlaubt


@dataclass
class ToolResult:
    ok: bool
    output: str
    error: str = ""
    meta: dict = field(default_factory=dict)


class Tool:
    name: str = "base"
    description: str = ""
    permission: str = "confirm"  # auto | confirm | admin-only
    schema: dict = {}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError
