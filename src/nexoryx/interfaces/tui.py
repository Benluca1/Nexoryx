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
    from rich.padding import Padding
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
_AMBER     = "#C8901A"   # Primärfarbe  — warm, unverwechselbar
_AMBER_DIM = "#7A5510"   # gedämpft     — Borders, Untertitel
_SLATE     = "#5F7FA8"   # Nutzer-Blau  — kühler Kontrast zum Amber

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


# ── Öffentlicher Einstieg ─────────────────────────────────────────────────────

def run() -> int:
    import os
    from ..platform import detect, choose_profile
    from ..platform import config as cfg_mod
    from ..brain import classify
    from ..router import ChatRequest, Router, ProviderError
    from ..memory import MemoryStore
    from ..orchestrator import Orchestrator
    from ..tools import ToolContext

    hw = detect()
    profile = choose_profile(hw)
    router = Router(hw, profile)
    mem = MemoryStore()
    cfg = cfg_mod.load()
    orch = Orchestrator(hw, profile, memory=mem)

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
                _banner(console, profile)

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

            elif cmd == "/stream":
                streaming = not streaming
                state = "[green]AN[/green]" if streaming else "[dim]AUS[/dim]"
                console.print(f"  Streaming: {state}")

            elif cmd == "/update":
                console.print()
                _do_update(console)

            else:
                console.print(f"  [yellow]Unbekannt:[/yellow] {cmd}  —  [dim]/help[/dim] für Übersicht")

            continue

        # ── KI-Anfrage ─────────────────────────────────────────────────────────
        _print_user(console, user)

        brain = classify(user)
        if brain.trivial and brain.canned:
            _print_bot(console, brain.canned, label="nexoryx")
            history.extend([f"User: {user}", f"Nexoryx: {brain.canned[:300]}"])
            continue

        # ── Agentic-Modus für PC-Aktionen ──────────────────────────────────────
        if brain.task_type == "action":
            _run_agentic(console, orch, user, history, mem, cfg, private)
            continue

        # ── Normaler Chat-Modus ─────────────────────────────────────────────────
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
            console.print()
            if streaming:
                with Live(
                    _bot_panel("", label="…", done=False),
                    console=console,
                    refresh_per_second=15,
                    vertical_overflow="visible",
                ) as live:
                    for chunk in router.stream(req):
                        parts.append(chunk)
                        live.update(_bot_panel("".join(parts), label="…", done=False))
                    live.update(_bot_panel("".join(parts), label="stream", done=True))
            else:
                with console.status(
                    f"  [{_AMBER_DIM}]◆  Nexoryx denkt …[/{_AMBER_DIM}]",
                    spinner="arc",
                    spinner_style=_AMBER,
                ):
                    resp = router.route(req)
                parts = [resp.text]
                label = f"{resp.provider}/{resp.model}"
                console.print(_bot_panel(resp.text, label=label, done=True))

        except ProviderError as exc:
            console.print(f"\n  [red]● Provider-Fehler:[/red] {exc}\n")
            continue
        except Exception as exc:
            console.print(f"\n  [red]● Fehler:[/red] {exc}\n")
            continue

        answer = "".join(parts).strip()
        history.extend([f"User: {user}", f"Nexoryx: {answer[:300]}"])
        mem.remember(f"Chat: {user} → {answer[:200]}", scope="long")

    return 0


# ── Agentic-Modus (PC-Kontrolle) ─────────────────────────────────────────────

def _run_agentic(console: "Console", orch, task: str, history: list,
                 mem, cfg, private: bool) -> None:
    import os
    from ..tools import ToolContext

    home = os.path.expanduser("~")
    ctx = ToolContext(
        role=cfg.role,
        project_root=home,
        actor="tui",
        auto_approve=False,
        sandbox=False,   # direkte Ausführung — Sicherheit kommt vom confirm-Gate
    )

    step_log: list[str] = []

    def confirm_cb(tool, reason: str) -> bool:
        """Zeigt ein Bestätigungs-Panel und wartet auf j/n."""
        cmd_info = reason
        console.print()
        console.print(Panel(
            Text(f"  {cmd_info}", style="white"),
            title=f"[yellow]⚡ Aktion erforderlich[/yellow]  [dim]{tool.name}[/dim]",
            border_style="yellow",
            box=box.HEAVY_HEAD,
            padding=(0, 1),
        ))
        try:
            ans = console.input(
                f"  [yellow]Ausführen?[/yellow]  [[bold]J[/bold]]a / [dim]N[/dim]ein:  "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        approved = ans in ("j", "ja", "y", "yes", "")
        if approved:
            console.print(f"  [green]✓[/green] [dim]Bestätigt[/dim]")
        else:
            console.print(f"  [dim]✗ Übersprungen[/dim]")
        return approved

    def on_step(name: str, args: dict) -> None:
        cmd = args.get("command") or args.get("query") or args.get("path") or str(args)
        step_log.append(f"{name}: {str(cmd)[:60]}")
        console.print(
            f"  [{_AMBER_DIM}]→[/{_AMBER_DIM}]  [dim]{name}[/dim]  {str(cmd)[:80]}"
        )

    console.print()
    with console.status(
        f"  [{_AMBER_DIM}]◆  Plant Schritte …[/{_AMBER_DIM}]",
        spinner="arc",
        spinner_style=_AMBER,
    ):
        pass  # zeigt kurz den Spinner bevor der Loop beginnt

    try:
        result = orch.agentic_run(
            task, ctx,
            confirm_cb=confirm_cb,
            on_step=on_step,
            max_steps=8,
        )
    except Exception as exc:
        console.print(f"\n  [red]● Fehler:[/red] {exc}\n")
        return

    label = f"agentic · {len(result.steps)} Schritt{'e' if len(result.steps) != 1 else ''}"
    _print_bot(console, result.answer, label=label)
    history.extend([f"User: {task}", f"Nexoryx: {result.answer[:300]}"])


# ── Visuelle Bausteine ────────────────────────────────────────────────────────

def _banner(console: "Console", profile) -> None:
    console.print()
    # obere Linie
    console.rule(style=_AMBER_DIM)

    # Marken-Zeile
    title = Text()
    title.append("  ◆  ", style=f"bold {_AMBER}")
    title.append("N", style=f"bold {_AMBER}")
    title.append("EX", style=f"{_AMBER}")
    title.append("O", style=f"bold {_AMBER}")
    title.append("RY", style=f"{_AMBER}")
    title.append("X", style=f"bold {_AMBER}")
    title.append("  ◆", style=f"bold {_AMBER}")
    console.print(Align.center(title))

    # Untertitel
    sub = Text()
    sub.append("Multi-Agenten-KI-Framework", style="bold white")
    sub.append("  ·  ", style="dim")
    sub.append("Profil: ", style="dim")
    sub.append(profile.name, style=f"bold {_AMBER}")
    sub.append("  ·  ", style="dim")
    sub.append("/help", style=f"italic {_AMBER_DIM}")
    sub.append(" für Befehle", style="dim")
    console.print(Align.center(sub))

    # untere Linie
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
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=border,
        box=box.HEAVY_HEAD,
        padding=(0, 1),
    )


def _print_bot(console: "Console", content: str, label: str) -> None:
    console.print()
    console.print(_bot_panel(content, label=label, done=True))


# ── Update-Helfer ─────────────────────────────────────────────────────────────

def _do_update(console: "Console") -> None:
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    console.print(f"  [dim]Repo: {repo}[/dim]")

    with console.status(f"  [{_AMBER_DIM}]git pull …[/{_AMBER_DIM}]", spinner="arc", spinner_style=_AMBER):
        pull = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo, capture_output=True, text=True,
        )

    if pull.returncode != 0:
        console.print(f"  [red]git pull fehlgeschlagen:[/red]\n{pull.stderr.strip()}")
        return

    msg = pull.stdout.strip()
    if "Already up to date" in msg or "Bereits aktuell" in msg:
        console.print(f"  [{_AMBER_DIM}]Bereits auf dem neuesten Stand.[/{_AMBER_DIM}]")
        return

    console.print(f"  [green]✓[/green] {msg}")

    with console.status(f"  [{_AMBER_DIM}]pip install …[/{_AMBER_DIM}]", spinner="arc", spinner_style=_AMBER):
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=repo, capture_output=True, text=True,
        )

    if pip.returncode == 0:
        console.print(f"  [green]✓[/green] Update installiert — bitte [bold {_AMBER}]nex[/bold {_AMBER}] neu starten.")
    else:
        console.print(f"  [red]pip install fehlgeschlagen:[/red]\n{pip.stderr.strip()}")


# ── Fallback ohne Rich ────────────────────────────────────────────────────────

def _run_plain(router, mem, cfg, profile) -> int:
    from ..brain import classify
    from ..router import ChatRequest, ProviderError
    print(f"\n=== NEXORYX ({profile.name}) === /exit zum Beenden\n")
    history: list[str] = []
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
        brain = classify(user)
        if brain.trivial and brain.canned:
            print(f"\n  Nexoryx: {brain.canned}\n")
            continue
        req = ChatRequest(
            prompt=user, system=cfg.persona or "",
            task_type=brain.task_type, max_tokens=1024,
        )
        try:
            resp = router.route(req)
            print(f"\n  Nexoryx: {resp.text.rstrip()}\n")
        except ProviderError as exc:
            print(f"  Fehler: {exc}")
    return 0
