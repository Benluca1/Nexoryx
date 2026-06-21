"""Nexoryx TUI — interaktive Oberfläche (startet bei nacktem `nexoryx`/`nex`)."""
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

_SLASH = [
    "/help", "/clear", "/doctor", "/models", "/usage",
    "/memory", "/private", "/stream", "/update", "/exit", "/quit",
]

_HELP_MD = """\
**Befehle**

| Befehl | Wirkung |
|---|---|
| `/help` | Diese Hilfe |
| `/clear` | Bildschirm leeren |
| `/doctor` | Hardware + Profil prüfen |
| `/models` | Modelle anzeigen |
| `/usage` | Cloud-Verbrauch |
| `/memory` | Letzte Erinnerungen |
| `/private` | Privat-Modus umschalten (nur lokal) |
| `/stream` | Streaming umschalten |
| `/update` | Neueste Version installieren (git pull + pip) |
| `/exit` | Beenden |

Einfach eine Frage schreiben — Nexoryx antwortet direkt.
"""


def run() -> int:
    from ..platform import detect, choose_profile
    from ..platform import config as cfg_mod
    from ..brain import classify
    from ..router import ChatRequest, Router, ProviderError
    from ..memory import MemoryStore

    hw = detect()
    profile = choose_profile(hw)
    router = Router(hw, profile)
    mem = MemoryStore()
    cfg = cfg_mod.load()

    if not HAS_RICH:
        return _run_plain(router, mem, cfg, profile)

    console = Console()
    _banner(console, profile)

    history: list[str] = []
    streaming = True
    private = False

    if HAS_PT:
        _session: PromptSession = PromptSession(
            completer=WordCompleter(_SLASH, sentence=True),
            history=InMemoryHistory(),
            style=PTStyle.from_dict({"prompt": "#555555"}),
        )

    def _get_input() -> str:
        if HAS_PT:
            return _session.prompt("\n You › ").strip()
        return console.input("\n[dim] You ›[/dim] ").strip()

    while True:
        try:
            user = _get_input()
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print(Rule("[dim]Tschüss[/dim]"))
            return 0

        if not user:
            continue

        if user.startswith("/"):
            cmd = user.split()[0].lower()

            if cmd in ("/exit", "/quit"):
                console.print(Rule("[dim]Tschüss[/dim]"))
                return 0

            elif cmd == "/clear":
                console.clear()
                _banner(console, profile)

            elif cmd == "/help":
                console.print(Panel(
                    Markdown(_HELP_MD),
                    title="[bold]Hilfe[/bold]",
                    border_style="dim",
                    box=box.ROUNDED,
                    padding=(1, 2),
                ))

            elif cmd == "/doctor":
                import argparse
                from .. import cli as _cli
                _cli.cmd_doctor(argparse.Namespace())

            elif cmd == "/models":
                import argparse
                from .. import cli as _cli
                _cli.cmd_models(argparse.Namespace(models_action="list"))

            elif cmd == "/usage":
                import argparse
                from .. import cli as _cli
                _cli.cmd_usage(argparse.Namespace())

            elif cmd == "/memory":
                entries = mem.recent(10)
                if entries:
                    for m in entries:
                        console.print(f"  [dim]·[/dim] {m.text[:160]}")
                else:
                    console.print("  [dim](keine Erinnerungen)[/dim]")

            elif cmd == "/private":
                private = not private
                label = "[green]an[/green] — nur lokale Modelle" if private else "[yellow]aus[/yellow] — Cloud erlaubt"
                console.print(f"  Privat-Modus: {label}")

            elif cmd == "/stream":
                streaming = not streaming
                label = "[green]an[/green]" if streaming else "[yellow]aus[/yellow]"
                console.print(f"  Streaming: {label}")

            elif cmd == "/update":
                _do_update(console)

            else:
                console.print(f"  [yellow]Unbekannt:[/yellow] {cmd} — /help für Übersicht")

            continue

        # --- KI-Anfrage ---
        console.print()
        console.print(Panel(
            Text(user, overflow="fold"),
            title="[dim]Du[/dim]",
            border_style="steel_blue",
            box=box.ROUNDED,
            padding=(0, 1),
        ))
        console.print()

        brain = classify(user)
        if brain.trivial and brain.canned:
            console.print(Panel(
                Markdown(brain.canned),
                title="[bold green]Nexoryx[/bold green] [dim]✦[/dim]",
                border_style="green",
                box=box.ROUNDED,
                padding=(0, 1),
            ))
            history.extend([f"User: {user}", f"Nexoryx: {brain.canned[:300]}"])
            continue

        ctx_items = mem.recall(user, limit=3)
        ctx_text = "\n".join(f"- {m.text}" for m in ctx_items)
        convo = "\n".join(history[-6:])
        prompt = (f"Bisheriger Verlauf:\n{convo}\n\n" if convo else "") + \
                 (f"Erinnerungen:\n{ctx_text}\n\n" if ctx_text else "") + f"User: {user}"
        system = "Du bist Nexoryx, ein kompetenter, präziser Assistent." + \
                 (f" {cfg.persona}" if cfg.persona else "")

        req = ChatRequest(
            prompt=prompt,
            system=system,
            task_type=brain.task_type,
            sensitive=private,
            max_tokens=2048,
        )

        parts: list[str] = []
        try:
            if streaming:
                with Live(
                    Panel("[dim]…[/dim]",
                          title="[bold green]Nexoryx[/bold green] [dim]✦[/dim]",
                          border_style="green", box=box.ROUNDED, padding=(0, 1)),
                    console=console,
                    refresh_per_second=15,
                ) as live:
                    for chunk in router.stream(req):
                        parts.append(chunk)
                        live.update(Panel(
                            Markdown("".join(parts)),
                            title="[bold green]Nexoryx[/bold green] [dim]✦[/dim]",
                            border_style="green",
                            box=box.ROUNDED,
                            padding=(0, 1),
                        ))
            else:
                with console.status("[dim]Nexoryx denkt …[/dim]", spinner="dots"):
                    resp = router.route(req)
                parts = [resp.text]
                console.print(Panel(
                    Markdown(resp.text),
                    title=f"[bold green]Nexoryx[/bold green] [dim]✦ {resp.provider}/{resp.model}[/dim]",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(0, 1),
                ))
        except ProviderError as exc:
            console.print(f"  [red]Fehler:[/red] {exc}")
            continue
        except Exception as exc:
            console.print(f"  [red]Fehler:[/red] {exc}")
            continue

        answer = "".join(parts).strip()
        history.extend([f"User: {user}", f"Nexoryx: {answer[:300]}"])
        mem.remember(f"Chat: {user} → {answer[:200]}", scope="long")

    return 0


def _do_update(console: "Console") -> None:
    import subprocess
    from pathlib import Path

    # Repo-Root: zwei Ebenen über diesem File (src/nexoryx/interfaces/tui.py → Nexoryx/)
    repo = Path(__file__).resolve().parents[3]

    console.print(f"  [dim]Repo: {repo}[/dim]")

    with console.status("[dim]git pull …[/dim]", spinner="dots"):
        pull = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo, capture_output=True, text=True,
        )

    if pull.returncode != 0:
        console.print(f"  [red]git pull fehlgeschlagen:[/red]\n{pull.stderr.strip()}")
        return

    msg = pull.stdout.strip()
    if "Already up to date" in msg or "Bereits aktuell" in msg:
        console.print("  [dim]Bereits auf dem neuesten Stand.[/dim]")
        return

    console.print(f"  [green]✓[/green] {msg}")

    with console.status("[dim]pip install …[/dim]", spinner="dots"):
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=repo, capture_output=True, text=True,
        )

    if pip.returncode == 0:
        console.print("  [green]✓[/green] Update installiert — bitte [bold]nex[/bold] neu starten.")
    else:
        console.print(f"  [red]pip install fehlgeschlagen:[/red]\n{pip.stderr.strip()}")


def _banner(console: "Console", profile) -> None:
    console.print()
    console.print(Rule("[bold cyan]N E X O R Y X[/bold cyan]", style="cyan"))
    console.print(Align.center(
        f"[dim]Multi-Agenten-KI-Framework  ·  Profil: [bold]{profile.name}[/bold]  ·  [italic]/help[/italic] für Befehle[/dim]"
    ))
    console.print()


def _run_plain(router, mem, cfg, profile) -> int:
    from ..brain import classify
    from ..router import ChatRequest, ProviderError
    print(f"\n=== NEXORYX ({profile.name}) === /exit zum Beenden\n")
    history: list[str] = []
    while True:
        try:
            user = input(" You › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTschüss.")
            return 0
        if not user:
            continue
        if user.lower() in ("/exit", "/quit"):
            return 0
        if user.startswith("/"):
            print("  (Rich installieren für volle TUI-Unterstützung: pip install rich)")
            continue
        brain = classify(user)
        if brain.trivial and brain.canned:
            print(f"\n Nexoryx: {brain.canned}\n")
            continue
        req = ChatRequest(
            prompt=user, system=cfg.persona or "",
            task_type=brain.task_type, max_tokens=1024,
        )
        try:
            resp = router.route(req)
            print(f"\n Nexoryx: {resp.text.rstrip()}\n")
        except ProviderError as exc:
            print(f"  Fehler: {exc}")
    return 0
