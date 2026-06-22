"""Telegram-Bot via Raw Bot API (urllib long-polling) — zero-dependency.

Bot ist ein dünner Client von Router/Orchestrator/Memory (Plan §8.1). Auth über
Allowlist/Rollen (§8.5). Risiko-Aktionen (/exec) sind admin-gated.

start_background() enthält einen Watchdog-Thread: der Bot startet sich nach
Abstürzen automatisch neu (exponentieller Backoff, max 5 Minuten).
"""

from __future__ import annotations

import json
import os
import threading
import time
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

HELP = """\
🤖 *Nexoryx-Bot* — Befehle

*Chat*
/ask <text> — KI-Anfrage
/code <aufgabe> — Coding-Agent
/plan <aufgabe> — Planungs-Agent
/research <frage> — Recherche-Agent
/debug <problem> — Debug-Agent

*Ausführung*
/run <task> — Aufgabe mit Planer
/exec <cmd> — Shell in Sandbox (nur Admin)
/search <query> — Web-Suche

*Speicher & Profil*
/memory [query] — Speicher anzeigen/suchen
/forget <query> — Erinnerungen löschen
/profile — Nutzer-Profil anzeigen (Interessen, Vorlieben, …)

*System*
/status — System-Status
/models — Verfügbare Modelle
/usage — API-Kosten & Token
/tools — Verfügbare Tools
/train — Training-Status anzeigen
/autotrain — Hausmodell im Hintergrund trainieren (Admin)
/audit — letzte Aktionen (Admin)
/whoami — Deine Nutzer-Info
/agent — Agenten auflisten
/private — Privat-Modus umschalten

*Admin*
/restart — Bot neu starten
/broadcast <text> — Alle Nutzer benachrichtigen
/users — Nutzer auflisten

/help — diese Hilfe
"""


def _api(token: str, method: str, **params) -> dict:
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data), timeout=70
        ) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}


def _send(token: str, chat_id, text: str, parse_mode: str = "") -> None:
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        kw: dict = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            kw["parse_mode"] = parse_mode
        _api(token, "sendMessage", **kw)


def _typing(token: str, chat_id) -> None:
    _api(token, "sendChatAction", chat_id=chat_id, action="typing")


def run_bot(stop_event=None) -> int:
    """Haupt-Loop. stop_event: threading.Event zum sauberen Beenden."""
    token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN fehlt. Setze ihn via:  nexoryx admin telegram set")
        return 1

    me = _api(token, "getMe")
    if not me.get("ok"):
        print("Telegram-Auth fehlgeschlagen (Token ungültig?).")
        return 1
    username = me["result"].get("username", "?")
    print(f"Telegram-Bot @{username} läuft.")

    hw = detect()
    profile = choose_profile(hw)
    memory = MemoryStore()
    orch = Orchestrator(hw, profile, memory=memory)
    private_users: set = set()  # user_ids im Privat-Modus

    offset = 0
    try:
        while not (stop_event and stop_event.is_set()):
            updates = _api(token, "getUpdates", offset=offset, timeout=60)
            if not updates.get("ok"):
                time.sleep(5)
                continue
            for upd in updates.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                first_name = msg.get("from", {}).get("first_name", "Nutzer")
                if not text or chat_id is None:
                    continue
                role = resolve_role(user_id)
                if role is None:
                    _send(token, chat_id,
                          f"⛔ Zugriff verweigert.\nDeine ID: {user_id}\n"
                          "Ein Admin kann dich freischalten:\n"
                          "nexoryx admin user add <id> user")
                    continue
                _handle(token, chat_id, user_id, first_name, role, text,
                        orch, memory, private_users)
    except KeyboardInterrupt:
        print("\nBot beendet.")
    except Exception as exc:
        print(f"Bot-Fehler: {exc}")
        return 2
    return 0


def start_background() -> threading.Thread | None:
    """Startet den Bot als überwachten Thread mit automatischem Neustart.

    Der Watchdog-Thread erkennt Abstürze und startet den Bot mit
    exponentiellem Backoff (5s → 10s → 20s → … → max 300s) neu.
    """
    token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
    if not token:
        return None

    stop_event = threading.Event()

    def _watchdog():
        delay = 5
        max_delay = 300
        while not stop_event.is_set():
            try:
                rc = run_bot(stop_event=stop_event)
            except Exception as exc:
                rc = 2
                print(f"[Telegram] Bot abgestürzt: {exc}")
            if stop_event.is_set():
                break
            if rc == 1:
                # Konfigurationsfehler — nicht wiederholen, nur warten
                print(f"[Telegram] Bot-Konfigurationsfehler — nächster Versuch in {delay}s")
            else:
                print(f"[Telegram] Bot beendet (rc={rc}) — Neustart in {delay}s …")
            time.sleep(delay)
            delay = min(delay * 2, max_delay)

    watchdog = threading.Thread(target=_watchdog, daemon=True, name="nexoryx-telegram-watchdog")
    watchdog.start()
    return watchdog


def _handle(token, chat_id, user_id, first_name, role, text, orch, memory, private_users) -> None:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().lstrip("/")
    arg = arg.strip()
    is_private = user_id in private_users

    # ── Hilfe & Start ──────────────────────────────────────────────────────────
    if cmd in ("start", "help"):
        _send(token, chat_id, HELP, parse_mode="Markdown")

    elif cmd == "whoami":
        cfg = cfg_mod.load()
        _send(token, chat_id,
              f"👤 *Nutzer-Info*\n"
              f"Name: {first_name}\n"
              f"ID: `{user_id}`\n"
              f"Rolle: `{role}`\n"
              f"Privat-Modus: {'AN 🔒' if is_private else 'AUS'}",
              parse_mode="Markdown")

    # ── Chat / KI ─────────────────────────────────────────────────────────────
    elif cmd == "ask":
        if not arg:
            return _send(token, chat_id, "Nutzung: /ask <text>")
        _typing(token, chat_id)
        res = orch.run(arg, plan=False)
        _send(token, chat_id, res.answer)

    elif cmd in ("code", "plan", "research", "debug"):
        if not arg:
            return _send(token, chat_id, f"Nutzung: /{cmd} <aufgabe>")
        _task_labels = {
            "code": ("coding", "Coder"),
            "plan": ("reasoning", "Planner"),
            "research": ("research", "Research"),
            "debug": ("coding", "Debug"),
        }
        task_type, label = _task_labels[cmd]
        _typing(token, chat_id)
        _send(token, chat_id, f"⏳ {label} arbeitet …")
        from ...router import ChatRequest, Router
        hw = detect(); p = choose_profile(hw)
        router = Router(hw, p)
        system = f"Du bist ein spezialisierter {label}-Agent. Antworte auf Deutsch."
        try:
            req = ChatRequest(prompt=arg, system=system, task_type=task_type,
                              sensitive=is_private, max_tokens=4096)
            resp = router.route(req)
            answer = resp.text.strip()
            _send(token, chat_id, f"[{label} · {resp.model}]\n\n{answer}")
        except Exception as exc:
            _send(token, chat_id, f"❌ Fehler: {exc}")

    elif cmd == "run":
        if not arg:
            return _send(token, chat_id, "Nutzung: /run <task>")
        _typing(token, chat_id)
        _send(token, chat_id, "⏳ Plane Aufgabe …")
        res = orch.run(arg, plan=True)
        out = (f"📋 *Plan:*\n{res.plan}\n\n" if res.plan else "") + res.answer
        _send(token, chat_id, out, parse_mode="Markdown")

    elif cmd == "search":
        if not arg:
            return _send(token, chat_id, "Nutzung: /search <suchbegriff>")
        _typing(token, chat_id)
        try:
            ctx = ToolContext(role=role, actor=f"telegram:{user_id}", auto_approve=True)
            from ...tools.web import WebSearch
            ws = WebSearch()
            result = ws.run({"query": arg}, ctx)
            _send(token, chat_id, f"🔍 *{arg}*\n\n{result.output[:3000]}", parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"❌ Suche fehlgeschlagen: {exc}")

    # ── Shell / Ausführung ────────────────────────────────────────────────────
    elif cmd == "exec":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin darf /exec nutzen.")
        if not arg:
            return _send(token, chat_id, "Nutzung: /exec <befehl>")
        _typing(token, chat_id)
        ctx = ToolContext(role=role, actor=f"telegram:{user_id}", auto_approve=True)
        result = orch.exec_command(arg, ctx)
        body = result.output or result.error or "(keine Ausgabe)"
        icon = "✅" if result.ok else "❌"
        _send(token, chat_id, f"{icon} `{arg}`\n\n```\n{body[:3000]}\n```", parse_mode="Markdown")

    # ── Status / Info ─────────────────────────────────────────────────────────
    elif cmd == "status":
        hw = detect()
        p = choose_profile(hw)
        from ...router import available_models
        models = available_models()
        model_list = "\n".join(f"  • {s.name} [{pr.name}]" for s, pr in models[:8])
        _send(token, chat_id,
              f"📊 *System-Status*\n"
              f"Profil: `{p.name}`\n"
              f"CPU: {hw.cpu_model[:30]}\n"
              f"RAM: {hw.ram_mb} MB\n"
              f"GPU: {hw.gpu.vendor}\n"
              f"Rolle: `{role}`\n"
              f"Privat: {'AN 🔒' if is_private else 'AUS'}\n\n"
              f"*Modelle:*\n{model_list or '(keine)'}",
              parse_mode="Markdown")

    elif cmd == "models":
        from ...router import available_models
        models = available_models()
        if not models:
            return _send(token, chat_id, "Keine Modelle verfügbar.")
        lines = [f"• {s.name} [{pr.name}]{'  (lokal)' if s.is_local else ''}"
                 for s, pr in models]
        _send(token, chat_id, "🤖 *Verfügbare Modelle*\n\n" + "\n".join(lines), parse_mode="Markdown")

    elif cmd == "usage":
        try:
            from ...platform.usage import today_stats
            s = today_stats()
            _send(token, chat_id,
                  f"💰 *API-Nutzung heute*\n"
                  f"Anfragen: {s.get('requests', 0)}\n"
                  f"Token (In): {s.get('in_tok', 0):,}\n"
                  f"Token (Out): {s.get('out_tok', 0):,}\n"
                  f"Kosten: ${s.get('cost', 0.0):.4f}",
                  parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"Nutzungsdaten nicht verfügbar: {exc}")

    elif cmd == "tools":
        try:
            from ...tools.registry import _REGISTRY
            lines = [f"• `{name}` [{getattr(e['tool'], 'permission_level', 'auto')}]"
                     for name, e in sorted(_REGISTRY.items())]
        except Exception:
            lines = ["• terminal [confirm]", "• fs_read [auto]", "• fs_write [confirm]",
                     "• web_search [auto]", "• http_fetch [auto]", "• glob [auto]",
                     "• grep [auto]", "• git [auto]"]
        _send(token, chat_id, "🔧 *Verfügbare Tools*\n\n" + "\n".join(lines), parse_mode="Markdown")

    # ── Training ──────────────────────────────────────────────────────────────
    elif cmd == "train":
        # Nur Status anzeigen, kein Training starten (dafür /autotrain)
        try:
            from ...training.train import train_report
            report = train_report()
            total = report["dataset"]["total"]
            teacher = report["dataset"].get("teacher", 0)
            MIN = 50
            deps = report.get("deps_missing", [])
            _send(token, chat_id,
                  f"📊 *Training-Status*\n"
                  f"Datensatz: {total} Beispiele ({teacher} Cloud/Teacher)\n"
                  f"Minimum: {MIN}\n"
                  f"Basismodell: {report.get('house_base', '?')}\n"
                  f"Bereits trainiert: {'✅' if report.get('house_trained') else '—'}\n"
                  f"Version: {report.get('house_version', 0)}\n"
                  f"Fehlende Deps: {', '.join(deps) if deps else 'keine ✅'}\n\n"
                  f"{'✅ Bereit für /autotrain' if total >= MIN else f'⏳ Noch {MIN - total} Beispiele nötig'}",
                  parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"❌ Fehler: {exc}")

    elif cmd == "autotrain":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin darf /autotrain nutzen.")
        _typing(token, chat_id)
        try:
            from ...training.train import train_report
            from pathlib import Path
            import threading
            report = train_report()
            total = report["dataset"]["total"]
            MIN = 50
            if total < MIN:
                _send(token, chat_id,
                      f"⏳ Noch {MIN - total} Beispiele nötig (aktuell {total}/{MIN}).\n"
                      "Nutze den Bot weiter — jede Anfrage sammelt Daten.")
                return

            def _bg_train():
                from ...training.train import train
                from ...training.scheduler import _notify_telegram, _save_last_count
                try:
                    out_dir = Path.home() / ".nexoryx" / "auto_training"
                    result = train(out_dir)
                    action = result.get("action", "?")
                    if action == "trained":
                        v = result.get("house_version", "?")
                        _notify_telegram(f"✅ *Auto-Training abgeschlossen* — Version {v}")
                        _save_last_count(total)
                    elif action == "script_generated":
                        deps_str = ", ".join(result.get("deps_missing", []))
                        _notify_telegram(
                            f"📝 *Training-Skript erzeugt*\n"
                            f"Fehlende Pakete: {deps_str}\n"
                            f"{result.get('instructions', '')}"
                        )
                        _save_last_count(total)
                    elif action == "failed":
                        _notify_telegram(f"❌ *Auto-Training fehlgeschlagen*\n{result.get('error', '?')}")
                    try:
                        from ...training.on_exit import run_background
                        run_background(console=None)
                    except Exception:
                        pass
                except Exception as exc:
                    _notify_telegram(f"❌ *Auto-Train Ausnahme:* {exc}")

            t = threading.Thread(target=_bg_train, daemon=True, name="nexoryx-tg-autotrain")
            t.start()
            _send(token, chat_id,
                  f"🏋️ *Auto-Training gestartet im Hintergrund*\n"
                  f"Datensatz: {total} Beispiele\n"
                  f"Du bekommst eine Nachricht wenn es fertig ist.",
                  parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"❌ Fehler: {exc}")

    # ── Speicher ──────────────────────────────────────────────────────────────
    elif cmd == "memory":
        hits = memory.recall(arg, limit=8) if arg else memory.recent(8)
        if not hits:
            return _send(token, chat_id, "Kein Speicher gefunden.")
        lines = [f"• [{m.scope}] {m.text[:180]}" for m in hits]
        _send(token, chat_id, "🧠 *Erinnerungen*\n\n" + "\n".join(lines), parse_mode="Markdown")

    elif cmd == "forget":
        if not arg:
            return _send(token, chat_id, "Nutzung: /forget <query>")
        n = memory.forget(arg)
        _send(token, chat_id, f"🗑️ {n} Einträge gelöscht.")

    elif cmd == "private":
        if user_id in private_users:
            private_users.discard(user_id)
            _send(token, chat_id, "🌐 Privat-Modus AUS — Cloud-Modelle erlaubt.")
        else:
            private_users.add(user_id)
            _send(token, chat_id, "🔒 Privat-Modus AN — nur lokale Modelle.")

    # ── Audit / Admin ─────────────────────────────────────────────────────────
    elif cmd == "audit":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin.")
        rows = tail(15)
        if not rows:
            return _send(token, chat_id, "Audit-Log leer.")
        lines = [f"[{r.get('ts','?')[:16]}] {r.get('event','?')}: {r.get('tool','')}" for r in rows]
        _send(token, chat_id, "📋 *Audit-Log*\n\n" + "\n".join(lines), parse_mode="Markdown")

    elif cmd == "users":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin.")
        try:
            cfg = cfg_mod.load()
            admin_id = getattr(cfg, "telegram_admin_id", None)
            allowlist = getattr(cfg, "telegram_allowlist", [])
            lines = [f"👑 Admin: {admin_id}"]
            for uid in allowlist:
                lines.append(f"• Nutzer: {uid}")
            _send(token, chat_id, "👥 *Registrierte Nutzer*\n\n" + "\n".join(lines), parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"Fehler: {exc}")

    elif cmd == "broadcast":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin.")
        if not arg:
            return _send(token, chat_id, "Nutzung: /broadcast <nachricht>")
        try:
            cfg = cfg_mod.load()
            targets = list(getattr(cfg, "telegram_allowlist", []))
            admin_id = getattr(cfg, "telegram_admin_id", None)
            if admin_id:
                targets.append(admin_id)
            sent = 0
            for tid in set(targets):
                _api(token, "sendMessage", chat_id=tid,
                     text=f"📢 *Broadcast von Admin:*\n\n{arg}", parse_mode="Markdown")
                sent += 1
            _send(token, chat_id, f"✅ Nachricht an {sent} Nutzer gesendet.")
        except Exception as exc:
            _send(token, chat_id, f"Fehler: {exc}")

    elif cmd == "restart":
        if role not in ("admin", "owner"):
            return _send(token, chat_id, "⛔ Nur Admin.")
        _send(token, chat_id, "🔄 Bot wird neu gestartet …")
        raise SystemExit(0)

    elif cmd == "agent":
        from ...agents import AGENTS
        names = "\n".join(f"• `{n}`" for n in AGENTS)
        _send(token, chat_id, f"🤖 *Agenten:*\n\n{names}", parse_mode="Markdown")

    elif cmd == "profile":
        try:
            from ...memory.persona import all_files, interest_counts
            files = all_files()
            if not files:
                _send(token, chat_id,
                      "📋 Noch kein Profil gespeichert.\n"
                      "Nexoryx lernt automatisch beim Chatten — sag z.B.:\n"
                      "• 'Merk dir, dass ich kurze Antworten bevorzuge'\n"
                      "• 'Ich arbeite als Entwickler'")
                return
            parts_out = ["📋 *Nutzer-Profil*\n"]
            _icons = {
                "user.md": "👤", "behavior.md": "⚙️", "corrections.md": "✏️",
                "interests.md": "🔍", "preferences.md": "🎨",
            }
            for fname, content in files.items():
                icon = _icons.get(fname, "◆")
                label = fname.replace(".md", "").replace("_", " ").capitalize()
                # Nur Bullet-Zeilen extrahieren, Header-Zeilen weglassen
                lines = [l for l in content.splitlines() if l.startswith("- ")]
                if lines:
                    parts_out.append(f"{icon} *{label}*\n" + "\n".join(lines[:8]))
            out = "\n\n".join(parts_out)
            # Admin: Interessen-Statistik anhängen
            if role in ("admin", "owner"):
                counts = interest_counts()
                if counts:
                    top = sorted(counts.items(), key=lambda x: -x[1])[:8]
                    stat_lines = "\n".join(f"• {t}: ×{c}" for t, c in top)
                    out += f"\n\n📊 *Interessen-Statistik (Admin)*\n{stat_lines}"
            _send(token, chat_id, out[:4000], parse_mode="Markdown")
        except Exception as exc:
            _send(token, chat_id, f"❌ Fehler: {exc}")

    elif cmd == "cancel":
        _send(token, chat_id, "⛔ Abgebrochen.")

    elif text.startswith("/"):
        _send(token, chat_id, f"❓ Unbekannter Befehl: `{cmd}`\n/help für die Liste.", parse_mode="Markdown")

    else:
        # Plain-Text → direkt als Frage an die KI (kein /ask nötig)
        _typing(token, chat_id)
        try:
            from ...orchestrator.fc_runner import run_fc, available_model
            fc_model = available_model()
            if fc_model:
                ctx = ToolContext(role=role, actor=f"telegram:{user_id}",
                                  auto_approve=(role in ("admin", "owner")),
                                  sandbox=True)
                answer, _ = run_fc(text, ctx, model=fc_model)
            else:
                res = orch.run(text, plan=False)
                answer = res.answer
        except Exception as exc:
            answer = f"❌ Fehler: {exc}"
        _send(token, chat_id, answer)
