#!/usr/bin/env python3
"""Nexoryx Setup-Wizard — interaktiver Erststart.

Standalone:   python bootstrap.py
Via Installer: python bootstrap.py --source=server --role=admin --admin-enable=TOKEN
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

MIN_PY = (3, 11)

# ── ANSI ──────────────────────────────────────────────────────────────────────
_B   = "\033[1m"
_DIM = "\033[2m"
_G   = "\033[32m"
_Y   = "\033[33m"
_C   = "\033[36m"
_R   = "\033[31m"
_RST = "\033[0m"
_W   = 54

def _rule(ch="─"): print(f"  {_DIM}{ch * _W}{_RST}")
def _ok(m):   print(f"  {_G}✓{_RST} {m}")
def _warn(m): print(f"  {_Y}!{_RST} {m}")
def _err(m):  print(f"  {_R}✗{_RST} {m}")


# ── Dependency-Auto-Install ────────────────────────────────────────────────────

def _can_import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _pip(*pkgs: str, quiet: bool = True) -> bool:
    cmd = [sys.executable, "-m", "pip", "install"] + list(pkgs)
    if quiet:
        cmd.append("-q")
    try:
        subprocess.run(cmd, check=True, capture_output=quiet)
        return True
    except subprocess.CalledProcessError:
        return False


def _ensure_python_packages() -> None:
    print(f"\n  {_B}Python-Pakete prüfen{_RST}")
    # pip aktualisieren
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "pip"],
        capture_output=True,
    )

    # Nexoryx-Paket selbst
    if not _can_import("nexoryx"):
        print("  Installiere Nexoryx + Abhängigkeiten …")
        spec = f"{_REPO_ROOT}[runtime,cloud,telegram]"
        if _pip("-e", spec):
            _ok("Nexoryx installiert")
        else:
            _warn("Installation fehlgeschlagen — läuft weiter via src/")
    else:
        _ok("Nexoryx-Paket vorhanden")

    # Alle optionalen Extras einzeln prüfen und ggf. nachinstallieren
    extras = {
        "anthropic":    "anthropic>=0.40",
        "openai":       "openai>=1.40",
        "google.genai": "google-genai>=0.3",
        "telegram":     "python-telegram-bot>=21",
        "fastapi":      "fastapi>=0.110",
        "uvicorn":      "uvicorn>=0.29",
        "pydantic":     "pydantic>=2.6",
        "typer":        "typer>=0.12",
        "rich":         "rich>=13",
        "httpx":        "httpx>=0.27",
        "pytest":       "pytest>=8",
    }
    missing = [spec for mod, spec in extras.items() if not _can_import(mod)]
    if missing:
        print(f"  Installiere {len(missing)} fehlende Pakete …")
        if _pip(*missing):
            _ok(f"{len(missing)} Pakete installiert")
        else:
            _warn("Einige optionale Pakete fehlgeschlagen")
    else:
        _ok("Alle Python-Pakete vorhanden")


def _ensure_ollama() -> None:
    print(f"\n  {_B}Ollama{_RST}")
    if shutil.which("ollama"):
        _ok("Ollama bereits installiert")
        return
    print("  Ollama nicht gefunden — wird installiert …")
    if sys.platform == "win32":
        _warn("Windows: bitte manuell ausführen:  winget install Ollama.Ollama")
        return
    try:
        r = subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True, capture_output=True, text=True, timeout=300,
        )
        if r.returncode == 0:
            _ok("Ollama installiert")
        else:
            _warn(f"Ollama-Installation fehlgeschlagen: {r.stderr[:100]}")
    except subprocess.TimeoutExpired:
        _warn("Timeout — Ollama bitte manuell installieren: https://ollama.com")
    except OSError as e:
        _warn(f"Ollama-Installation: {e}")


def _ensure_clamav() -> None:
    if sys.platform == "win32":
        return  # Windows Defender übernimmt
    print(f"\n  {_B}ClamAV (Virus-Scanner){_RST}")
    if shutil.which("clamscan"):
        _ok("ClamAV bereits installiert")
        return
    pm = next(
        (n for cmd, n in [("apt-get","apt"),("dnf","dnf"),("pacman","pacman"),("brew","brew")]
         if shutil.which(cmd)),
        None,
    )
    if pm is None:
        _warn("ClamAV: kein Paketmanager gefunden — manuell installieren (optional)")
        return
    print("  Installiere ClamAV …")
    cmds = {
        "apt":    ["sudo", "apt-get", "install", "-y", "-qq", "clamav"],
        "dnf":    ["sudo", "dnf", "install", "-y", "-q", "clamav"],
        "pacman": ["sudo", "pacman", "-S", "--noconfirm", "clamav"],
        "brew":   ["brew", "install", "clamav"],
    }
    try:
        r = subprocess.run(cmds[pm], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            subprocess.run(["sudo", "freshclam", "--quiet"],
                           capture_output=True, timeout=120, check=False)
            _ok("ClamAV installiert + Signaturen aktualisiert")
        else:
            _warn("ClamAV-Installation fehlgeschlagen (Nexoryx läuft trotzdem)")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        _warn("ClamAV konnte nicht installiert werden — manuell nachholbar")


# ── Früh: Wurde vom Installer aufgerufen? ─────────────────────────────────────
# install.sh / install.ps1 haben Pakete bereits installiert → kein Doppellauf.
_CALLED_FROM_INSTALLER = any("--source" in a for a in sys.argv[1:])

if not _CALLED_FROM_INSTALLER:
    _ensure_python_packages()
    _ensure_ollama()
    _ensure_clamav()

# Ab hier sind alle Nexoryx-Module garantiert importierbar
from nexoryx import __version__
from nexoryx.platform import detect, choose_profile, model_gates
from nexoryx.platform import config as cfg_mod


# ── Interaktive Widgets ────────────────────────────────────────────────────────

def _select(question: str, choices: list[str], default: int = 0) -> int:
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
        print(f"  {'→' if i == default else ' '} [{i+1}] {c}")
    while True:
        try:
            raw = input(f"  Auswahl [1–{len(choices)}, Enter={default+1}]: ").strip()
            if not raw:
                return default
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx
        except (ValueError, EOFError):
            return default


def _multiselect_plain(question: str, choices: list[str], defaults: list[int]) -> list[int]:
    print(f"\n  {question} (Nummern mit Komma, z.B. 1,3):")
    for i, c in enumerate(choices):
        print(f"  [{'*' if i in defaults else ' '}] [{i+1}] {c}")
    raw = input("  Auswahl (Enter = Standard): ").strip()
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
    sub   = f"Setup-Wizard  v{__version__}"
    print(f"  {' ' * ((_W - len(title)) // 2)}{_C}{_B}{title}{_RST}")
    print(f"  {' ' * ((_W - len(sub))   // 2)}{_DIM}{sub}{_RST}")
    _rule("━")
    print()


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main() -> int:
    import argparse as _ap
    parser = _ap.ArgumentParser(add_help=False)
    parser.add_argument("--role",          default="user")
    parser.add_argument("--admin-enable",  default="", dest="admin_enable")
    parser.add_argument("--source",        default="manual")
    args, _ = parser.parse_known_args()

    # Rolle per Admin-Token ableiten (Plan §16.3)
    role = cfg_mod.resolve_role(args.admin_enable, args.source)

    _banner()

    # 1) Python-Version
    if sys.version_info < MIN_PY:
        _warn(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ empfohlen (läuft mit {sys.version.split()[0]})")
    else:
        _ok(f"Python {sys.version.split()[0]}")

    # 2) Hardware
    print(f"\n  {_B}Hardware-Analyse{_RST}")
    hw = detect()
    profile = choose_profile(hw)
    gates   = model_gates(hw)
    _ok(f"{hw.cpu_model}  ·  {hw.cpu_cores_logical} Kerne  ·  {hw.ram_mb} MB RAM")
    gpu_label = hw.gpu.name or hw.gpu.vendor
    if hw.gpu.vram_mb:
        gpu_label += f" ({hw.gpu.vram_mb} MB VRAM)"
    _ok(f"GPU: {gpu_label}")
    _ok(f"Profil: {_B}{profile.name}{_RST}  →  {_DIM}{profile.reason}{_RST}")
    allowed = [m for m, ok in gates.items() if ok]
    _ok(f"Erlaubte Modelle: {', '.join(allowed) or '—'}")

    # 3) Ollama-Modell ziehen?
    print(f"\n  {_B}Ollama-Startmodell{_RST}")
    try:
        from nexoryx.training.house import recommended_base
        base = recommended_base(profile, hw)
        rec_tag = base["ollama"]
    except Exception:
        rec_tag = "qwen2.5:0.5b" if hw.ram_mb < 8000 else "qwen2.5:7b"

    if shutil.which("ollama"):
        # Wenn vom Installer aufgerufen: Modell wird schon im Hintergrund geladen → Standard "Nein"
        pull_default = 1 if args.source == "server" else 0
        pull_idx = _select(
            f"Empfohlenes Modell '{rec_tag}' jetzt laden?",
            [f"Ja, '{rec_tag}' laden (~{'5 GB' if '7b' in rec_tag else '400 MB'})",
             "Später manuell:  ollama pull <modell>"],
            default=pull_default,
        )
        if pull_idx == 0:
            print(f"  Lade {rec_tag} …")
            r = subprocess.run(["ollama", "pull", rec_tag], capture_output=False)
            if r.returncode == 0:
                _ok(f"{rec_tag} geladen")
            else:
                _warn(f"Pull fehlgeschlagen — manuell: ollama pull {rec_tag}")
    else:
        _warn("Ollama nicht gefunden — Modell-Download übersprungen")
        _warn("Ollama installieren: https://ollama.com  oder:  curl -fsSL https://ollama.com/install.sh | sh")
        rec_tag = ""

    # 4) Cloud-Provider
    providers = ["Anthropic Claude (empfohlen)", "OpenAI GPT-4o", "Google Gemini", "Keinen — nur lokal"]
    chosen = _multiselect(
        "Cloud-Provider einrichten (Leertaste = auswählen):",
        providers,
        defaults=[0],
    )
    key_map = {0: "ANTHROPIC_API_KEY", 1: "OPENAI_API_KEY", 2: "GEMINI_API_KEY"}
    any_key = False
    for idx in chosen:
        env = key_map.get(idx)
        if env is None:
            continue
        pname = providers[idx].split(" (")[0]
        print(f"\n  {_B}{pname}{_RST} — API-Key eingeben (Enter = überspringen):")
        try:
            value = getpass.getpass(f"  {env}: ").strip()
        except (EOFError, KeyboardInterrupt):
            _warn(f"{pname} übersprungen")
            continue
        if value:
            cfg_mod.set_secret(env, value)
            _ok(f"{pname} konfiguriert")
            any_key = True
        else:
            _warn(f"{pname} übersprungen")

    if not any_key and 3 not in chosen:
        _warn("Kein Cloud-Key gesetzt — Nexoryx läuft nur lokal über Ollama.")

    # 5) Telegram
    tg_idx = _select(
        "Telegram-Bot einrichten?",
        ["Jetzt einrichten", "Später  (nexoryx admin telegram)"],
        default=1,
    )
    if tg_idx == 0:
        print(f"\n  {_B}Telegram-Setup{_RST}")
        print(f"  {_DIM}Bot erstellen: @BotFather → /newbot  ·  User-ID: @userinfobot{_RST}")
        try:
            token    = getpass.getpass("  TELEGRAM_BOT_TOKEN: ").strip()
            admin_id = input("  Deine Telegram-User-ID (Zahl): ").strip()
        except (EOFError, KeyboardInterrupt):
            _warn("Telegram übersprungen")
            token, admin_id = "", ""
        if token:
            cfg_mod.set_secret("TELEGRAM_BOT_TOKEN", token)
            _ok("Telegram-Token gespeichert")
        cfg = cfg_mod.load()
        if admin_id:
            cfg.telegram_admin_id = admin_id
            cfg_mod.save(cfg)
            _ok(f"Telegram-Admin-ID: {admin_id}")
        if token:
            _ok("Telegram konfiguriert — starten mit:  nexoryx telegram")

    # 6) Config speichern
    cfg = cfg_mod.load()
    cfg.role           = role
    cfg.install_source = args.source
    cfg.profile        = profile.name
    cfg.version        = __version__
    if rec_tag:
        cfg.house_base = rec_tag
    cfg_mod.save(cfg)

    # 7) Abschluss
    print()
    _rule("━")
    msg = "Nexoryx ist bereit!"
    print(f"  {' ' * ((_W - len(msg)) // 2)}{_G}{_B}{msg}{_RST}")
    _rule("━")
    inst = "admin" if role == "admin" else "user"
    print(f"""
  {_B}Rolle:{_RST}  {_C}{role}{_RST}  ·  Profil: {_C}{profile.name}{_RST}  ·  Install: {inst}

  {_B}Loslegen:{_RST}
    {_C}nex{_RST}                  TUI starten (Fragen stellen)
    {_C}nexoryx doctor{_RST}       Hardware + Profil + Modelle prüfen
    {_C}nexoryx ask "Hallo"{_RST}  Erste Frage (Router wählt automatisch)
    {_C}nexoryx models list{_RST}  Verfügbare Modelle anzeigen

  {_DIM}Lokales Modell ziehen:  nexoryx models pull house{_RST}
  {_DIM}Cloud-Key setzen:       nexoryx admin keys set anthropic{_RST}
""")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(f"\n\n  {_Y}Setup abgebrochen.{_RST}\n")
        raise SystemExit(1)
