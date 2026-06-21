"""Telegram-Bot via Raw Bot API (urllib long-polling) — zero-dependency.

Bot ist ein dünner Client von Router/Orchestrator/Memory (Plan §8.1). Auth über
Allowlist/Rollen (§8.5). Risiko-Aktionen (/exec) sind admin-gated.

Produktions-Upgrade: `python-telegram-bot` (async) — gleiche Handler-Logik.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ...memory import MemoryStore
from ...platform import choose_profile, detect
from ...platform import config as cfg_mod
from ...orchestrator import Orchestrator
from ...tools import ToolContext
from ...tools.audit import tail
from .auth import resolve_role

API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "Nexoryx-Bot — Befehle:\n"
    "/ask <text> — KI-Anfrage\n"
    "/run <task> — Aufgabe (Planner+Lead)\n"
    "/exec <cmd> — Shell in Sandbox (nur Admin)\n"
    "/status — System-Status\n"
    "/memory [query] — Speicher anzeigen/suchen\n"
    "/forget <query> — Erinnerungen löschen\n"
    "/audit — letzte Aktionen (Admin)\n"
    "/agent — Agenten auflisten\n"
    "/help — diese Hilfe"
)


def _api(token: str, method: str, **params) -> dict:
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}


def _send(token: str, chat_id, text: str) -> None:
    # Telegram begrenzt auf 4096 Zeichen.
    _api(token, "sendMessage", chat_id=chat_id, text=text[:4000])


def run_bot() -> int:
    token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN fehlt. Setze ihn via:  nexoryx admin telegram set")
        return 1

    me = _api(token, "getMe")
    if not me.get("ok"):
        print("Telegram-Auth fehlgeschlagen (Token ungültig?).")
        return 1
    print(f"Telegram-Bot @{me['result'].get('username')} läuft. Ctrl-C zum Beenden.")

    hw = detect()
    profile = choose_profile(hw)
    memory = MemoryStore()
    orch = Orchestrator(hw, profile, memory=memory)

    offset = 0
    try:
        while True:
            updates = _api(token, "getUpdates", offset=offset, timeout=60)
            for upd in updates.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                if not text or chat_id is None:
                    continue
                role = resolve_role(user_id)
                if role is None:
                    _send(token, chat_id, f"Zugriff verweigert. Deine ID: {user_id}\n"
                          "Ein Admin kann dich freischalten: nexoryx admin user add <id> user")
                    continue
                _handle(token, chat_id, user_id, role, text, orch, memory)
    except KeyboardInterrupt:
        print("\nBot beendet.")
    return 0


def _handle(token, chat_id, user_id, role, text, orch, memory) -> None:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().lstrip("/")
    arg = arg.strip()

    if cmd in ("start", "help"):
        _send(token, chat_id, HELP)
    elif cmd == "ask":
        if not arg:
            return _send(token, chat_id, "Nutzung: /ask <text>")
        res = orch.run(arg, plan=False)
        _send(token, chat_id, res.answer)
    elif cmd == "run":
        if not arg:
            return _send(token, chat_id, "Nutzung: /run <task>")
        res = orch.run(arg, plan=True)
        out = (f"Plan:\n{res.plan}\n\n" if res.plan else "") + res.answer
        _send(token, chat_id, out)
    elif cmd == "exec":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "Nur Admin darf /exec nutzen.")
        ctx = ToolContext(role=role, actor=f"telegram:{user_id}", auto_approve=True)
        result = orch.exec_command(arg, ctx)
        body = result.output or result.error or "(keine Ausgabe)"
        _send(token, chat_id, f"[{'ok' if result.ok else 'fehler'}]\n{body}")
    elif cmd == "status":
        from ...platform import choose_profile, detect
        hw = detect(); p = choose_profile(hw)
        _send(token, chat_id, f"Profil: {p.name}\nCPU: {hw.cpu_model}\n"
              f"RAM: {hw.ram_mb} MB\nGPU: {hw.gpu.vendor}\nRolle: {role}")
    elif cmd == "memory":
        hits = memory.recall(arg, limit=8) if arg else memory.recent(8)
        if not hits:
            return _send(token, chat_id, "Kein Speicher gefunden.")
        _send(token, chat_id, "\n".join(f"• {m.text[:200]}" for m in hits))
    elif cmd == "forget":
        if not arg:
            return _send(token, chat_id, "Nutzung: /forget <query>")
        n = memory.forget(arg)
        _send(token, chat_id, f"{n} Einträge gelöscht.")
    elif cmd == "audit":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "Nur Admin.")
        rows = tail(10)
        _send(token, chat_id, "\n".join(f"{r.get('event')}: {r.get('tool','')}" for r in rows) or "leer")
    elif cmd == "agent":
        from ...agents import AGENTS
        _send(token, chat_id, "Agenten: " + ", ".join(AGENTS))
    elif cmd == "cancel":
        _send(token, chat_id, "Abgebrochen.")
    else:
        _send(token, chat_id, "Unbekannter Befehl. /help für die Liste.")
