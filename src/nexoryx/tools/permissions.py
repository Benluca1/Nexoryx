"""Permission-System (Plan §7/§9).

Stuft Tool-Aktionen ein (auto|confirm|admin-only) und prüft gegen die Rolle.
Gibt eine Entscheidung zurück: allow | deny | confirm (UI/Telegram fragt nach).
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Tool, ToolContext

ROLE_RANK = {"guest": 0, "user": 1, "admin": 2, "owner": 2}


@dataclass
class Decision:
    verdict: str  # allow | deny | confirm
    reason: str = ""


def check_permission(tool: Tool, ctx: ToolContext) -> Decision:
    rank = ROLE_RANK.get(ctx.role, 0)

    if tool.permission == "admin-only" and rank < 2:
        return Decision("deny", f"'{tool.name}' erfordert Admin-Rolle (du: {ctx.role})")

    if ctx.role == "guest":
        # Gäste nur read-only Tools
        if tool.permission != "auto":
            return Decision("deny", "Gäste dürfen nur read-only Tools nutzen")

    if tool.permission == "auto":
        return Decision("allow")

    # confirm-Stufe: Admin mit auto_approve darf direkt, sonst Bestätigung nötig
    if ctx.auto_approve and rank >= 2:
        return Decision("allow", "Admin auto-approve")
    return Decision("confirm", f"'{tool.name}' braucht Bestätigung")
