"""Nexoryx TUI — interaktive Oberfläche (startet bei nacktem `nexoryx`/`nex`).

Nutzt Olamas OpenAI-kompatiblen Endpunkt (openclaw) + hermes3 für native
Function Calls. Jede Nachricht geht durch denselben Kanal — das Modell
entscheidet selbst ob es Tools braucht oder direkt antwortet.
"""
from __future__ import annotations
import sys

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.live import Live
    from rich.rule import Rule
    from rich.align import Align
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
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
_YELLOW    = "#F5C242"

# ── Maskottchen ───────────────────────────────────────────────────────────────
# Nexo — stilisierter Oryx-Roboter (Hörner oben, Schaltkreis-Gesicht)
_MASCOT = [
    #  idx  content                   bright?
    (False, "       │     │       "),
    (False, "       │     │       "),
    (True,  "  ╔════╧═════╧════╗  "),
    (True,  "  ║   ◈       ◈   ║  "),
    (False, "  ║     ╭───╮     ║  "),
    (True,  "  ║     │ N │     ║  "),
    (False, "  ║     ╰───╯     ║  "),
    (True,  "  ╚═══════════════╝  "),
]

_SLASH = [
    "/help", "/clear", "/doctor", "/models", "/usage",
    "/memory", "/private", "/update", "/personality", "/settings", "/exit", "/quit",
]

_HELP_MD = """\
Einfach schreiben — Nexoryx erledigt es direkt.

**Beispiele**
- *Erstelle einen Ordner Musik auf dem Desktop*
- *Öffne Firefox*
- *Zeige mir alle Dateien im Home-Verzeichnis*
- *Schreibe eine Datei notiz.txt mit dem Text Hallo*
- *Was ist der Unterschied zwischen RAM und SSD?*

**Befehle**

| Befehl | Wirkung |
|---|---|
| `/help` | Diese Hilfe |
| `/settings` | API-Keys & Einstellungen verwalten |
| `/personality` | Persönlichkeit wechseln / erstellen |
| `/clear` | Chat leeren |
| `/private` | Privat-Modus (nur lokal) |
| `/memory` | Letzte Erinnerungen |
| `/doctor` | Hardware + Profil prüfen |
| `/models` | Verfügbare Modelle |
| `/update` | Auf neuste Version aktualisieren |
| `/exit` | Beenden |
"""


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
    home = os.path.expanduser("~")

    from ..memory.personalities import get_default, list_personalities, get as get_personality
    current_personality = get_default()

    if not HAS_RICH:
        return _run_plain(router, mem, cfg, profile)

    console = Console()
    _msg_counter = [0]  # mutable für Closure
    _banner(console, profile, fc_model, current_personality)

    history: list[str] = []
    private = False

    if HAS_PT:
        _session: PromptSession = PromptSession(
            completer=WordCompleter(_SLASH, sentence=True),
            history=InMemoryHistory(),
            style=PTStyle.from_dict({"prompt": f"bold {_AMBER}"}),
        )

    def _get_input() -> str:
        if HAS_PT:
            return _session.prompt("\n  ▸  ").strip()
        return console.input(f"\n  [bold {_AMBER}]▸[/bold {_AMBER}]  ").strip()

    while True:
        try:
            user = _get_input()
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.rule("[dim]Auf Wiedersehen[/dim]", style=_AMBER_DIM)
            _on_exit(console, history)
            console.print()
            return 0

        if not user:
            continue

        # ── Slash-Befehle ──────────────────────────────────────────────────────
        if user.startswith("/"):
            cmd = user.split()[0].lower()

            if cmd in ("/exit", "/quit"):
                console.rule("[dim]Auf Wiedersehen[/dim]", style=_AMBER_DIM)
                _on_exit(console, history)
                console.print()
                return 0

            elif cmd == "/clear":
                console.clear()
                _banner(console, profile, fc_model, current_personality)

            elif cmd == "/help":
                console.print()
                console.print(Panel(
                    Markdown(_HELP_MD),
                    title=f"[{_AMBER}]● Hilfe[/{_AMBER}]",
                    border_style=_AMBER_DIM,
                    box=box.ROUNDED,
                    padding=(1, 2),
                ))

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

            elif cmd == "/memory":
                console.print()
                entries = mem.recent(10)
                if entries:
                    for m in entries:
                        c = _AMBER if m.scope == "long" else "dim"
                        console.print(f"  [dim]·[/dim] [{c}]{m.scope}[/{c}]  {m.text[:140]}")
                else:
                    console.print("  [dim](keine Erinnerungen)[/dim]")

            elif cmd == "/private":
                private = not private
                if private:
                    console.print(f"  [green]🔒  Privat-Modus AN[/green]  [dim]— nur lokale Modelle[/dim]")
                else:
                    console.print(f"  [{_AMBER}]🌐  Privat-Modus AUS[/{_AMBER}]  [dim]— Cloud erlaubt[/dim]")

            elif cmd == "/update":
                console.print()
                _do_update(console)

            elif cmd == "/settings":
                console.print()
                _cmd_settings(console)

            elif cmd == "/personality":
                parts_cmd = user.split(maxsplit=2)
                sub = parts_cmd[1].lower() if len(parts_cmd) > 1 else ""

                if not sub or sub == "list":
                    _cmd_personality_list(console, current_personality)

                elif sub == "switch" and len(parts_cmd) > 2:
                    target = parts_cmd[2].strip()
                    p = get_personality(target)
                    if p:
                        current_personality = p
                        _banner(console, profile, fc_model, current_personality)
                        console.print(f"  [{_AMBER}]◆  Persönlichkeit: {p['display_name']}[/{_AMBER}]")
                    else:
                        console.print(f"  [yellow]Unbekannt:[/yellow] '{target}'  —  /personality list")

                elif sub == "default" and len(parts_cmd) > 2:
                    from ..memory.personalities import set_default as _set_def
                    name = parts_cmd[2].strip()
                    if _set_def(name):
                        console.print(f"  [green]✓[/green] Standard gesetzt: {name}")
                    else:
                        console.print(f"  [red]✗[/red] Nicht gefunden: {name}")

                elif sub == "create":
                    current_personality = _cmd_personality_create(console)

                elif sub == "delete" and len(parts_cmd) > 2:
                    from ..memory.personalities import delete as _del
                    name = parts_cmd[2].strip()
                    if _del(name):
                        console.print(f"  [green]✓[/green] Gelöscht: {name}")
                    else:
                        console.print(f"  [red]✗[/red] Nicht löschbar: {name}")

                else:
                    # Direkt nach Name suchen
                    p = get_personality(sub)
                    if p:
                        current_personality = p
                        _banner(console, profile, fc_model, current_personality)
                        console.print(f"  [{_AMBER}]◆  Persönlichkeit: {p['display_name']}[/{_AMBER}]")
                    else:
                        console.print(
                            f"  [dim]Nutzung:[/dim]\n"
                            f"    [bold]/personality list[/bold]         — alle anzeigen\n"
                            f"    [bold]/personality <name>[/bold]        — wechseln\n"
                            f"    [bold]/personality create[/bold]        — neue erstellen\n"
                            f"    [bold]/personality default <name>[/bold] — Standard setzen\n"
                            f"    [bold]/personality delete <name>[/bold]  — löschen"
                        )

            else:
                console.print(f"  [yellow]?[/yellow]  {cmd}  [dim]— /help für Übersicht[/dim]")

            continue

        # ── Alles durch einen Kanal ────────────────────────────────────────────
        _print_user(console, user)

        ctx = ToolContext(
            role=cfg.role,
            project_root=home,
            actor="tui",
            auto_approve=False,
            sandbox=False,
        )

        def confirm_cb(tool, args) -> bool:
            cmd_str = args.get("command") or args.get("path") or str(args)
            console.print()
            t = Text()
            t.append(f"  {cmd_str}", style="bold white", overflow="fold")
            console.print(Panel(
                t,
                title=f"[bold {_YELLOW}]⚡  {tool.name}[/bold {_YELLOW}]  [dim]Bestätigung nötig[/dim]",
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

        _STEP_ICONS = {
            "terminal":   "⚡",
            "fs_read":    "◎",
            "fs_write":   "✎",
            "web_search": "◌",
        }

        def on_step(name: str, args: dict) -> None:
            icon   = _STEP_ICONS.get(name, "◆")
            detail = args.get("command") or args.get("query") or args.get("path") or ""
            t = Text()
            t.append(f"  {icon} ", style=f"bold {_AMBER}")
            t.append(name, style=_AMBER_DIM)
            t.append("  ", style="")
            t.append(str(detail)[:90], style="dim")
            console.print(t)

        console.print()
        try:
            pdisp = current_personality.get("display_name", "Nexoryx") if current_personality else "Nexoryx"
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
                )
        except RuntimeError as exc:
            # FC nicht verfügbar → normaler Chat-Fallback
            answer, steps = _chat_fallback(router, user, history, mem, cfg, private), []
        except Exception as exc:
            console.print(f"\n  [red]● Fehler:[/red] {exc}\n")
            continue

        n = len(steps)
        _msg_counter[0] += 1
        step_txt = f" · {n} Schritt{'e' if n != 1 else ''}" if n else ""
        label = f"{fc_model or 'chat'}{step_txt} · #{_msg_counter[0]}"
        _print_bot(console, answer, label=label)
        history.extend([f"User: {user}", f"Nexoryx: {answer[:300]}"])
        mem.remember(f"Chat: {user} → {answer[:200]}", scope="long")

        # Persona aus diesem Turn lernen
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


# ── Visuelle Bausteine ────────────────────────────────────────────────────────

def _banner(console: "Console", profile, fc_model: str | None = None,
            personality: dict | None = None) -> None:
    """Banner mit Maskottchen links, Titeltext rechts."""
    console.print()
    console.rule(style=_AMBER_DIM)

    # Maskottchen als Rich-Text
    mascot_t = Text()
    for bright, line in _MASCOT:
        style = f"bold {_AMBER_HI}" if bright else _AMBER_DIM
        mascot_t.append(line + "\n", style=style)

    # Titelblock rechts
    pname = personality.get("display_name", "Nex") if personality else "Nex"
    tone  = personality.get("tone", "") if personality else ""

    info = Text()
    info.append("\n")
    # Großer Titel — leicht letter-spaced
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
    info.append("   /help", style=f"{_AMBER_DIM}")
    info.append("  /personality", style=f"{_AMBER_DIM}")
    info.append("  /exit\n", style=f"{_AMBER_DIM}")

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


def _print_user(console: "Console", text: str) -> None:
    """Nutzereingabe — Chat-Bubble rechts, passt sich der Textlänge an."""
    ts = _ts()
    lines = text.split("\n")
    max_len = max(len(l) for l in lines) if lines else len(text)
    bubble_w = min(max_len + 10, int(console.width * 0.72), console.width - 4)

    body = Text(text, overflow="fold", style="bold white")
    p = Panel(
        body,
        border_style=_SLATE,
        box=box.ROUNDED,
        padding=(0, 2),
        width=bubble_w,
    )
    footer = Text()
    footer.append(f"Du  ", style=f"bold {_SLATE_DIM}")
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

    console.print(Panel(
        rows,
        title=f"[bold {_AMBER}]◆  Persönlichkeiten[/bold {_AMBER}]",
        title_align="left",
        border_style=_AMBER_DIM,
        box=box.HEAVY_HEAD,
        padding=(0, 2),
    ))
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

        display = console.input(f"  [dim]Anzeige-Name (z. B. 'Freund'):[/dim] ").strip()
        if not display:
            display = name.capitalize()

        tone = console.input(f"  [dim]Ton/Charakter (z. B. 'humorvoll, locker'):[/dim] ").strip()
        if not tone:
            tone = "freundlich"

        language = console.input(f"  [dim]Sprache (Enter = Deutsch):[/dim] ").strip()
        if not language:
            language = "Deutsch"

        console.print(f"  [dim]System-Prompt (beschreibe wie {display} sich verhält):[/dim]")
        prompt_lines: list[str] = []
        console.print(f"  [dim](leere Zeile zum Beenden)[/dim]")
        while True:
            line = console.input("  ").strip()
            if not line:
                break
            prompt_lines.append(line)

        if not prompt_lines:
            system_prompt = (
                f"Du bist {display}, ein {tone} KI-Assistent. "
                f"Antworte immer auf {language}."
            )
        else:
            system_prompt = " ".join(prompt_lines)

        is_default_ans = console.input(
            f"  [dim]Als Standard setzen? [[/dim][bold]j[/bold][dim]/n]:[/dim] "
        ).strip().lower()
        is_default = is_default_ans in ("j", "ja", "y", "yes", "")

        p = create(name, display, tone, language, system_prompt, is_default)
        console.print(f"\n  [green]✓[/green] Persönlichkeit '{display}' erstellt.")
        console.print(f"  [dim]Aktivieren: /personality {name}[/dim]")
        return p

    except (EOFError, KeyboardInterrupt):
        console.print("\n  [dim]Abgebrochen.[/dim]")
        return get_default()


# ── On-Exit-Hook ─────────────────────────────────────────────────────────────

def _on_exit(console: "Console", history: list[str]) -> None:
    """Läuft nach dem Schließen der TUI: Persona lernen + Training + Upload."""
    if not history:
        return
    # Persona aus gesamter Sitzung extrahieren
    try:
        from ..memory.persona import learn_from_history
        learn_from_history(history)
    except Exception:
        pass
    # Training + Upload still im Hintergrund
    try:
        from ..training.on_exit import run_background
        run_background(console=None)
    except Exception:
        pass


# ── Update-Helfer ─────────────────────────────────────────────────────────────

def _do_update(console: "Console") -> None:
    import os
    import subprocess
    import time
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
            title=f"[red]✗ git pull fehlgeschlagen[/red]",
            border_style="red", box=box.ROUNDED, padding=(0, 2),
        ))
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
        console.print(f"  [red]pip fehlgeschlagen:[/red]\n{pip.stderr.strip()}")
        return
    console.print(f"  [bold {_GREEN}]✓[/bold {_GREEN}]  Update installiert — starte neu …\n")
    time.sleep(0.8)
    # Prozess in-place neustarten (kein manueller Restart nötig)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── Settings ──────────────────────────────────────────────────────────────────

_SETTINGS_KEYS = [
    ("anthropic",  "ANTHROPIC_API_KEY",   "Anthropic Claude"),
    ("openai",     "OPENAI_API_KEY",       "OpenAI GPT-4o"),
    ("gemini",     "GEMINI_API_KEY",       "Google Gemini"),
    ("telegram",   "TELEGRAM_BOT_TOKEN",  "Telegram Bot-Token"),
    ("github",     "GITHUB_PAT",           "GitHub PAT (Training-Upload)"),
]


def _cmd_settings(console: "Console") -> None:
    """Interaktive Einstellungen — API-Keys verwalten."""
    from ..platform import config as cfg_mod
    import getpass

    while True:
        # Status-Tabelle
        rows = Text()
        for i, (slug, env, label) in enumerate(_SETTINGS_KEYS, 1):
            val = cfg_mod.get_key(env) or ""
            if val:
                masked = val[:4] + "●●●●" + val[-2:] if len(val) > 6 else "●●●●"
                status = Text()
                status.append(f"  [{i}]  ", style=f"bold {_AMBER}")
                status.append(f"{label:<28}", style="white")
                status.append(masked, style=f"{_GREEN}")
            else:
                status = Text()
                status.append(f"  [{i}]  ", style="dim")
                status.append(f"{label:<28}", style="dim")
                status.append("nicht gesetzt", style="dim red")
            rows.append_text(status)
            rows.append("\n")

        console.print(Panel(
            rows,
            title=f"[bold {_AMBER}]◆  Einstellungen[/bold {_AMBER}]",
            title_align="left",
            subtitle=f"[dim {_AMBER_DIM}]Nummer = Key setzen  ·  d = löschen  ·  Enter = fertig[/dim {_AMBER_DIM}]",
            border_style=_AMBER_DIM,
            box=box.HEAVY_HEAD,
            padding=(0, 1),
        ))

        try:
            choice = console.input(f"  [{_AMBER}]▸[/{_AMBER}]  ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not choice or choice in ("q", "exit", "fertig"):
            break

        # Löschen: "d1" oder "d anthropic"
        if choice.startswith("d"):
            target = choice[1:].strip()
            for i, (slug, env, label) in enumerate(_SETTINGS_KEYS, 1):
                if target == str(i) or target == slug:
                    cfg_mod.set_secret(env, "")
                    console.print(f"  [dim]✗  {label} gelöscht.[/dim]")
            continue

        # Nummer eingegeben
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
            answer, steps = run_fc(user, ctx, confirm_cb=lambda t, a: True,
                                   model=fc_model)
            print(f"\n  Nexoryx: {answer.rstrip()}\n")
        except Exception as exc:
            print(f"  Fehler: {exc}")
    return 0
