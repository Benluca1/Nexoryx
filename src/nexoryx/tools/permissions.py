"""Permission-System (Plan §7/§9).

Stufen:
  auto        — immer erlaubt (read-only, harmlos)
  confirm     — Bestätigung nötig; auto_approve überspringt sie
  computer    — Maus/Tastatur-Injection: nur via Telegram-Befehl oder
                ctx.allow_computer=True (explizite Freigabe); NIE automatisch
  admin-only  — erfordert Admin-Rolle

Maus/Tastatur werden von Nexoryx nur eingesetzt wenn es keinen anderen Weg gibt,
oder wenn der Benutzer es explizit über Telegram anfordert.
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

    if ctx.role == "guest" and tool.permission not in ("auto",):
        return Decision("deny", "Gäste dürfen nur read-only Tools nutzen")

    if tool.permission == "auto":
        return Decision("allow")

    # computer-Stufe: nur via Telegram oder explizite Freigabe, nie automatisch
    if tool.permission == "computer":
        via_telegram = ctx.actor.startswith("telegram:")
        if via_telegram or ctx.allow_computer:
            return Decision("allow", "computer via " + ("telegram" if via_telegram else "allow_computer"))
        return Decision(
            "deny",
            f"'{tool.name}' (Maus/Tastatur) wird nur auf explizite Telegram-Anfrage "
            "oder mit allow_computer=True ausgeführt.",
        )

    # confirm-Stufe: auto_approve überspringt die Rückfrage
    if ctx.auto_approve:
        return Decision("allow", "auto-approve")

    return Decision("confirm", f"'{tool.name}' braucht Bestätigung")
