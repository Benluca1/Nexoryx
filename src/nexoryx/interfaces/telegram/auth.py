"""Telegram-Auth (Plan §8.5/§9): Allowlist + Rollen.

Admin = konfigurierte telegram_admin_id. Andere Nutzer: Rolle aus der
Allowlist; nicht gelistete IDs werden abgewiesen.
"""

from __future__ import annotations

from ...platform import config as cfg_mod


def resolve_role(user_id: str | int) -> str | None:
    """Gibt 'admin'|'user'|'guest' zurück, oder None wenn nicht erlaubt."""
    uid = str(user_id)
    cfg = cfg_mod.load()
    if cfg.telegram_admin_id and uid == str(cfg.telegram_admin_id):
        return "admin"
    role = cfg.telegram_allowlist.get(uid)
    return role if role in ("user", "guest", "admin") else None
