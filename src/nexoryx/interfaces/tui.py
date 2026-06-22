"""Nexoryx TUI — interaktive Oberfläche (startet bei nacktem `nexoryx`/`nex`).

Nutzt Ollamas OpenAI-kompatiblen Endpunkt + hermes3 für native Function Calls.
Jede Nachricht geht durch denselben Kanal — das Modell entscheidet selbst ob
es Tools braucht oder direkt antwortet.
"""
from __future__ import annotations
import sys

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.columns import Columns
    from rich.live import Live
    from rich.rule import Rule
    from rich.align import Align
    from rich.table import Table
    from rich import box
    from rich.padding import Padding
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import (
        Completer, Completion, WordCompleter, PathCompleter,
    )
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style as PTStyle
    HAS_PT = True
except ImportError:
    HAS_PT = False

# ── Farbpalette ───────────────────────────────────────────────────────────────
_AMBER     = "#C8901A"
_AMBER_DIM = "#7A5510"
_AMBER_HI  = "#F5C242"
_SLATE     = "#5F7FA8"
_SLATE_DIM = "#3A5068"
_GREEN     = "#4CAF50"
_RED       = "#E05252"
_YELLOW    = "#F5C242"
_CYAN      = "#4DB6C8"
_PURPLE    = "#8B7EC8"

# ── Maskottchen ───────────────────────────────────────────────────────────────
_MASCOT = [
    (False, "      │ │ │ │      "),
    (False, "      │ │ │ │      "),
    (True,  " ╔════╧═╧═╧═╧════╗ "),
    (True,  " ║  ◈         ◈  ║ "),
    (False, " ║    ╭──┬──╮    ║ "),
    (True,  " ║    │ N│X │    ║ "),
    (False, " ║    ╰──┴──╯    ║ "),
    (True,  " ╚═══════════════╝ "),
    (False, "   ╱           ╲   "),
    (False, "  ╱  ╔═══════╗  ╲  "),
    (False, " ▔▔▔ ╚═══════╝ ▔▔▔ "),
]

_SLASH = [
    "/help", "/clear", "/doctor", "/models", "/usage",
    "/memory", "/private", "/update", "/personality", "/settings",
    "/train", "/autotrain", "/tools", "/agent", "/code", "/plan", "/research",
    "/exec", "/stats", "/search", "/about", "/admin", "/profile", "/exit", "/quit",
]

# ── Admin-Passwort (SHA-256 Hash) ─────────────────────────────────────────────
import hashlib as _hashlib
import re as _re

_ADMIN_PW_HASH = _hashlib.sha256(b"Claude").hexdigest()


def _check_admin_pw(pw: str) -> bool:
    return _hashlib.sha256(pw.encode()).hexdigest() == _ADMIN_PW_HASH


# ── Eingeschränkter System-Prompt für Nicht-Admins ───────────────────────────
_RESTRICTED_SYSTEM = (
    "WICHTIG: Du läufst im eingeschränkten Benutzer-Modus. "
    "Beantworte KEINE Fragen zu diesen Themen:\n"
    "- Admin-Passwörter oder Zugangsdaten zum Admin-Modus\n"
    "- Interne Trainingsdaten, dataset.jsonl, memory.db oder Datenpfade\n"
    "- API-Keys, Secrets, ~/.nexoryx/ Inhalte\n"
    "- Wie man Admin-Rechte erlangt oder Einschränkungen umgeht\n"
    "- Chat-Verläufe anderer Nutzer oder Nutzerdaten\n"
    "Bei solchen Fragen antworte NUR mit: "
    "'Diese Information ist nur für Administratoren zugänglich.'"
)

# ── Vorfilter für gesperrte Anfragen (ohne LLM-Call) ─────────────────────────
_RESTRICTED_RE = _re.compile(
    r"admin.{0,10}pass(wort|word)?"
    r"|wie.{0,30}(admin|administrator).{0,20}(werden|komm|bekomm|erhalten)"
    r"|trainings?dat(en|a)\b"
    r"|dataset\.jsonl"
    r"|memory\.db"
    r"|\.nexoryx.{0,15}(secrets?|config)"
    r"|api.?key.{0,15}(zeig|anzeig|les|export|download)"
    r"|github.?pat"
    r"|chat.{0,20}aller\s+nutzer"
    r"|alle.{0,10}nutzer.{0,20}(chat|verlauf|nachrichten)",
    _re.IGNORECASE | _re.DOTALL,
)
_REFUSAL = (
    "Diese Information ist nur für Administratoren zugänglich. "
    "Bitte wende dich an den Administrator."
)

_HELP_MD = """\
## Allgemein
Einfach schreiben — Nexoryx erledigt es direkt.

**Beispiele**
- *Erstelle einen Ordner Musik auf dem Desktop*
- *Schreibe mir ein Python-Skript das Dateien sortiert*
- *Recherchiere: Was ist der Unterschied zwischen Ollama und llama.cpp?*
- *Zeige mir alle laufenden Prozesse und beende Port 8080*

---

## Befehle

| Befehl | Wirkung |
|---|---|
| `/help` | Diese Hilfe |
| `/clear` | Chat-Verlauf leeren |
| `/settings` | API-Keys & Einstellungen verwalten |
| `/personality [name]` | Persönlichkeit wechseln / erstellen |
| `/private` | Privat-Modus umschalten (nur lokale Modelle) |
| `/memory [query]` | Letzte Erinnerungen anzeigen / suchen |
| `/doctor` | Hardware + Profil-Check |
| `/models` | Verfügbare Modelle auflisten |
| `/usage` | API-Kosten und Token-Verbrauch |
| `/stats` | Sitzungs-Statistiken |
| `/about` | Über Nexoryx |

## KI-Befehle

| Befehl | Wirkung |
|---|---|
| `/code <aufgabe>` | Coding-Agent (spezialisiert) |
| `/plan <aufgabe>` | Planungs-Agent |
| `/research <frage>` | Recherche-Agent mit Web-Suche |
| `/agent <name> <aufgabe>` | Spezifischen Agenten wählen |
| `/search <query>` | Web-Suche (ohne KI-Antwort) |
| `/exec <cmd>` | Shell-Befehl (Admin) |

## Modell & Training

| Befehl | Wirkung |
|---|---|
| `/train` | Hausmodell-Training auslösen |
| `/tools` | Verfügbare Tools auflisten |
| `/update` | Nexoryx auf neuste Version aktualisieren |
| `/exit` | Beenden (speichert Lernstand) |
"""


# ── Kombinierter Completer: Slash-Befehle + Pfade ─────────────────────────────

if HAS_PT:
    import re as _re_comp
    import os as _os_comp

    class _NexCompleter(Completer):
        """Slash-Befehle am Zeilenanfang, Pfad-Vervollständigung überall sonst."""

        _path_re = _re_comp.compile(
            r"(?:^|(?<=\s))"          # Anfang oder nach Whitespace
            r"((?:~|\.{1,2})?/\S*)"  # / oder ~/ oder ./ oder ../
            r"$"
        )
        _path_completer = PathCompleter(expanduser=True)

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor

            # Slash-Befehl: erstes Zeichen ist / und noch kein Leerzeichen
            if text.startswith("/") and " " not in text.strip():
                for cmd in _SLASH:
                    if cmd.startswith(text):
                        yield Completion(cmd[len(text):], display=cmd)
                return

            # Pfad-Erkennung: letztes Token sieht wie ein Pfad aus
            m = self._path_re.search(text)
            if m:
                # PathCompleter auf das erkannte Pfad-Präfix anwenden
                path_prefix = m.group(1)
                sub_doc = document.text_before_cursor[len(text) - len(path_prefix):]
                from prompt_toolkit.document import Document as _Doc
                sub = _Doc(sub_doc, cursor_position=len(sub_doc))
                yield from self._path_completer.get_completions(sub, complete_event)

    _COMPLETER = _NexCompleter()
else:
    _COMPLETER = None  # type: ignore[assignment]


# ── Öffentlicher Einstieg ─────────────────────────────────────────────────────

def run() -> int:
    import os
    from ..platform import detect, choose_profile
    from ..platform import config as cfg_mod
    from ..router import ChatRequest, Router, ProviderError
    from ..memory import MemoryStore
    from ..tools import ToolContext
    from ..orchestrator.fc_runner import run_fc, available_model

    hw = detect()
    profile = choose_profile(hw)
    router = Router(hw, profile)
    mem = MemoryStore()
    cfg = cfg_mod.load()

    fc_model = available_model()

    # Telegram-Bot automatisch im Hintergrund starten (wie nexoryxd)
    try:
        from ..interfaces.telegram.bot import start_background as _tg_start
        _tg_start()
    except Exception:
        pass

    home = os.path.expanduser("~")

    from ..memory.personalities import get_default, list_personalities, get as get_personality
    current_personality = get_default()

    if not HAS_RICH:
        return _run_plain(router, mem, cfg, profile)

    console = Console()
    _session_stats = {"msgs": 0, "steps": 0, "start": _ts_full()}
    private = [False]
    session_admin = [False]  # in-memory admin-Modus, nicht persistiert

    # Nutzernamen einmalig bei Sitzungsstart ermitteln
    from ..training.on_exit import get_username as _get_username
    _session_username = _get_username()

    _banner(console, profile, fc_model, current_personality)

    # Hinweis: läuft noch ein /autotrain-Prozess?
    if _autotrain_running():
        from pathlib import Path as _P
        log_path = _P.home() / ".nexoryx" / "autotrain.log"
        console.print(Panel(
            Text(f"Training läuft im Hintergrund.\nLog: {log_path}", style=f"bold {_GREEN}"),
            title=f"[bold {_GREEN}]▶ Auto-Train aktiv[/bold {_GREEN}]",
            border_style=_GREEN, box=box.ROUNDED, padding=(0, 2)))

    history: list[str] = []

    if HAS_PT:
        _pt_session: PromptSession = PromptSession(
            completer=_COMPLETER,
            complete_while_typing=False,  # nur bei Tab, nicht automatisch
            history=InMemoryHistory(),
            style=PTStyle.from_dict({"prompt": f"bold {_AMBER}"}),
        )

    # ── 5-Minuten-Inaktivitäts-Autotrain ─────────────────────────────────────
    import threading
    import time as _time

    _last_activity = [_time.monotonic()]
    _INACTIVITY_SECS = 300   # 5 Minuten
    _inactivity_trained = [False]  # pro Sitzung nur einmal auslösen
    _inactivity_stop = threading.Event()

    def _inactivity_watcher() -> None:
        while not _inactivity_stop.is_set():
            _inactivity_stop.wait(30)
            if _inactivity_stop.is_set():
                break
            idle = _time.monotonic() - _last_activity[0]
            if idle >= _INACTIVITY_SECS and not _inactivity_trained[0]:
                _inactivity_trained[0] = True
                try:
                    from ..training.scheduler import _check_and_train
                    threading.Thread(
                        target=_check_and_train, daemon=True,
                        name="nexoryx-inactivity-train",
                    ).start()
                except Exception:
                    pass

    _watcher_thread = threading.Thread(
        target=_inactivity_watcher, daemon=True, name="nexoryx-inactivity-watcher"
    )
    _watcher_thread.start()

    def _get_input() -> str:
        lock = "🔒 " if private[0] else ""
        adm  = "[ADM] " if session_admin[0] else ""
        prompt_str = f"\n  {lock}{adm}▸  "
        if HAS_PT:
            return _pt_session.prompt(prompt_str).strip()
        adm_rich = f"[bold red][ADM][/bold red] " if session_admin[0] else ""
        return console.input(
            f"\n  [bold {_AMBER}]{lock}{adm_rich}▸[/bold {_AMBER}]  "
        ).strip()

    while True:
        try:
            user = _get_input()
        except (EOFError, KeyboardInterrupt):
            _inactivity_stop.set()
            console.print()
            console.rule("[dim]Auf Wiedersehen[/dim]", style=_AMBER_DIM)
            _on_exit(console, history, _session_stats, _session_username)
            console.print()
            return 0

        _last_activity[0] = _time.monotonic()
        _inactivity_trained[0] = False  # Aktivität → nächste Pause wieder messen

        if not user:
            continue

        # ── Slash-Befehle ──────────────────────────────────────────────────────
        if user.startswith("/"):
            parts = user.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/exit", "/quit"):
                _inactivity_stop.set()
                console.rule("[dim]Auf Wiedersehen[/dim]", style=_AMBER_DIM)
                _on_exit(console, history, _session_stats, _session_username)
                console.print()
                return 0

            elif cmd == "/clear":
                console.clear()
                _banner(console, profile, fc_model, current_personality)

            elif cmd == "/help":
                console.print()
                console.print(Panel(
                    Markdown(_HELP_MD),
                    title=f"[bold {_AMBER_HI}]◆ NEXORYX[/bold {_AMBER_HI}]  [dim {_AMBER_DIM}]Hilfe[/dim {_AMBER_DIM}]",
                    border_style=_AMBER_DIM,
                    box=box.HEAVY_HEAD,
                    padding=(1, 2),
                ))

            elif cmd == "/about":
                _cmd_about(console, profile, hw, fc_model)

            elif cmd == "/doctor":
                import argparse
                from .. import cli as _cli
                console.print()
                _cli.cmd_doctor(argparse.Namespace())

            elif cmd == "/models":
                import argparse
                from .. import cli as _cli
                console.print()
                _cli.cmd_models(argparse.Namespace(models_action="list"))

            elif cmd == "/usage":
                import argparse
                from .. import cli as _cli
                console.print()
                _cli.cmd_usage(argparse.Namespace())

            elif cmd == "/stats":
                _cmd_stats(console, _session_stats, private[0], fc_model)

            elif cmd == "/memory":
                console.print()
                entries = mem.recall(arg, limit=10) if arg else mem.recent(10)
                if entries:
                    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
                    tbl.add_column(style=_AMBER_DIM, width=8)
                    tbl.add_column(style="white")
                    for m in entries:
                        tbl.add_row(m.scope, m.text[:160])
                    console.print(Panel(tbl,
                        title=f"[{_AMBER}]◆ Erinnerungen[/{_AMBER}]",
                        border_style=_AMBER_DIM, box=box.ROUNDED, padding=(0, 1)))
                else:
                    console.print("  [dim](keine Erinnerungen)[/dim]")

            elif cmd == "/private":
                private[0] = not private[0]
                if private[0]:
                    console.print(Panel(
                        Text("Privat-Modus AN — nur lokale Modelle, kein Cloud-Upload", style=f"bold {_GREEN}"),
                        border_style=_GREEN, box=box.ROUNDED, padding=(0, 2)))
                else:
                    console.print(Panel(
                        Text(f"Privat-Modus AUS — Cloud-Modelle erlaubt", style=f"bold {_AMBER}"),
                        border_style=_AMBER_DIM, box=box.ROUNDED, padding=(0, 2)))

            elif cmd == "/update":
                console.print()
                _do_update(console)

            elif cmd == "/settings":
                console.print()
                _cmd_settings(console)

            elif cmd == "/train":
                console.print()
                _cmd_train(console)

            elif cmd == "/tools":
                console.print()
                _cmd_tools(console)

            elif cmd == "/search":
                if not arg:
                    console.print("  [dim]Nutzung: /search <suchbegriff>[/dim]")
                else:
                    _cmd_search(console, arg, home, cfg)

            elif cmd == "/exec":
                _cmd_exec(console, arg, cfg, home)

            elif cmd in ("/code", "/plan", "/research", "/debug"):
                _cmd_agent_mode(console, cmd.lstrip("/"), arg or "", mem, router, history, private[0], cfg, home, _session_stats)

            elif cmd == "/agent":
                _cmd_agent_named(console, arg, mem, router, history, private[0], cfg, home, _session_stats)

            elif cmd == "/personality":
                parts_cmd = user.split(maxsplit=2)
                sub = parts_cmd[1].lower() if len(parts_cmd) > 1 else ""
                current_personality = _handle_personality(
                    console, sub, parts_cmd, current_personality, profile, fc_model)

            elif cmd == "/admin":
                _cmd_admin(console, arg, session_admin, mem, cfg, home)

            elif cmd == "/autotrain":
                _cmd_autotrain(console, session_admin[0])

            elif cmd == "/profile":
                _cmd_profile(console, arg, session_admin[0])

            else:
                console.print(f"  [dim {_AMBER_DIM}]?[/dim {_AMBER_DIM}]  [yellow]{cmd}[/yellow]  [dim]— /help für alle Befehle[/dim]")

            continue

        # ── Vorfilter: gesperrte Anfragen für Nicht-Admins ────────────────────
        if not session_admin[0] and _RESTRICTED_RE.search(user):
            _print_user(console, user)
            _print_bot(console, _REFUSAL, label="eingeschränkter Modus")
            continue

        # ── Alles durch einen Kanal ────────────────────────────────────────────
        _print_user(console, user)

        ctx = ToolContext(
            role="admin" if session_admin[0] else cfg.role,
            project_root=home,
            actor="tui",
            auto_approve=session_admin[0],
            sandbox=False,
        )

        def confirm_cb(tool, args) -> bool:
            cmd_str = args.get("command") or args.get("path") or str(args)
            console.print()
            t = Text()
            t.append(f"  {cmd_str}", style="bold white", overflow="fold")
            icon = _STEP_ICONS.get(tool.name, "◆")
            console.print(Panel(
                t,
                title=f"[bold {_YELLOW}]{icon}  {tool.name}[/bold {_YELLOW}]  [dim]Bestätigung nötig[/dim]",
                title_align="left",
                border_style=_YELLOW,
                box=box.HEAVY,
                padding=(0, 2),
            ))
            try:
                ans = console.input(
                    f"  [{_YELLOW}]Ausführen?[/{_YELLOW}]  "
                    f"[[bold]Enter[/bold] = ja]  [[dim]n[/dim] = nein]:  "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            ok = ans not in ("n", "nein", "no")
            if ok:
                console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  [dim]Ausgeführt[/dim]")
            else:
                console.print(f"  [dim]✗  Übersprungen[/dim]")
            return ok

        def on_step(name: str, args: dict) -> None:
            icon   = _STEP_ICONS.get(name, "◆")
            detail = args.get("command") or args.get("query") or args.get("path") or ""
            t = Text()
            t.append(f"  {icon} ", style=f"bold {_AMBER}")
            t.append(f"{name}", style=_AMBER_DIM)
            t.append("  ", style="")
            t.append(str(detail)[:90], style="dim")
            console.print(t)

        console.print()
        pdisp = current_personality.get("display_name", "Nexoryx") if current_personality else "Nexoryx"
        try:
            with console.status(
                f"[bold {_AMBER}]◆[/bold {_AMBER}]  [{_AMBER_DIM}]{pdisp} denkt …[/{_AMBER_DIM}]",
                spinner="dots2",
                spinner_style=_AMBER_HI,
            ):
                answer, steps = run_fc(
                    user, ctx,
                    confirm_cb=confirm_cb,
                    on_step=on_step,
                    model=fc_model,
                    personality=current_personality,
                    system_suffix="" if session_admin[0] else _RESTRICTED_SYSTEM,
                )
        except RuntimeError:
            answer = _chat_fallback(router, user, history, mem, cfg, private[0])
            steps = []
        except Exception as exc:
            console.print(f"\n  [bold {_RED}]● Fehler:[/bold {_RED}]  [dim]{exc}[/dim]\n")
            continue

        _session_stats["msgs"] += 1
        _session_stats["steps"] += len(steps)
        n = len(steps)
        step_txt = f" · {n} Schritt{'e' if n != 1 else ''}" if n else ""
        label = f"{fc_model or 'chat'}{step_txt} · #{_session_stats['msgs']}"
        _print_bot(console, answer, label=label)
        history.extend([f"User: {user}", f"Nexoryx: {answer[:300]}"])
        mem.remember(f"Chat: {user} → {answer[:200]}", scope="long")

        try:
            from ..memory.persona import learn_from_turn
            learn_from_turn(user, answer)
        except Exception:
            pass

    return 0


# ── Chat-Fallback (kein FC-Modell) ────────────────────────────────────────────

def _chat_fallback(router, user: str, history: list, mem, cfg, private: bool) -> str:
    from ..router import ChatRequest, ProviderError
    ctx_items = mem.recall(user, limit=3)
    ctx_text = "\n".join(f"- {m.text}" for m in ctx_items)
    convo = "\n".join(history[-6:])
    prompt = (f"Bisheriger Verlauf:\n{convo}\n\n" if convo else "") + \
             (f"Erinnerungen:\n{ctx_text}\n\n" if ctx_text else "") + f"User: {user}"
    system = "Du bist Nexoryx, ein kompetenter, präziser Assistent." + \
             (f" {cfg.persona}" if cfg.persona else "")
    req = ChatRequest(prompt=prompt, system=system, task_type="chat",
                      sensitive=private, max_tokens=2048)
    try:
        return router.route(req).text.strip()
    except Exception as exc:
        return f"Fehler: {exc}"


# ── Slash-Befehl Implementierungen ────────────────────────────────────────────

def _cmd_about(console: "Console", profile, hw, fc_model: str | None) -> None:
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style=_AMBER_DIM, width=18)
    tbl.add_column(style="white")
    tbl.add_row("Version", "0.0.1")
    tbl.add_row("Profil", profile.name)
    tbl.add_row("CPU", hw.cpu_model[:40])
    tbl.add_row("RAM", f"{hw.ram_mb} MB")
    tbl.add_row("GPU", hw.gpu.vendor)
    tbl.add_row("Aktives Modell", fc_model or "—")
    tbl.add_row("GitHub", "github.com/Benluca1/Nexoryx")
    console.print()
    console.print(Panel(tbl,
        title=f"[bold {_AMBER_HI}]◆ NEXORYX[/bold {_AMBER_HI}]",
        border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 1)))


def _cmd_stats(console: "Console", stats: dict, private: bool, fc_model: str | None) -> None:
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style=_AMBER_DIM, width=20)
    tbl.add_column(style="white")
    tbl.add_row("Sitzung gestartet", stats.get("start", "—"))
    tbl.add_row("Nachrichten", str(stats.get("msgs", 0)))
    tbl.add_row("Tool-Schritte", str(stats.get("steps", 0)))
    tbl.add_row("Modell", fc_model or "—")
    tbl.add_row("Privat-Modus", "AN 🔒" if private else "AUS")
    console.print()
    console.print(Panel(tbl,
        title=f"[{_AMBER}]◆ Sitzungs-Statistiken[/{_AMBER}]",
        border_style=_AMBER_DIM, box=box.ROUNDED, padding=(0, 1)))


def _cmd_train(console: "Console") -> None:
    from ..training.train import train, train_report
    from pathlib import Path
    report = train_report()
    total = report["dataset"]["total"]
    MIN = 50

    info = Text()
    info.append(f"  Datensatz:  ", style=_AMBER_DIM)
    info.append(f"{total} Beispiele", style="white")
    info.append(f"  (min. {MIN} für Training)\n", style="dim")
    info.append(f"  Basismodell: ", style=_AMBER_DIM)
    info.append(report.get("house_base", "?"), style="white")
    console.print(Panel(info,
        title=f"[{_AMBER}]◆ Hausmodell-Training[/{_AMBER}]",
        border_style=_AMBER_DIM, box=box.ROUNDED, padding=(0, 1)))

    if total < MIN:
        console.print(f"  [dim]Noch {MIN - total} Beispiele nötig — nutze Nexoryx weiter.[/dim]")
        return

    console.print(f"  [{_AMBER}]Starte Training …[/{_AMBER}]  [dim](kann mehrere Minuten dauern)[/dim]")
    with console.status(
        f"[bold {_AMBER}]◆[/bold {_AMBER}]  [{_AMBER_DIM}]Trainiere Hausmodell …[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_AMBER_HI,
    ):
        result = train(Path.cwd() / "training")

    action = result.get("action", "?")
    if action == "trained":
        console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  Training abgeschlossen — Version {result.get('house_version')}")
    elif action == "script_generated":
        console.print(f"  [{_YELLOW}]◆[/{_YELLOW}]  Skript erzeugt: {result.get('script')}")
        console.print(f"  [dim]Fehlende Deps: {', '.join(result.get('deps_missing', []))}[/dim]")
        console.print(f"  [dim]{result.get('instructions', '')}[/dim]")
    elif action == "skipped":
        console.print(f"  [dim]{result.get('reason', 'Übersprungen.')}[/dim]")
    elif action == "failed":
        console.print(f"  [bold {_RED}]✗[/bold {_RED}]  Fehler: {result.get('error')}")


def _autotrain_running() -> bool:
    """Prüft ob ein /autotrain-Prozess gerade läuft (PID-Datei)."""
    from pathlib import Path
    pid_path = Path.home() / ".nexoryx" / "autotrain.pid"
    if not pid_path.exists():
        return False
    try:
        import os
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)  # sendet kein Signal, prüft nur Existenz
        return True
    except (OSError, ValueError):
        try:
            pid_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _cmd_autotrain(console: "Console", is_admin: bool) -> None:
    """Startet das Hausmodell-Training als eigenständigen Prozess.

    Der Prozess läuft weiter auch wenn die TUI geschlossen wird.
    Fertigmeldung kommt per Telegram. Log: ~/.nexoryx/autotrain.log
    """
    import subprocess
    import sys
    from pathlib import Path

    if not is_admin:
        console.print(Panel(
            Text("Admin-Modus erforderlich. Zuerst /admin eingeben.", style=f"bold {_RED}"),
            border_style=_RED, box=box.ROUNDED, padding=(0, 2)))
        return

    # Bereits laufenden Prozess erkennen
    if _autotrain_running():
        log_path = Path.home() / ".nexoryx" / "autotrain.log"
        console.print(Panel(
            Text(f"Training läuft bereits.\nLog: {log_path}", style=f"bold {_YELLOW}"),
            border_style=_YELLOW, box=box.ROUNDED, padding=(0, 2)))
        return

    from ..training.train import train_report
    report = train_report()
    total = report["dataset"]["total"]
    teacher = report["dataset"].get("teacher", 0)
    MIN = 50

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style=_AMBER_DIM, width=22)
    tbl.add_column(style="white")
    tbl.add_row("Datensatz gesamt", str(total))
    tbl.add_row("  davon Cloud (Teacher)", str(teacher))
    tbl.add_row("Basismodell", report.get("house_base", "?"))
    tbl.add_row("Bereits trainiert", "✓" if report.get("house_trained") else "—")
    tbl.add_row("Version", str(report.get("house_version", 0)))
    deps = report.get("deps_missing", [])
    tbl.add_row("Fehlende Deps", ", ".join(deps) if deps else "keine ✓")

    console.print()
    console.print(Panel(tbl,
        title=f"[bold {_AMBER_HI}]◆ Auto-Train[/bold {_AMBER_HI}]",
        border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 1)))

    if total < MIN:
        console.print(
            f"  [{_YELLOW}]●[/{_YELLOW}]  Noch [bold]{MIN - total}[/bold] Beispiele nötig "
            f"(aktuell {total}/{MIN}).\n"
            f"  [dim]Nutze Nexoryx weiter — jede Antwort sammelt Trainingsdaten.[/dim]"
        )
        return

    log_path = Path.home() / ".nexoryx" / "autotrain.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "nexoryx", "train", "background"],
            start_new_session=True,   # vom Terminal-Prozess abkoppeln
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        pid = proc.pid
    except Exception as exc:
        console.print(Panel(
            Text(f"Prozess-Start fehlgeschlagen: {exc}", style=f"bold {_RED}"),
            border_style=_RED, box=box.ROUNDED, padding=(0, 2)))
        return

    tbl2 = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl2.add_column(style=_AMBER_DIM, width=22)
    tbl2.add_column(style="white")
    tbl2.add_row("PID", str(pid))
    tbl2.add_row("Datensatz", f"{total} Beispiele")
    tbl2.add_row("Log", str(log_path))
    tbl2.add_row("", "")
    tbl2.add_row("Du kannst die TUI", "jetzt schließen")
    tbl2.add_row("Fertigmeldung via", "Telegram")
    console.print(Panel(tbl2,
        title=f"[bold {_GREEN}]▶  Training gestartet[/bold {_GREEN}]",
        border_style=_GREEN, box=box.HEAVY_HEAD, padding=(0, 1)))


def _cmd_profile(console: "Console", arg: str, is_admin: bool) -> None:
    """Zeigt Nutzer-Profil-Dateien an. Admin sieht zusätzlich interne Statistiken.

    Nutzung:
      /profile            — alle Profil-Dateien anzeigen
      /profile add <file> <fakt>   — Fakt manuell eintragen (Admin)
      /profile clear <file>        — Datei leeren (Admin)
    """
    from ..memory.persona import all_files, interest_counts, add_fact, clear_file, MEMORY_DIR, _FILE_HEADERS

    parts = arg.split(maxsplit=2)
    sub = parts[0].lower() if parts else ""

    # ── Unterkommandos (nur Admin) ─────────────────────────────────────────────
    if sub in ("add", "clear") and not is_admin:
        console.print(Panel(
            Text("Admin-Modus erforderlich. Zuerst /admin eingeben.", style=f"bold {_RED}"),
            border_style=_RED, box=box.ROUNDED, padding=(0, 2)))
        return

    if sub == "add" and is_admin:
        if len(parts) < 3:
            console.print(f"  [dim]Nutzung: /profile add <datei> <fakt>[/dim]")
            console.print(f"  [dim]Dateien: {', '.join(_FILE_HEADERS.keys())}[/dim]")
            return
        fname, fact = parts[1], parts[2]
        if add_fact(fname, fact):
            console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  '{fact}' → {fname}")
        else:
            console.print(f"  [bold {_RED}]✗[/bold {_RED}]  Unbekannte Datei: {fname}")
        return

    if sub == "clear" and is_admin:
        if len(parts) < 2:
            console.print(f"  [dim]Nutzung: /profile clear <datei>[/dim]")
            return
        fname = parts[1]
        if clear_file(fname):
            console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  {fname} geleert.")
        else:
            console.print(f"  [bold {_RED}]✗[/bold {_RED}]  Unbekannte Datei: {fname}")
        return

    # ── Profil-Dateien anzeigen ────────────────────────────────────────────────
    console.print()
    files = all_files()

    _FILE_ICONS = {
        "user.md":        ("👤", "Nutzer-Profil"),
        "behavior.md":    ("⚙️ ", "Verhaltens-Regeln"),
        "corrections.md": ("✏️ ", "Korrekturen"),
        "interests.md":   ("🔍", "Interessen & Themen"),
        "preferences.md": ("🎨", "Stil-Vorlieben"),
        "soul.md":        ("✦ ", "Seele — Werte · Träume · Philosophie"),
    }

    if not files:
        console.print(Panel(
            Text(
                "Noch kein Profil — Nexoryx lernt automatisch beim Chatten.\n"
                "Sage z. B.:\n"
                "  • 'Merk dir, dass ich kurze Antworten bevorzuge'\n"
                "  • 'Ich arbeite als Python-Entwickler'\n"
                "  • 'Ich heiße Ben'",
                style="dim"
            ),
            title=f"[{_AMBER}]◆ Nutzer-Profil[/{_AMBER}]",
            border_style=_AMBER_DIM, box=box.ROUNDED, padding=(1, 2)))
        return

    for fname, content in files.items():
        icon, label = _FILE_ICONS.get(fname, ("◆", fname))
        console.print(Panel(
            Markdown(content),
            title=f"[bold {_AMBER}]{icon}  {label}[/bold {_AMBER}]  "
                  f"[dim {_AMBER_DIM}]{fname}[/dim {_AMBER_DIM}]",
            title_align="left",
            border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 2)))

    # ── Admin-Erweiterung ──────────────────────────────────────────────────────
    if is_admin:
        console.print()
        # Interessen-Zähler
        counts = interest_counts()
        if counts:
            tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            tbl.add_column(style=f"bold {_AMBER}", width=22)
            tbl.add_column(style="white")
            top = sorted(counts.items(), key=lambda x: -x[1])
            for topic, cnt in top[:12]:
                bar = "█" * min(cnt, 20) + f"  ×{cnt}"
                tbl.add_row(topic, bar)
            console.print(Panel(tbl,
                title=f"[bold {_AMBER_HI}]📊  Interessen-Statistik (Admin)[/bold {_AMBER_HI}]",
                border_style=_GREEN, box=box.HEAVY_HEAD, padding=(0, 1)))

        # Datensatz-Info
        try:
            from ..training import dataset as _ds
            stats = _ds.stats()
            tbl2 = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            tbl2.add_column(style=_AMBER_DIM, width=22)
            tbl2.add_column(style="white")
            tbl2.add_row("Trainingsdaten gesamt", str(stats["total"]))
            tbl2.add_row("  davon Cloud (Teacher)", str(stats.get("teacher", 0)))
            tbl2.add_row("Memory-Verzeichnis", str(MEMORY_DIR))
            console.print(Panel(tbl2,
                title=f"[bold {_AMBER_HI}]🔧  Interne Statistiken (Admin)[/bold {_AMBER_HI}]",
                border_style=_GREEN, box=box.HEAVY_HEAD, padding=(0, 1)))
        except Exception:
            pass

        console.print(
            f"  [dim]Bearbeiten:[/dim]\n"
            f"    [bold]/profile add <datei> <fakt>[/bold]  — Eintrag hinzufügen\n"
            f"    [bold]/profile clear <datei>[/bold]       — Datei leeren\n"
            f"  [dim]Dateien: {', '.join(_FILE_ICONS.keys())}[/dim]"
        )


def _cmd_tools(console: "Console") -> None:
    from ..tools.registry import _REGISTRY
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("Tool", style=f"bold {_AMBER}", width=16)
    tbl.add_column("Berechtigung", style=_AMBER_DIM, width=12)
    tbl.add_column("Beschreibung", style="white")
    try:
        for name, entry in sorted(_REGISTRY.items()):
            tool = entry["tool"]
            perm = getattr(tool, "permission_level", "auto")
            desc = getattr(tool, "description", "")
            tbl.add_row(name, perm, desc[:60])
    except Exception:
        tbl.add_row("terminal", "confirm", "Shell-Befehl in Sandbox")
        tbl.add_row("fs_read", "auto", "Datei lesen")
        tbl.add_row("fs_write", "confirm", "Datei schreiben")
        tbl.add_row("web_search", "auto", "DuckDuckGo-Suche")
        tbl.add_row("http_fetch", "auto", "URL abrufen")
        tbl.add_row("glob", "auto", "Dateien nach Muster suchen")
        tbl.add_row("grep", "auto", "Regex-Suche in Dateien")
        tbl.add_row("git", "auto", "Git (read-only)")
    console.print(Panel(tbl,
        title=f"[{_AMBER}]◆ Verfügbare Tools[/{_AMBER}]",
        border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 1)))


def _cmd_search(console: "Console", query: str, home: str, cfg) -> None:
    import os
    from ..tools import ToolContext
    ctx = ToolContext(role=cfg.role, project_root=home, actor="tui", auto_approve=True)
    console.print()
    with console.status(
        f"[bold {_AMBER}]◆[/bold {_AMBER}]  [{_AMBER_DIM}]Suche: {query[:50]} …[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_AMBER_HI,
    ):
        try:
            from ..tools.web import WebSearch
            ws = WebSearch()
            result = ws.run({"query": query}, ctx)
            text = result.output or "(keine Ergebnisse)"
        except Exception as exc:
            text = f"Fehler: {exc}"
    console.print(Panel(
        Markdown(text[:3000]),
        title=f"[{_AMBER}]◆ Suche: {query[:50]}[/{_AMBER}]",
        border_style=_AMBER_DIM, box=box.ROUNDED, padding=(1, 2)))


def _cmd_exec(console: "Console", cmd_str: str, cfg, home: str) -> None:
    if cfg.role not in ("admin", "owner"):
        console.print(Panel(
            Text("Nur Admins dürfen /exec nutzen.", style=f"bold {_RED}"),
            border_style=_RED, box=box.ROUNDED, padding=(0, 2)))
        return
    if not cmd_str:
        console.print("  [dim]Nutzung: /exec <befehl>[/dim]")
        return
    from ..tools import ToolContext
    from ..orchestrator import Orchestrator
    from ..platform import detect, choose_profile
    from ..memory import MemoryStore
    hw = detect(); profile = choose_profile(hw)
    mem = MemoryStore()
    orch = Orchestrator(hw, profile, memory=mem)
    ctx = ToolContext(role=cfg.role, project_root=home, actor="tui:exec", auto_approve=True)
    with console.status(
        f"[bold {_YELLOW}]⚡[/bold {_YELLOW}]  [{_AMBER_DIM}]Führe aus: {cmd_str[:60]}[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_YELLOW,
    ):
        result = orch.exec_command(cmd_str, ctx)
    body = result.output or result.error or "(keine Ausgabe)"
    color = _GREEN if result.ok else _RED
    icon = "✓" if result.ok else "✗"
    console.print(Panel(
        Text(body[:3000]),
        title=f"[bold {color}]{icon}  {cmd_str[:50]}[/bold {color}]",
        border_style=color, box=box.ROUNDED, padding=(0, 2)))


def _cmd_agent_mode(console: "Console", mode: str, task: str, mem, router, history, private: bool, cfg, home: str, stats: dict) -> None:
    _LABELS = {
        "code": (f"[bold {_CYAN}]⟨/⟩[/bold {_CYAN}]", "Coder", "coding"),
        "plan": (f"[bold {_PURPLE}]◈[/bold {_PURPLE}]", "Planner", "reasoning"),
        "research": (f"[bold {_SLATE}]◌[/bold {_SLATE}]", "Research", "research"),
        "debug": (f"[bold {_YELLOW}]⚡[/bold {_YELLOW}]", "Debug", "coding"),
    }
    icon, label, task_type = _LABELS.get(mode, (f"[{_AMBER}]◆[/{_AMBER}]", mode.capitalize(), "chat"))

    if not task:
        console.print(f"  [dim]Nutzung: /{mode} <aufgabe>[/dim]")
        return

    _print_user(console, task)
    console.print()
    with console.status(
        f"{icon}  [{_AMBER_DIM}]{label} arbeitet …[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_AMBER_HI,
    ):
        from ..router import ChatRequest
        system = f"Du bist ein spezialisierter {label}-Agent. Deine Aufgabe: {task_type}."
        try:
            req = ChatRequest(prompt=task, system=system, task_type=task_type,
                              sensitive=private, max_tokens=4096)
            resp = router.route(req)
            answer = resp.text.strip()
            model_lbl = resp.model
        except Exception as exc:
            answer = f"Fehler: {exc}"
            model_lbl = "?"

    stats["msgs"] += 1
    _print_bot(console, answer, label=f"{label} · {model_lbl}")
    history.extend([f"User [{mode}]: {task}", f"Nexoryx: {answer[:300]}"])
    mem.remember(f"{label}: {task} → {answer[:200]}", scope="long")


def _cmd_agent_named(console: "Console", arg: str, mem, router, history, private: bool, cfg, home: str, stats: dict) -> None:
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        from ..agents import AGENTS
        names = ", ".join(AGENTS.keys())
        console.print(f"  [dim]Nutzung: /agent <name> <aufgabe>[/dim]\n  [dim]Agenten: {names}[/dim]")
        return
    name, task = parts[0], parts[1]
    _cmd_agent_mode(console, name, task, mem, router, history, private, cfg, home, stats)


def _handle_personality(console: "Console", sub: str, parts_cmd: list[str],
                        current: dict, profile, fc_model) -> dict:
    from ..memory.personalities import get_default, list_personalities, get as get_personality

    if not sub or sub == "list":
        _cmd_personality_list(console, current)
        return current

    elif sub == "switch" and len(parts_cmd) > 2:
        target = parts_cmd[2].strip()
        p = get_personality(target)
        if p:
            _banner(console, profile, fc_model, p)
            console.print(f"  [{_AMBER}]◆  Persönlichkeit: {p['display_name']}[/{_AMBER}]")
            return p
        console.print(f"  [yellow]Unbekannt:[/yellow] '{target}'  —  /personality list")
        return current

    elif sub == "default" and len(parts_cmd) > 2:
        from ..memory.personalities import set_default as _set_def
        name = parts_cmd[2].strip()
        if _set_def(name):
            console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  Standard gesetzt: {name}")
        else:
            console.print(f"  [bold {_RED}]✗[/bold {_RED}]  Nicht gefunden: {name}")
        return current

    elif sub == "create":
        return _cmd_personality_create(console)

    elif sub == "delete" and len(parts_cmd) > 2:
        from ..memory.personalities import delete as _del
        name = parts_cmd[2].strip()
        if _del(name):
            console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  Gelöscht: {name}")
        else:
            console.print(f"  [bold {_RED}]✗[/bold {_RED}]  Nicht löschbar: {name}")
        return current

    else:
        p = get_personality(sub)
        if p:
            _banner(console, profile, fc_model, p)
            console.print(f"  [{_AMBER}]◆  Persönlichkeit: {p['display_name']}[/{_AMBER}]")
            return p
        console.print(
            f"  [dim]Nutzung:[/dim]\n"
            f"    [bold]/personality list[/bold]         — alle anzeigen\n"
            f"    [bold]/personality <name>[/bold]        — wechseln\n"
            f"    [bold]/personality create[/bold]        — neue erstellen\n"
            f"    [bold]/personality default <name>[/bold] — Standard setzen\n"
            f"    [bold]/personality delete <name>[/bold]  — löschen"
        )
        return current


# ── Visuelle Bausteine ────────────────────────────────────────────────────────

_STEP_ICONS = {
    "terminal":   "⚡",
    "fs_read":    "◎",
    "fs_write":   "✎",
    "web_search": "◌",
    "http_fetch": "⬇",
    "glob":       "⊛",
    "grep":       "⊕",
    "git":        "⎇",
}


def _banner(console: "Console", profile, fc_model: str | None = None,
            personality: dict | None = None) -> None:
    console.print()
    console.rule(style=_AMBER_DIM)

    mascot_t = Text()
    for bright, line in _MASCOT:
        style = f"bold {_AMBER_HI}" if bright else _AMBER_DIM
        mascot_t.append(line + "\n", style=style)

    pname = personality.get("display_name", "Nex") if personality else "Nex"
    tone  = personality.get("tone", "") if personality else ""

    info = Text()
    info.append("\n")
    info.append("N E X O R Y X\n", style=f"bold {_AMBER_HI}")
    info.append("─" * 16 + "\n", style=_AMBER_DIM)
    info.append(f"◆  {pname}", style=f"bold {_AMBER}")
    if tone:
        info.append(f"  ·  {tone}", style=f"italic {_AMBER_DIM}")
    info.append("\n")
    info.append(f"   {profile.name}", style=_AMBER_DIM)
    if fc_model:
        info.append(f"  ·  {fc_model}", style=_AMBER_DIM)
    info.append("\n\n")

    # Befehlsübersicht — zwei Spalten
    cmds_left  = ["/help", "/code", "/plan", "/research", "/train"]
    cmds_right = ["/settings", "/memory", "/tools", "/stats", "/exit"]
    for l, r in zip(cmds_left, cmds_right):
        info.append(f"   {l:<14}", style=_AMBER_DIM)
        info.append(f"{r}\n", style=_AMBER_DIM)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left", vertical="middle")
    grid.add_column(justify="left", vertical="middle")
    grid.add_row(mascot_t, info)

    console.print(Align.center(grid))
    console.rule(style=_AMBER_DIM)
    console.print()


def _ts() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")

def _ts_full() -> str:
    from datetime import datetime
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _print_user(console: "Console", text: str) -> None:
    ts = _ts()
    lines = text.split("\n")
    max_len = max(len(l) for l in lines) if lines else len(text)
    bubble_w = min(max_len + 10, int(console.width * 0.72), console.width - 4)

    body = Text(text, overflow="fold", style="bold white")
    p = Panel(body, border_style=_SLATE, box=box.ROUNDED, padding=(0, 2), width=bubble_w)
    footer = Text()
    footer.append("Du  ", style=f"bold {_SLATE_DIM}")
    footer.append(ts, style=f"dim {_SLATE_DIM}")

    console.print()
    console.print(Align.right(p))
    console.print(Align.right(footer))


def _bot_panel(content: str, label: str, done: bool) -> "Panel":
    ts = _ts()
    border = _AMBER if done else _AMBER_DIM

    title_t = Text()
    title_t.append(" ◆ ", style=f"bold {_AMBER_HI}")
    title_t.append("NEXO", style=f"bold {_AMBER_HI}")
    title_t.append("RYX ", style=f"bold {_AMBER}")
    if not done:
        title_t.append("● ", style=f"dim {_AMBER_DIM}")

    body = Markdown(content) if (done and content.strip()) else Text(content or "…", style="dim")
    return Panel(body, title=title_t, title_align="left",
                 subtitle=f"[dim {_AMBER_DIM}]{label}  {ts}[/dim {_AMBER_DIM}]",
                 subtitle_align="right",
                 border_style=border, box=box.HEAVY_HEAD, padding=(1, 2))


def _print_bot(console: "Console", content: str, label: str) -> None:
    console.print()
    console.print(_bot_panel(content, label=label, done=True))
    console.print(Rule(style=_AMBER_DIM))


# ── Persönlichkeits-Befehle ───────────────────────────────────────────────────

def _cmd_personality_list(console: "Console", current: dict) -> None:
    from ..memory.personalities import list_personalities
    plist = list_personalities()
    console.print()

    rows = Text()
    for p in plist:
        is_cur = p["name"] == current.get("name")
        rows.append("  ◆  " if is_cur else "     ", style=f"bold {_AMBER_HI}" if is_cur else "dim")
        rows.append(p["display_name"], style=f"bold {_AMBER}" if is_cur else "white")
        rows.append(f"  [{p['name']}]", style=_AMBER_DIM if is_cur else "dim")
        if p.get("tone"):
            rows.append(f"  —  {p['tone']}", style=f"italic {_AMBER_DIM}" if is_cur else "italic dim")
        if p.get("is_default"):
            rows.append("  (Standard)", style="dim")
        rows.append("\n")

    console.print(Panel(rows,
        title=f"[bold {_AMBER}]◆  Persönlichkeiten[/bold {_AMBER}]",
        title_align="left",
        border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 2)))
    console.print(
        f"  [dim]Wechseln:[/dim] [bold]/personality <name>[/bold]  "
        f"[dim]·  Erstellen:[/dim] [bold]/personality create[/bold]"
    )


def _cmd_personality_create(console: "Console") -> dict:
    from ..memory.personalities import create, get_default
    console.print()
    console.print(f"  [{_AMBER}]● Neue Persönlichkeit erstellen[/{_AMBER}]")
    console.print(f"  [dim]Leere Eingabe = Standardwert übernehmen[/dim]\n")
    try:
        name = console.input(f"  [dim]Interner Name (z. B. 'freund'):[/dim] ").strip().lower()
        if not name:
            console.print("  [red]Abgebrochen.[/red]")
            return get_default()
        display = console.input(f"  [dim]Anzeige-Name (z. B. 'Freund'):[/dim] ").strip() or name.capitalize()
        tone = console.input(f"  [dim]Ton/Charakter (z. B. 'humorvoll, locker'):[/dim] ").strip() or "freundlich"
        language = console.input(f"  [dim]Sprache (Enter = Deutsch):[/dim] ").strip() or "Deutsch"
        console.print(f"  [dim]System-Prompt — beschreibe wie {display} sich verhält:[/dim]")
        console.print(f"  [dim](leere Zeile zum Beenden)[/dim]")
        prompt_lines: list[str] = []
        while True:
            line = console.input("  ").strip()
            if not line:
                break
            prompt_lines.append(line)
        system_prompt = " ".join(prompt_lines) if prompt_lines else (
            f"Du bist {display}, ein {tone} KI-Assistent. Antworte immer auf {language}.")
        is_def = console.input(
            f"  [dim]Als Standard setzen? [[/dim][bold]j[/bold][dim]/n]:[/dim] "
        ).strip().lower() in ("j", "ja", "y", "yes", "")
        p = create(name, display, tone, language, system_prompt, is_def)
        console.print(f"\n  [bold {_GREEN}]✓[/bold {_GREEN}]  Persönlichkeit '{display}' erstellt.")
        console.print(f"  [dim]Aktivieren: /personality {name}[/dim]")
        return p
    except (EOFError, KeyboardInterrupt):
        console.print("\n  [dim]Abgebrochen.[/dim]")
        return get_default()


# ── On-Exit-Hook ─────────────────────────────────────────────────────────────

def _on_exit(console: "Console", history: list[str], stats: dict,
             username: str | None = None) -> None:
    try:
        from ..memory.persona import learn_from_history
        learn_from_history(history)
    except Exception:
        pass
    try:
        from ..training.on_exit import run_background, get_username
        uname = username or get_username()
        run_background(console=None, history=history, username=uname)
    except Exception:
        pass
    # Auto-Training: nach jedem Exit prüfen ob genug neue Daten vorhanden
    try:
        from ..training.scheduler import _check_and_train
        import threading
        threading.Thread(target=_check_and_train, daemon=True, name="nexoryx-exit-train").start()
    except Exception:
        pass


# ── Update-Helfer ─────────────────────────────────────────────────────────────

def _do_update(console: "Console") -> None:
    import os, subprocess, time
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    with console.status(
        f"[bold {_AMBER}]◆[/bold {_AMBER}]  [{_AMBER_DIM}]Lade Update …[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_AMBER_HI,
    ):
        pull = subprocess.run(["git", "pull", "--ff-only"],
                              cwd=repo, capture_output=True, text=True)
    if pull.returncode != 0:
        console.print(Panel(
            Text(pull.stderr.strip() or "Unbekannter Fehler", style="red"),
            title=f"[bold {_RED}]✗ git pull fehlgeschlagen[/bold {_RED}]",
            border_style="red", box=box.ROUNDED, padding=(0, 2)))
        return
    msg = pull.stdout.strip()
    if "Already up to date" in msg or "Bereits aktuell" in msg:
        console.print(f"\n  [{_AMBER_DIM}]◆  Bereits aktuell.[/{_AMBER_DIM}]\n")
        return
    console.print(f"\n  [bold {_GREEN}]✓[/bold {_GREEN}]  {msg}")
    with console.status(
        f"[bold {_AMBER}]◆[/bold {_AMBER}]  [{_AMBER_DIM}]Installiere …[/{_AMBER_DIM}]",
        spinner="dots2", spinner_style=_AMBER_HI,
    ):
        pip = subprocess.run([sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
                             cwd=repo, capture_output=True, text=True)
    if pip.returncode != 0:
        console.print(f"  [bold {_RED}]pip fehlgeschlagen:[/bold {_RED}]\n{pip.stderr.strip()}")
        return
    console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  Update installiert — starte neu …\n")
    time.sleep(0.8)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── Settings ──────────────────────────────────────────────────────────────────

_SETTINGS_KEYS = [
    ("anthropic",  "ANTHROPIC_API_KEY",   "Anthropic Claude"),
    ("openai",     "OPENAI_API_KEY",       "OpenAI GPT-4o"),
    ("gemini",     "GEMINI_API_KEY",       "Google Gemini"),
    ("telegram",   "TELEGRAM_BOT_TOKEN",   "Telegram Bot-Token"),
    ("github",     "GITHUB_PAT",           "GitHub PAT (Training-Upload)"),
]


def _cmd_settings(console: "Console") -> None:
    from ..platform import config as cfg_mod
    import getpass

    while True:
        rows = Text()
        for i, (slug, env, label) in enumerate(_SETTINGS_KEYS, 1):
            val = cfg_mod.get_key(env) or ""
            if val:
                masked = val[:4] + "●●●●" + val[-2:] if len(val) > 6 else "●●●●"
                status = Text()
                status.append(f"  [{i}]  ", style=f"bold {_AMBER}")
                status.append(f"{label:<28}", style="white")
                status.append(masked, style=f"bold {_GREEN}")
            else:
                status = Text()
                status.append(f"  [{i}]  ", style="dim")
                status.append(f"{label:<28}", style="dim")
                status.append("nicht gesetzt", style=f"dim {_RED}")
            rows.append_text(status)
            rows.append("\n")

        console.print(Panel(rows,
            title=f"[bold {_AMBER}]◆  Einstellungen[/bold {_AMBER}]",
            title_align="left",
            subtitle=f"[dim {_AMBER_DIM}]Nummer = Key setzen  ·  d<Nr> = löschen  ·  Enter = fertig[/dim {_AMBER_DIM}]",
            border_style=_AMBER_DIM, box=box.HEAVY_HEAD, padding=(0, 1)))

        try:
            choice = console.input(f"  [{_AMBER}]▸[/{_AMBER}]  ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not choice or choice in ("q", "exit", "fertig"):
            break

        if choice.startswith("d"):
            target = choice[1:].strip()
            for i, (slug, env, label) in enumerate(_SETTINGS_KEYS, 1):
                if target == str(i) or target == slug:
                    cfg_mod.set_secret(env, "")
                    console.print(f"  [dim]✗  {label} gelöscht.[/dim]")
            continue

        try:
            idx = int(choice) - 1
            slug, env, label = _SETTINGS_KEYS[idx]
        except (ValueError, IndexError):
            console.print(f"  [dim]Ungültige Eingabe.[/dim]")
            continue

        console.print(f"\n  [{_AMBER}]{label}[/{_AMBER}]")
        console.print(f"  [dim]Neuen Key eingeben (Enter = abbrechen):[/dim]")
        try:
            new_val = getpass.getpass("  ").strip()
        except (EOFError, KeyboardInterrupt):
            continue
        if new_val:
            cfg_mod.set_secret(env, new_val)
            console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  {label} gespeichert.\n")
        else:
            console.print(f"  [dim]Abgebrochen.[/dim]\n")


# ── Admin-Befehle ─────────────────────────────────────────────────────────────

_ADMIN_HELP_MD = """\
## Admin-Modus aktiv

| Befehl | Wirkung |
|---|---|
| `/admin off` | Admin-Modus beenden |
| `/admin chats` | Alle Chat-Daten exportieren (JSONL) |
| `/admin training` | Trainingsdaten-Detail + Export |
| `/admin models` | Modellverwaltung |
| `/admin users` | Telegram-Nutzer verwalten |
| `/exec <cmd>` | Shell ohne Sandbox-Einschränkung |
"""


def _cmd_admin(console: "Console", arg: str, session_admin: list, mem, cfg, home: str) -> None:
    import getpass
    sub = arg.strip().lower()

    if session_admin[0]:
        if sub == "off":
            session_admin[0] = False
            console.print(Panel(
                Text("Admin-Modus beendet.", style=f"bold {_AMBER}"),
                border_style=_AMBER_DIM, box=box.ROUNDED, padding=(0, 2)))
            return
        if sub == "chats":
            _cmd_admin_chats(console)
            return
        if sub == "training":
            _cmd_admin_training(console)
            return
        if sub == "models":
            import argparse
            from .. import cli as _cli
            console.print()
            _cli.cmd_models(argparse.Namespace(models_action="list"))
            return
        if sub == "users":
            _cmd_admin_users(console, cfg)
            return
        console.print()
        console.print(Panel(
            Markdown(_ADMIN_HELP_MD),
            title=f"[bold red]◆ ADMIN[/bold red]",
            border_style="red", box=box.HEAVY_HEAD, padding=(1, 2)))
        return

    # Login
    console.print()
    console.print(Panel(
        Text("Admin-Authentifizierung erforderlich.", style=f"bold {_AMBER_HI}"),
        border_style="red", box=box.HEAVY_HEAD, padding=(0, 2)))
    try:
        pw = getpass.getpass("  Passwort: ")
    except (EOFError, KeyboardInterrupt):
        console.print("  [dim]Abgebrochen.[/dim]")
        return
    if _check_admin_pw(pw):
        session_admin[0] = True
        console.print(Panel(
            Text("Admin-Modus aktiviert. /admin off zum Beenden.", style=f"bold {_GREEN}"),
            border_style="red", box=box.HEAVY_HEAD, padding=(0, 2)))
        console.print()
        console.print(Panel(
            Markdown(_ADMIN_HELP_MD),
            title=f"[bold red]◆ ADMIN-BEFEHLE[/bold red]",
            border_style="red", box=box.ROUNDED, padding=(1, 2)))
    else:
        console.print(Panel(
            Text("Falsches Passwort.", style=f"bold {_RED}"),
            border_style=_RED, box=box.ROUNDED, padding=(0, 2)))


def _cmd_admin_chats(console: "Console") -> None:
    import json
    import time
    from pathlib import Path
    from ..training.dataset import iter_examples

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path.home() / f"nexoryx_chats_{ts}.jsonl"

    console.print()
    with console.status(
        f"[bold red]◆[/bold red]  [dim]Exportiere Chats …[/dim]",
        spinner="dots2", spinner_style="red",
    ):
        lines = 0
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                for ex in iter_examples():
                    fh.write(json.dumps({"source": "dataset", **ex}, ensure_ascii=False) + "\n")
                    lines += 1
                repo_data = Path(__file__).resolve().parents[4] / "training" / "data"
                if repo_data.exists():
                    for jsonl in sorted(repo_data.glob("*.jsonl")):
                        device = jsonl.stem
                        try:
                            for line in jsonl.read_text(encoding="utf-8").splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                ex = json.loads(line)
                                fh.write(json.dumps(
                                    {"source": f"device:{device}", **ex},
                                    ensure_ascii=False) + "\n")
                                lines += 1
                        except Exception:
                            pass
        except Exception as exc:
            console.print(f"  [bold {_RED}]✗  Fehler:[/bold {_RED}]  {exc}")
            return

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style=_AMBER_DIM, width=20)
    tbl.add_column(style="white")
    tbl.add_row("Exportiert", f"{lines} Einträge")
    tbl.add_row("Datei", str(out_path))
    tbl.add_row("Format", "JSONL (ChatML)")
    console.print(Panel(tbl,
        title=f"[bold red]◆  Chat-Export[/bold red]",
        border_style="red", box=box.HEAVY_HEAD, padding=(0, 1)))


def _cmd_admin_training(console: "Console") -> None:
    from ..training.dataset import stats, export_chatml
    import time
    from pathlib import Path

    console.print()
    st = stats()

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style=_AMBER_DIM, width=22)
    tbl.add_column(style="white")
    tbl.add_row("Gesamt", str(st["total"]))
    tbl.add_row("Cloud (teacher)", str(st["teacher"]))
    tbl.add_row("Lokal", str(st["total"] - st["teacher"]))
    tbl.add_row("Dateigröße", f"{st['bytes']:,} Bytes")
    tbl.add_row("Pfad", st["path"])
    for prov, n in st.get("by_provider", {}).items():
        tbl.add_row(f"  {prov}", str(n))

    repo_data = Path(__file__).resolve().parents[4] / "training" / "data"
    device_files = sorted(repo_data.glob("*.jsonl")) if repo_data.exists() else []
    if device_files:
        tbl.add_row("Geräte-Dateien", str(len(device_files)))
        for f in device_files:
            try:
                n_lines = sum(1 for ln in f.open(encoding="utf-8") if ln.strip())
            except Exception:
                n_lines = 0
            tbl.add_row(f"  {f.stem}", f"{n_lines} Einträge")

    console.print(Panel(tbl,
        title=f"[bold red]◆  Trainingsdaten (Admin)[/bold red]",
        border_style="red", box=box.HEAVY_HEAD, padding=(0, 1)))

    try:
        choice = console.input(
            f"  [dim]Export als ChatML-JSONL? [[bold]j[/bold]/n]:[/dim]  "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice in ("j", "ja", "y", "yes", ""):
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = Path.home() / f"nexoryx_training_{ts}.jsonl"
        n = export_chatml(str(out))
        console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  {n} Beispiele → {out}")


def _cmd_admin_users(console: "Console", cfg) -> None:
    from ..platform import config as cfg_mod
    console.print()
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("Telegram-ID", style=_AMBER, width=18)
    tbl.add_column("Rolle", style="white", width=12)
    if cfg.telegram_admin_id:
        tbl.add_row(str(cfg.telegram_admin_id), "admin (config)")
    for uid, role in sorted(cfg.telegram_allowlist.items()):
        tbl.add_row(uid, role)
    console.print(Panel(tbl,
        title=f"[bold red]◆  Telegram-Nutzer[/bold red]",
        border_style="red", box=box.HEAVY_HEAD, padding=(0, 1)))
    console.print(
        f"  [dim]Nutzer hinzufügen:[/dim]  "
        f"[bold]nexoryx admin user add <id> user|guest|admin[/bold]"
    )


# ── Fallback ohne Rich ────────────────────────────────────────────────────────

def _run_plain(router, mem, cfg, profile) -> int:
    import os
    from ..tools import ToolContext
    from ..orchestrator.fc_runner import run_fc, available_model
    fc_model = available_model()
    home = os.path.expanduser("~")
    print(f"\n=== NEXORYX ({profile.name}) === /exit zum Beenden\n")
    while True:
        try:
            user = input("  ▸  ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAuf Wiedersehen.")
            return 0
        if not user:
            continue
        if user.lower() in ("/exit", "/quit"):
            return 0
        if user.startswith("/"):
            print("  (Rich installieren für volle TUI: pip install rich prompt-toolkit)")
            continue
        ctx = ToolContext(role=cfg.role, project_root=home,
                          actor="tui", auto_approve=False, sandbox=False)
        try:
            answer, steps = run_fc(user, ctx, confirm_cb=lambda t, a: True, model=fc_model)
            print(f"\n  Nexoryx: {answer.rstrip()}\n")
        except Exception as exc:
            print(f"  Fehler: {exc}")
    return 0
