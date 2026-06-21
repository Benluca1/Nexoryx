#!/usr/bin/env python3
"""Nexoryx Setup-Wizard — interaktiver Erststart.

Installiert automatisch alle Python-Abhängigkeiten und prüft Ollama,
bevor der interaktive Wizard startet.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

# src/ importierbar machen (Repo-Root → src/)
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

MIN_PY = (3, 11)

# ── ANSI-Farben (früh definiert, da vor dem nexoryx-Import genutzt) ───────────
_B   = "\033[1m"
_DIM = "\033[2m"
_G   = "\033[32m"
_Y   = "\033[33m"
_C   = "\033[36m"
_R   = "\033[31m"
_RST = "\033[0m"
_W = 54

def _rule(char: str = "─") -> None:
    print(f"  {_DIM}{char * _W}{_RST}")
def _ok(msg: str)   -> None: print(f"  {_G}✓{_RST} {msg}")
def _warn(msg: str) -> None: print(f"  {_Y}!{_RST} {msg}")
def _err(msg: str)  -> None: print(f"  {_R}✗{_RST} {msg}")


# ── Auto-Dependency-Install ────────────────────────────────────────────────────

def _pip_install(*packages: str, quiet: bool = True) -> bool:
    """Installiert Pakete in die aktuelle Python-Umgebung."""
    cmd = [sys.executable, "-m", "pip", "install"] + list(packages)
    if quiet:
        cmd.append("-q")
    try:
        subprocess.run(cmd, check=True, capture_output=quiet)
        return True
    except subprocess.CalledProcessError:
        return False


def _ensure_python_packages() -> None:
    """Installiert Nexoryx + alle Extras falls nicht vorhanden."""
    print(f"\n  {_B}Python-Pakete{_RST}")

    # pip aktualisieren
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "pip"],
        capture_output=True,
    )

    # Nexoryx selbst mit allen Extras installieren
    pkg_spec = f"{_REPO_ROOT}[runtime,cloud,telegram]"
    try:
        import nexoryx  # noqa: F401 — Prüfung ob bereits installiert
        _ok("Nexoryx-Paket bereits installiert")
    except ImportError:
        print("  Installiere Nexoryx + Abhängigkeiten …")
        if _pip_install("-e", pkg_spec):
            _ok("Nexoryx-Paket installiert")
        else:
            _warn("Paket-Installation teilweise fehlgeschlagen — läuft trotzdem via src/")

    # Einzelne optionale Extras sauber prüfen & nachinstallieren
    _extras = {
        "anthropic":          "anthropic>=0.40",
        "openai":             "openai>=1.40",
        "google.genai":       "google-genai>=0.3",
        "telegram":           "python-telegram-bot>=21",
        "fastapi":            "fastapi>=0.110",
        "pydantic":           "pydantic>=2.6",
        "typer":              "typer>=0.12",
        "rich":               "rich>=13",
        "httpx":              "httpx>=0.27",
        "pytest":             "pytest>=8",
    }
    missing = []
    for mod, spec in _extras.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(spec)

    if missing:
        print(f"  Installiere {len(missing)} fehlende Pakete …")
        if _pip_install(*missing):
            _ok(f"{len(missing)} Pakete installiert")
        else:
            _warn("Einige optionale Pakete konnten nicht installiert werden")
    else:
        _ok("Alle Python-Pakete vorhanden")


def _ensure_ollama() -> None:
    """Installiert Ollama falls nicht vorhanden."""
    print(f"\n  {_B}Ollama{_RST}")
    if shutil.which("ollama"):
        _ok("Ollama bereits installiert")
        return

    print("  Ollama nicht gefunden — wird installiert …")
    if sys.platform == "win32":
        _warn("Windows: Ollama bitte manuell installieren: winget install Ollama.Ollama")
        return

    try:
        result = subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            _ok("Ollama installiert")
        else:
            _warn(f"Ollama-Installation fehlgeschlagen: {result.stderr[:100]}")
    except subprocess.TimeoutExpired:
        _warn("Ollama-Installation: Timeout (zu langsam) — bitte manuell installieren")
    except OSError as exc:
        _warn(f"Ollama-Installation: {exc}")


def _ensure_clamav() -> None:
    """Installiert ClamAV (optional, für Hintergrund-Virenscanner)."""
    print(f"\n  {_B}ClamAV (Virus-Scanner){_RST}")
    if shutil.which("clamscan"):
        _ok("ClamAV bereits installiert")
        return

    # Paketmanager-Erkennung
    pm = None
    for cmd, name in [("apt-get","apt"), ("dnf","dnf"), ("pacman","pacman"), ("brew","brew")]:
        if shutil.which(cmd):
            pm = name
            break

    if pm is None:
        _warn("ClamAV: kein bekannter Paketmanager — manuell installieren (optional)")
        return

    print("  Installiere ClamAV (optional) …")
    cmd_map = {
        "apt":    ["sudo", "apt-get", "install", "-y", "-qq", "clamav"],
        "dnf":    ["sudo", "dnf", "install", "-y", "-q", "clamav"],
        "pacman": ["sudo", "pacman", "-S", "--noconfirm", "clamav"],
        "brew":   ["brew", "install", "clamav"],
    }
    try:
        r = subprocess.run(cmd_map[pm], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            # Signaturen aktualisieren
            subprocess.run(["sudo", "freshclam", "--quiet"],
                           capture_output=True, timeout=120, check=False)
            _ok("ClamAV installiert + Signaturen aktualisiert")
        else:
            _warn("ClamAV-Installation fehlgeschlagen (Nexoryx läuft trotzdem)")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        _warn("ClamAV konnte nicht installiert werden — manuell nachholbar")


# ── Abhängigkeiten sicherstellen (läuft vor allen Imports) ──────────────────

_ensure_python_packages()
_ensure_ollama()
_ensure_clamav()

# Jetzt können wir Nexoryx-Module sicher importieren
from nexoryx import __version__
from nexoryx.platform import detect, choose_profile, model_gates
from nexoryx.platform import config as cfg_mod

# ── Interaktive Widgets ────────────────────────────────────────────────────────

def _select(question: str, choices: list[str], default: int = 0) -> int:
    """Pfeiltasten-Einfachauswahl. Gibt den Index zurück."""
    if not sys.stdin.isatty():
        return default
    try:
        import tty, termios
    except ImportError:
        return _select_plain(question, choices, default)

    current = [default]
    n = len(choices)

    def _draw() -> str:
        lines = [f"\n  {_B}{question}{_RST}"]
        for i, c in enumerate(choices):
            if i == current[0]:
                lines.append(f"    {_G}❯{_RST} {_B}{c}{_RST}")
            else:
                lines.append(f"      {_DIM}{c}{_RST}")
        return "\n".join(lines) + "\n"

    out = _draw()
    sys.stdout.write(out)
    sys.stdout.flush()
    n_lines = out.count("\n")

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.buffer.read(1)
            if ch in (b"\r", b"\n"):
                break
            elif ch == b"\x03":
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif ch == b"\x1b":
                rest = sys.stdin.buffer.read(2)
                if rest == b"[A":
                    current[0] = (current[0] - 1) % n
                elif rest == b"[B":
                    current[0] = (current[0] + 1) % n
            sys.stdout.write(f"\033[{n_lines}A")
            out = _draw()
            sys.stdout.write(out)
            sys.stdout.flush()
            n_lines = out.count("\n")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    sys.stdout.write("\n")
    return current[0]


def _multiselect(question: str, choices: list[str], defaults: list[int] | None = None) -> list[int]:
    """Pfeiltasten + Leertaste für Mehrfachauswahl."""
    if not sys.stdin.isatty():
        return defaults or []
    try:
        import tty, termios
    except ImportError:
        return _multiselect_plain(question, choices, defaults or [])

    current = [0]
    selected: set[int] = set(defaults or [])
    n = len(choices)

    def _draw() -> str:
        lines = [
            f"\n  {_B}{question}{_RST}",
            f"  {_DIM}Leertaste = auswählen · Enter = bestätigen{_RST}",
        ]
        for i, c in enumerate(choices):
            check  = f"{_G}◉{_RST}" if i in selected else f"{_DIM}○{_RST}"
            cursor = f"{_G}❯{_RST}" if i == current[0] else " "
            lines.append(f"    {cursor} {check}  {c}")
        return "\n".join(lines) + "\n"

    out = _draw()
    sys.stdout.write(out)
    sys.stdout.flush()
    n_lines = out.count("\n")

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.buffer.read(1)
            if ch in (b"\r", b"\n"):
                break
            elif ch == b"\x03":
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif ch == b" ":
                if current[0] in selected:
                    selected.discard(current[0])
                else:
                    selected.add(current[0])
            elif ch == b"\x1b":
                rest = sys.stdin.buffer.read(2)
                if rest == b"[A":
                    current[0] = (current[0] - 1) % n
                elif rest == b"[B":
                    current[0] = (current[0] + 1) % n
            sys.stdout.write(f"\033[{n_lines}A")
            out = _draw()
            sys.stdout.write(out)
            sys.stdout.flush()
            n_lines = out.count("\n")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    sys.stdout.write("\n")
    return sorted(selected)


def _select_plain(question: str, choices: list[str], default: int) -> int:
    print(f"\n  {question}")
    for i, c in enumerate(choices):
        marker = "→" if i == default else " "
        print(f"  {marker} [{i + 1}] {c}")
    while True:
        try:
            raw = input(f"  Auswahl [1–{len(choices)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx
        except (ValueError, EOFError):
            return default


def _multiselect_plain(question: str, choices: list[str], defaults: list[int]) -> list[int]:
    print(f"\n  {question} (Nummern mit Komma, z.B. 1,3):")
    for i, c in enumerate(choices):
        d = "*" if i in defaults else " "
        print(f"  [{d}] [{i + 1}] {c}")
    raw = input("  Auswahl: ").strip()
    if not raw:
        return defaults
    result = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(choices):
                result.append(idx)
        except ValueError:
            pass
    return sorted(result) or defaults


# ── Banner ─────────────────────────────────────────────────────────────────────

def _banner() -> None:
    print()
    _rule("━")
    title = "N  E  X  O  R  Y  X"
    sub   = "Setup-Wizard"
    pad_t = (_W - len(title)) // 2
    pad_s = (_W - len(sub))   // 2
    print(f"  {' ' * pad_t}{_C}{_B}{title}{_RST}")
    print(f"  {' ' * pad_s}{_DIM}{sub}{_RST}")
    _rule("━")
    print()


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main() -> int:
    _banner()

    # 1) Python-Version
    if sys.version_info < MIN_PY:
        _warn(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ empfohlen (gefunden {sys.version.split()[0]})")
    else:
        _ok(f"Python {sys.version.split()[0]}")

    # 2) Hardware
    print(f"\n  {_B}Hardware-Analyse{_RST}")
    hw = detect()
    profile = choose_profile(hw)
    gates = model_gates(hw)
    _ok(f"{hw.cpu_model}  ·  {hw.cpu_cores_logical} Kerne  ·  {hw.ram_mb} MB RAM")
    gpu_label = hw.gpu.name or hw.gpu.vendor
    if hw.gpu.vram_mb:
        gpu_label += f" ({hw.gpu.vram_mb} MB VRAM)"
    _ok(f"GPU: {gpu_label}")
    allowed = [m for m, ok in gates.items() if ok]
    _ok(f"Profil: {_B}{profile.name}{_RST}  →  {_DIM}{profile.reason}{_RST}")
    _ok(f"Erlaubte Modelle: {', '.join(allowed)}")

    # 3) Cloud-Provider einrichten?
    providers = ["Anthropic Claude (empfohlen)", "OpenAI GPT", "Google Gemini", "Keinen — nur lokal"]
    chosen = _multiselect(
        "Cloud-Provider einrichten (Leertaste = auswählen):",
        providers,
        defaults=[0],
    )

    key_map = {0: "ANTHROPIC_API_KEY", 1: "OPENAI_API_KEY", 2: "GEMINI_API_KEY"}
    any_key = False
    for idx in chosen:
        if idx not in key_map:
            continue
        env = key_map[idx]
        pname = providers[idx].split(" (")[0]
        print(f"\n  {_B}{pname}{_RST} API-Key eingeben:")
        try:
            value = getpass.getpass(f"  {env}: ").strip()
        except (EOFError, KeyboardInterrupt):
            _warn(f"{pname} übersprungen.")
            continue
        if value:
            cfg_mod.set_secret(env, value)
            _ok(f"{pname} konfiguriert")
            any_key = True
        else:
            _warn(f"{pname} übersprungen (kein Wert eingegeben)")

    if not any_key and 3 not in chosen:
        _warn("Kein Cloud-Key gesetzt — nur lokale Modelle verfügbar.")

    # 4) Telegram
    tg_idx = _select(
        "Telegram-Bot einrichten?",
        ["Jetzt einrichten", "Später (nexoryx admin telegram)"],
        default=1,
    )
    if tg_idx == 0:
        print(f"\n  {_B}Telegram-Setup{_RST}")
        try:
            token = getpass.getpass("  TELEGRAM_BOT_TOKEN: ").strip()
            admin_id = input("  Deine Telegram-User-ID: ").strip()
        except (EOFError, KeyboardInterrupt):
            _warn("Telegram übersprungen.")
            token, admin_id = "", ""
        if token:
            cfg_mod.set_secret("TELEGRAM_BOT_TOKEN", token)
        cfg = cfg_mod.load()
        if admin_id:
            cfg.telegram_admin_id = admin_id
            cfg_mod.save(cfg)
        if token:
            _ok("Telegram konfiguriert — start mit: nex telegram")

    # 5) Config speichern
    from nexoryx.training.house import recommended_base
    base = recommended_base(profile, hw)
    cfg = cfg_mod.load()
    cfg.profile  = profile.name
    cfg.house_base = base["ollama"]
    cfg.version  = __version__
    cfg_mod.save(cfg)

    # 6) Abschluss
    print()
    _rule("━")
    title2 = "Fertig! 🎉"
    pad2 = (_W - len(title2)) // 2
    print(f"  {' ' * pad2}{_G}{_B}{title2}{_RST}")
    _rule("━")
    print(f"""
  {_B}Loslegen:{_RST}

    {_C}nex{_RST}            TUI starten (Fragen stellen, /commands)
    {_C}nex doctor{_RST}     Hardware + Profil prüfen
    {_C}nex models list{_RST}  Verfügbare Modelle anzeigen

  {_DIM}Lokales Modell:  nex models pull house{_RST}
""")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(f"\n\n  {_Y}Setup abgebrochen.{_RST}\n")
        raise SystemExit(1)
