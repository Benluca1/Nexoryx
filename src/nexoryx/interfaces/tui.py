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
    "/memory", "/private", "/update", "/exit", "/quit",
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

    if not HAS_RICH:
        return _run_plain(router, mem, cfg, profile)

    console = Console()
    _banner(console, profile, fc_model)

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
            console.print()
            return 0

        if not user:
            continue

        # ── Slash-Befehle ──────────────────────────────────────────────────────
        if user.startswith("/"):
            cmd = user.split()[0].lower()

            if cmd in ("/exit", "/quit"):
                console.rule("[dim]Auf Wiedersehen[/dim]", style=_AMBER_DIM)
                console.print()
                return 0

            elif cmd == "/clear":
                console.clear()
                _banner(console, profile, fc_model)

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
                f"  [{_AMBER_DIM}]◆  Nexoryx …[/{_AMBER_DIM}]",
                spinner="arc",
                spinner_style=_AMBER,
            ):
                answer, steps = run_fc(
                    user, ctx,
                    confirm_cb=confirm_cb,
                    on_step=on_step,
                    model=fc_model,
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

def _banner(console: "Console", profile, fc_model: str | None = None) -> None:
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
    sub.append("Profil: ", style="dim")
    sub.append(profile.name, style=f"bold {_AMBER}")
    sub.append("  ·  ", style="dim")
    if fc_model:
        sub.append(fc_model, style=f"{_AMBER_DIM}")
        sub.append("  ·  ", style="dim")
    sub.append("/help", style=f"italic {_AMBER_DIM}")
    sub.append(" für Befehle", style="dim")
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
