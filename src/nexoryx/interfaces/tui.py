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
_SLATE     = "#5F7FA8"
_GREEN     = "#4CAF50"
_YELLOW    = "#F5C242"

_SLASH = [
    "/help", "/clear", "/doctor", "/models", "/usage",
    "/memory", "/private", "/update", "/personality", "/exit", "/quit",
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
| `/clear` | Bildschirm leeren |
| `/doctor` | Hardware + Profil prüfen |
| `/models` | Modelle anzeigen |
| `/usage` | Cloud-Verbrauch |
| `/memory` | Letzte Erinnerungen |
| `/private` | Privat-Modus (nur lokale Modelle) |
| `/update` | Neueste Version installieren |
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
            console.print(Panel(
                Text(f"  {cmd_str}", style="white", overflow="fold"),
                title=f"[{_YELLOW}]⚡ {tool.name}[/{_YELLOW}]",
                border_style=_YELLOW,
                box=box.HEAVY_HEAD,
                padding=(0, 1),
            ))
            try:
                ans = console.input(
                    f"  [{_YELLOW}]Ausführen?[/{_YELLOW}]  [[bold]Enter[/bold]/j]a  [dim]n[/dim]ein:  "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            ok = ans not in ("n", "nein", "no")
            console.print(f"  [green]✓[/green]" if ok else f"  [dim]✗ übersprungen[/dim]")
            return ok

        def on_step(name: str, args: dict) -> None:
            detail = args.get("command") or args.get("query") or args.get("path") or ""
            console.print(
                f"  [{_AMBER_DIM}]→[/{_AMBER_DIM}]  [dim]{name}[/dim]  {str(detail)[:80]}"
            )

        console.print()
        try:
            with console.status(
                f"  [{_AMBER_DIM}]◆  {current_personality.get('display_name','Nexoryx')} …[/{_AMBER_DIM}]",
                spinner="arc",
                spinner_style=_AMBER,
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
        label = f"{fc_model or 'chat'}" + (f" · {n} Schritt{'e' if n != 1 else ''}" if n else "")
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
    console.print()
    console.rule(style=_AMBER_DIM)

    title = Text()
    title.append("  ◆  ", style=f"bold {_AMBER}")
    title.append("N", style=f"bold {_AMBER}")
    title.append("EX", style=_AMBER)
    title.append("O", style=f"bold {_AMBER}")
    title.append("RY", style=_AMBER)
    title.append("X", style=f"bold {_AMBER}")
    title.append("  ◆", style=f"bold {_AMBER}")
    console.print(Align.center(title))

    sub = Text()
    pname = personality.get("display_name", "Nex") if personality else "Nex"
    sub.append(pname, style=f"bold {_AMBER}")
    sub.append("  ·  ", style="dim")
    sub.append(profile.name, style=f"{_AMBER_DIM}")
    if fc_model:
        sub.append("  ·  ", style="dim")
        sub.append(fc_model, style=f"{_AMBER_DIM}")
    sub.append("  ·  ", style="dim")
    sub.append("/help", style=f"italic {_AMBER_DIM}")
    console.print(Align.center(sub))

    console.rule(style=_AMBER_DIM)
    console.print()


def _print_user(console: "Console", text: str) -> None:
    console.print()
    console.print(Panel(
        Text(text, overflow="fold", style="white"),
        title=f"[{_SLATE}]Du[/{_SLATE}]",
        title_align="left",
        border_style=_SLATE,
        box=box.SIMPLE_HEAD,
        padding=(0, 1),
    ))


def _bot_panel(content: str, label: str, done: bool) -> "Panel":
    border = _AMBER if done else _AMBER_DIM
    spinner = "" if done else " [dim]●[/dim]"
    title = f"[bold {_AMBER}]◆ Nexoryx[/bold {_AMBER}]{spinner}  [dim]{label}[/dim]"
    body = Markdown(content) if content.strip() else Text("…", style="dim")
    return Panel(body, title=title, title_align="left",
                 border_style=border, box=box.HEAVY_HEAD, padding=(0, 1))


def _print_bot(console: "Console", content: str, label: str) -> None:
    console.print()
    console.print(_bot_panel(content, label=label, done=True))


# ── Persönlichkeits-Befehle ───────────────────────────────────────────────────

def _cmd_personality_list(console: "Console", current: dict) -> None:
    from ..memory.personalities import list_personalities
    plist = list_personalities()
    console.print()
    console.print(Panel(
        "\n".join(
            f"  [{'bold ' + _AMBER if p['name'] == current['name'] else 'dim'}]"
            f"{'◆ ' if p['name'] == current['name'] else '  '}"
            f"{p['display_name']}[/{'bold ' + _AMBER if p['name'] == current['name'] else 'dim'}]"
            f"  [dim]{p['name']}[/dim]"
            + (f"  [dim]— {p.get('tone','')}[/dim]" if p.get("tone") else "")
            + (" [dim](Standard)[/dim]" if p.get("is_default") else "")
            for p in plist
        ),
        title=f"[{_AMBER}]● Persönlichkeiten[/{_AMBER}]",
        border_style=_AMBER_DIM,
        box=box.ROUNDED,
        padding=(0, 1),
    ))
    console.print(f"  [dim]Wechseln: /personality <name>  ·  Erstellen: /personality create[/dim]")


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
    # Training + Upload im Hintergrund
    try:
        from ..training.on_exit import run_background
        console.print(f"  [{_AMBER_DIM}]Speichere Sitzung & lade Trainingsdaten hoch …[/{_AMBER_DIM}]")
        run_background(console=console)
    except Exception:
        pass


# ── Update-Helfer ─────────────────────────────────────────────────────────────

def _do_update(console: "Console") -> None:
    import subprocess
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    console.print(f"  [dim]Repo: {repo}[/dim]")
    with console.status(f"  [{_AMBER_DIM}]git pull …[/{_AMBER_DIM}]",
                        spinner="arc", spinner_style=_AMBER):
        pull = subprocess.run(["git", "pull", "--ff-only"],
                              cwd=repo, capture_output=True, text=True)
    if pull.returncode != 0:
        console.print(f"  [red]git pull fehlgeschlagen:[/red]\n{pull.stderr.strip()}")
        return
    msg = pull.stdout.strip()
    if "Already up to date" in msg or "Bereits aktuell" in msg:
        console.print(f"  [{_AMBER_DIM}]Bereits aktuell.[/{_AMBER_DIM}]")
        return
    console.print(f"  [green]✓[/green] {msg}")
    with console.status(f"  [{_AMBER_DIM}]pip install …[/{_AMBER_DIM}]",
                        spinner="arc", spinner_style=_AMBER):
        pip = subprocess.run([sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
                             cwd=repo, capture_output=True, text=True)
    if pip.returncode == 0:
        console.print(f"  [green]✓[/green] Update fertig — [bold {_AMBER}]nex[/bold {_AMBER}] neu starten.")
    else:
        console.print(f"  [red]pip fehlgeschlagen:[/red]\n{pip.stderr.strip()}")


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
