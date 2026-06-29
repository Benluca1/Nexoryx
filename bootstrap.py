#!/usr/bin/env python3
"""Nexoryx Setup-Wizard — interaktiver Erststart.

Standalone:   python bootstrap.py
Via Installer: python bootstrap.py --source=server --role=admin --admin-enable=TOKEN
"""

from __future__ import annotations

import getpass
import os
import random
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
_W   = 60


def _hr():
    print(f"  {_DIM}{'─' * _W}{_RST}")

def _bhr():
    print(f"  {_C}{_B}{'━' * _W}{_RST}")

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
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", "pip"],
        capture_output=True,
    )
    if not _can_import("nexoryx"):
        print("  Installiere Nexoryx + Abhängigkeiten …")
        spec = f"{_REPO_ROOT}[runtime,cloud,telegram]"
        if _pip("-e", spec):
            _ok("Nexoryx installiert")
        else:
            _warn("Installation fehlgeschlagen — läuft weiter via src/")
    else:
        _ok("Nexoryx-Paket vorhanden")

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
        return
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
_CALLED_FROM_INSTALLER = any("--source" in a for a in sys.argv[1:])

if not _CALLED_FROM_INSTALLER:
    _ensure_python_packages()
    _ensure_ollama()
    _ensure_clamav()

# Ab hier sind alle Nexoryx-Module garantiert importierbar
from nexoryx import __version__
from nexoryx.platform import detect, choose_profile, model_gates
from nexoryx.platform import config as cfg_mod


# ── Terminal-Raw-Mode ─────────────────────────────────────────────────────────

_TTY = sys.stdin.isatty()
try:
    import tty as _tty
    import termios as _termios
    _RAW = True
except ImportError:
    _RAW = False


def _getch() -> bytes:
    return sys.stdin.buffer.read(1)


# ── Multiselect ───────────────────────────────────────────────────────────────

def _multiselect(
    question: str,
    labels: list[str],
    descs: list[str] | None = None,
    defaults: list[int] | None = None,
) -> list[int]:
    """
    Pfeiltasten navigieren · Leertaste auswählen · Enter bestätigen
    Cursor auf 'Skip for now' + Enter → leere Liste zurück.

    Gibt zurück: sortierte Liste ausgewählter Indizes ([] = übersprungen/nichts).
    """
    _descs  = list(descs) if descs else [""] * len(labels)
    n       = len(labels)
    SKIP    = n          # virtueller Skip-Index
    total   = n + 1
    LABEL_W = max((len(c) for c in labels), default=10) + 2

    if not _TTY or not _RAW:
        return _multiselect_plain(question, labels, _descs, defaults or [])

    current: list[int] = [0]
    selected: set[int] = set(defaults or [])

    def _draw() -> str:
        lines: list[str] = [
            "",
            f"  {_B}{question}{_RST}",
            f"  {_DIM}↑↓ navigate  ·  space = select  ·  enter = confirm{_RST}",
            "",
        ]
        for i, lbl in enumerate(labels):
            cur  = f"{_C}❯{_RST}" if i == current[0] else " "
            chk  = (f"{_G}◉{_RST}" if i in selected
                    else (f"{_C}○{_RST}" if i == current[0] else f"{_DIM}○{_RST}"))
            txt  = f"{_B}{lbl:<{LABEL_W}}{_RST}" if i == current[0] else f"{lbl:<{LABEL_W}}"
            desc = f"  {_DIM}{_descs[i]}{_RST}" if _descs[i] else ""
            lines.append(f"    {cur} {chk}  {txt}{desc}")
        # Trennlinie + Skip-Option
        lines.append(f"  {_DIM}  {'─' * (_W - 2)}{_RST}")
        cur_s    = f"{_C}❯{_RST}" if current[0] == SKIP else " "
        skip_txt = (f"{_Y}{_B}↩  Skip for now{_RST}"
                    if current[0] == SKIP
                    else f"{_DIM}↩  Skip for now{_RST}")
        lines.append(f"    {cur_s}  {skip_txt}")
        lines.append("")
        return "\n".join(lines)

    out     = _draw()
    n_lines = out.count("\n")
    sys.stdout.write(out)
    sys.stdout.flush()

    fd  = sys.stdin.fileno()
    old = _termios.tcgetattr(fd)
    try:
        _tty.setraw(fd)
        while True:
            ch = _getch()
            if ch in (b"\r", b"\n"):
                if current[0] == SKIP:
                    selected.clear()
                break
            elif ch == b"\x03":
                _termios.tcsetattr(fd, _termios.TCSADRAIN, old)
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif ch == b" ":
                if current[0] < n:
                    if current[0] in selected:
                        selected.discard(current[0])
                    else:
                        selected.add(current[0])
            elif ch == b"\x1b":
                b1 = _getch()
                if b1 == b"[":
                    b2 = _getch()
                    if b2 == b"A":
                        current[0] = (current[0] - 1) % total
                    elif b2 == b"B":
                        current[0] = (current[0] + 1) % total
            sys.stdout.write(f"\033[{n_lines}A")
            out     = _draw()
            n_lines = out.count("\n")
            sys.stdout.write(out)
            sys.stdout.flush()
    finally:
        _termios.tcsetattr(fd, _termios.TCSADRAIN, old)

    sys.stdout.write("\n")
    return sorted(selected)


def _multiselect_skippable(
    question: str,
    labels: list[str],
    descs: list[str] | None = None,
    defaults: list[int] | None = None,
) -> list[int] | None:
    """Gibt None zurück wenn der Benutzer 'Skip for now' wählt."""
    result = _multiselect(question, labels, descs, defaults)
    return result if result else None


# ── Single-Select ─────────────────────────────────────────────────────────────

def _select(
    question: str,
    choices: list[str],
    descs: list[str] | None = None,
    default: int = 0,
) -> int:
    """
    Pfeiltasten navigieren · Enter auswählen
    Letzte Option ist immer 'Skip for now' → gibt -1 zurück.
    """
    _descs  = list(descs) if descs else [""] * len(choices)
    SKIP    = len(choices)
    total   = SKIP + 1
    LABEL_W = max((len(c) for c in choices), default=10) + 2

    if not _TTY or not _RAW:
        return _select_plain(question, choices, default)

    current: list[int] = [default]

    def _draw() -> str:
        lines: list[str] = [
            "",
            f"  {_B}{question}{_RST}",
            f"  {_DIM}↑↓ navigieren  ·  Enter = auswählen{_RST}",
            "",
        ]
        for i, c in enumerate(choices):
            cur  = f"{_C}❯{_RST}" if i == current[0] else " "
            txt  = f"{_B}{c:<{LABEL_W}}{_RST}" if i == current[0] else f"{_DIM}{c:<{LABEL_W}}{_RST}"
            desc = f"  {_DIM}{_descs[i]}{_RST}" if _descs[i] else ""
            lines.append(f"    {cur}  {txt}{desc}")
        lines.append(f"  {_DIM}  {'─' * (_W - 2)}{_RST}")
        cur_s    = f"{_C}❯{_RST}" if current[0] == SKIP else " "
        skip_txt = (f"{_Y}{_B}↩  Skip for now{_RST}"
                    if current[0] == SKIP
                    else f"{_DIM}↩  Skip for now{_RST}")
        lines.append(f"    {cur_s}  {skip_txt}")
        lines.append("")
        return "\n".join(lines)

    out     = _draw()
    n_lines = out.count("\n")
    sys.stdout.write(out)
    sys.stdout.flush()

    fd  = sys.stdin.fileno()
    old = _termios.tcgetattr(fd)
    try:
        _tty.setraw(fd)
        while True:
            ch = _getch()
            if ch in (b"\r", b"\n"):
                break
            elif ch == b"\x03":
                _termios.tcsetattr(fd, _termios.TCSADRAIN, old)
                sys.stdout.write("\n")
                raise KeyboardInterrupt
            elif ch == b"\x1b":
                b1 = _getch()
                if b1 == b"[":
                    b2 = _getch()
                    if b2 == b"A":
                        current[0] = (current[0] - 1) % total
                    elif b2 == b"B":
                        current[0] = (current[0] + 1) % total
            sys.stdout.write(f"\033[{n_lines}A")
            out     = _draw()
            n_lines = out.count("\n")
            sys.stdout.write(out)
            sys.stdout.flush()
    finally:
        _termios.tcsetattr(fd, _termios.TCSADRAIN, old)

    sys.stdout.write("\n")
    return -1 if current[0] == SKIP else current[0]


# ── Plaintext-Fallbacks ───────────────────────────────────────────────────────

def _select_plain(question: str, choices: list[str], default: int) -> int:
    print(f"\n  {question}")
    for i, c in enumerate(choices):
        print(f"  {'→' if i == default else ' '} [{i+1}] {c}")
    print(f"  [s] Skip for now")
    while True:
        try:
            raw = input(f"  Auswahl [1–{len(choices)}/s, Enter={default+1}]: ").strip()
            if not raw:
                return default
            if raw.lower() == "s":
                return -1
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx
        except (ValueError, EOFError):
            return default


def _multiselect_plain(
    question: str, labels: list[str], descs: list[str], defaults: list[int]
) -> list[int]:
    print(f"\n  {question}")
    print(f"  (Nummern mit Komma, z.B. 1,3  ·  s = überspringen)")
    for i, lbl in enumerate(labels):
        mark = "◉" if i in defaults else "○"
        desc = f"  — {descs[i]}" if descs[i] else ""
        print(f"  [{mark}] [{i+1}] {lbl}{desc}")
    raw = input("  Auswahl (Enter = Standard, s = überspringen): ").strip()
    if not raw:
        return defaults
    if raw.lower() == "s":
        return []
    result = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(labels):
                result.append(idx)
        except ValueError:
            pass
    return sorted(result) if result else defaults


# ── Banner + Step-Header ──────────────────────────────────────────────────────

def _banner() -> None:
    print()
    _bhr()
    title = "N  E  X  O  R  Y  X"
    sub   = f"installer  v{__version__}"
    motto = random.choice(_MOTTOS)
    pad_t = " " * ((_W - len(title)) // 2)
    pad_s = " " * ((_W - len(sub))   // 2)
    pad_m = " " * ((_W - len(motto)) // 2)
    print(f"  {pad_t}{_C}{_B}{title}{_RST}")
    print(f"  {pad_s}{_DIM}{sub}{_RST}")
    _bhr()
    print(f"  {pad_m}{_DIM}{motto}{_RST}")
    print()


_TOTAL_STEPS = 3

_MOTTOS = [
    "trained in the dark. ready in the light.",
    "no cloud required. no trace left behind.",
    "local. private. learning.",
    "open weights. your data. your model.",
    "why pay for intelligence you can grow?",
]


def _step_header(step: int, title: str, subtitle: str = "") -> None:
    filled    = round(step / _TOTAL_STEPS * 18)
    bar       = f"{_G}{'█' * filled}{_RST}{_DIM}{'░' * (18 - filled)}{_RST}"
    step_info = f"{_DIM}STEP {step} of {_TOTAL_STEPS}{_RST}"
    print()
    _bhr()
    print(f"  {step_info}  {bar}  {_C}{_B}{title}{_RST}")
    if subtitle:
        print(f"  {_DIM}{subtitle}{_RST}")
    _bhr()


# ── Systemd-Service ───────────────────────────────────────────────────────────

def _install_systemd_service() -> None:
    if sys.platform != "linux":
        return
    if not shutil.which("systemctl"):
        return

    nexoryxd = shutil.which("nexoryxd") or str(Path(sys.executable).parent / "nexoryxd")
    if not Path(nexoryxd).exists():
        _warn(f"nexoryxd nicht gefunden ({nexoryxd}) — Service-Install übersprungen")
        return

    service_src = _REPO_ROOT / "web" / "nexoryx-daemon.service"
    if not service_src.exists():
        _warn("web/nexoryx-daemon.service nicht gefunden — übersprungen")
        return

    sd_dir  = Path.home() / ".config" / "systemd" / "user"
    sd_dir.mkdir(parents=True, exist_ok=True)
    sd_file = sd_dir / "nexoryx-daemon.service"
    content = service_src.read_text(encoding="utf-8").replace("__NEXORYXD_BIN__", nexoryxd)
    sd_file.write_text(content, encoding="utf-8")

    print(f"\n  {_B}Systemd-Service{_RST}")
    for cmd in [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "nexoryx-daemon"],
        ["systemctl", "--user", "restart", "nexoryx-daemon"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0 and "restart" in cmd:
                subprocess.run(
                    ["systemctl", "--user", "start", "nexoryx-daemon"],
                    capture_output=True, timeout=10,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    _ok("nexoryx-daemon.service aktiviert (startet beim Booten)")
    _ok("Log: ~/.nexoryx/daemon.log  ·  Status: systemctl --user status nexoryx-daemon")


def _install_gui_deps() -> None:
    print(f"\n  {_B}Desktop-GUI (pywebview){_RST}")

    if sys.platform == "linux":
        webkit_ok = False
        try:
            import gi  # type: ignore
            gi.require_version("WebKit2", "4.1")
            from gi.repository import WebKit2  # noqa: F401
            webkit_ok = True
            _ok("WebKit2GTK 4.1 vorhanden")
        except Exception:
            pass

        if not webkit_ok:
            try:
                gi.require_version("WebKit2", "4.0")
                from gi.repository import WebKit2  # noqa: F401
                webkit_ok = True
                _ok("WebKit2GTK 4.0 vorhanden")
            except Exception:
                pass

        if not webkit_ok:
            _warn("WebKit2GTK nicht gefunden — versuche apt-Installation …")
            for pkg in ["python3-gi-cairo", "gir1.2-webkit2-4.1", "gir1.2-webkit2-4.0"]:
                try:
                    subprocess.run(
                        ["sudo", "apt-get", "install", "-y", "-qq", pkg],
                        capture_output=True, timeout=90, check=False,
                    )
                except Exception:
                    pass
            _ok("WebKit2GTK-Installation versucht (ggf. manuell: sudo apt install gir1.2-webkit2-4.1)")

    pkgs_needed = []
    if not _can_import("webview"):
        pkgs_needed.append("pywebview>=5.0")
    if not _can_import("PyQt6"):
        pkgs_needed.append("PyQt6>=6.4")
    if not _can_import("qtpy"):
        pkgs_needed.append("qtpy>=2.4")
    if pkgs_needed:
        if _pip(*pkgs_needed):
            _ok("pywebview + Qt installiert")
        else:
            _warn("GUI-Pakete konnten nicht installiert werden — manuell: pip install pywebview PyQt6 qtpy")
    else:
        _ok("pywebview + Qt vorhanden")


def _create_desktop_entry(with_desktop_link: bool = True) -> None:
    if sys.platform != "linux":
        return

    venv_bin = Path(sys.executable).parent
    # nex-gui hat Vorrang vor nexoryx-gui
    gui_bin = venv_bin / "nex-gui"
    if not gui_bin.exists():
        gui_bin = venv_bin / "nexoryx-gui"
    if not gui_bin.exists():
        _warn("nex-gui nicht gefunden — Desktop-Icon nach 'pip install -e .[gui]' verfügbar")
        return

    icon_src  = _REPO_ROOT / "src" / "nexoryx" / "interfaces" / "gui" / "static" / "icon.png"
    icon_dir  = Path.home() / ".local" / "share" / "icons" / "nexoryx"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_dest = icon_dir / "nex.png"
    if icon_src.exists():
        shutil.copy2(icon_src, icon_dest)

    desktop_content = (
        "[Desktop Entry]\n"
        "Name=nex\n"
        "Comment=KI-Harness — lernt aus jeder Interaktion\n"
        f"Exec={gui_bin}\n"
        f"Icon={icon_dest}\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=Utility;\n"
        "StartupWMClass=nexoryx\n"
    )

    apps_dir     = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = apps_dir / "nex.desktop"
    desktop_file.write_text(desktop_content, encoding="utf-8")
    desktop_file.chmod(0o644)
    _ok(f"App-Eintrag: {desktop_file}  (Anwendungsmenü → nex)")

    if with_desktop_link:
        desktop_dir = Path.home() / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        link = desktop_dir / "nex.desktop"
        shutil.copy2(desktop_file, link)
        link.chmod(0o755)
        try:
            subprocess.run(
                ["gio", "set", str(link), "metadata::trusted", "true"],
                capture_output=True, timeout=5, check=False,
            )
        except Exception:
            pass
        _ok(f"Desktop-Verknüpfung: {link}  (Doppelklick = nex-GUI öffnen)")


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main() -> int:
    import argparse as _ap
    parser = _ap.ArgumentParser(add_help=False)
    parser.add_argument("--role",                default="user")
    parser.add_argument("--admin-enable",        default="", dest="admin_enable")
    parser.add_argument("--server-relay-token",  default="", dest="server_relay_token")
    parser.add_argument("--source",              default="manual")
    args, _ = parser.parse_known_args()

    role = cfg_mod.resolve_role(args.admin_enable, args.source)

    if args.server_relay_token:
        _secrets    = Path.home() / ".nexoryx" / "secrets"
        _secrets.mkdir(parents=True, exist_ok=True)
        _relay_file = _secrets / "server-secret"
        _relay_file.write_text(args.server_relay_token, encoding="utf-8")
        _relay_file.chmod(0o600)

    _banner()

    # ── System (automatic, no interaction) ────────────────────────────────────
    if sys.version_info < MIN_PY:
        _warn(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ recommended (running {sys.version.split()[0]})")
    else:
        _ok(f"Python {sys.version.split()[0]}")

    print(f"\n  {_B}Hardware{_RST}")
    hw      = detect()
    profile = choose_profile(hw)
    gates   = model_gates(hw)
    _ok(f"{hw.cpu_model}  ·  {hw.cpu_cores_logical} cores  ·  {hw.ram_mb} MB RAM")
    gpu_label = hw.gpu.name or hw.gpu.vendor
    if hw.gpu.vram_mb:
        gpu_label += f" ({hw.gpu.vram_mb} MB VRAM)"
    _ok(f"GPU: {gpu_label}")
    _ok(f"Profile: {_B}{profile.name}{_RST}  →  {_DIM}{profile.reason}{_RST}")
    allowed_models = [m for m, ok_flag in gates.items() if ok_flag]
    _ok(f"Models available: {', '.join(allowed_models) or '—'}")

    print(f"\n  {_B}House model{_RST}")
    try:
        from nexoryx.training.house import recommended_base
        base    = recommended_base(profile, hw)
        rec_tag = base["ollama"]
        hf_base = base["hf"]
    except Exception:
        rec_tag = "qwen2.5:0.5b" if hw.ram_mb < 8000 else "qwen2.5:7b"
        hf_base = "Qwen/Qwen2.5-0.5B-Instruct" if hw.ram_mb < 8000 else "Qwen/Qwen2.5-7B-Instruct"

    if shutil.which("ollama"):
        size_hint = "~5 GB" if "14b" in rec_tag else "~2 GB" if "3b" in rec_tag else "~400 MB"
        print(f"  Pulling {_C}{rec_tag}{_RST}  ({size_hint}) …")
        r = subprocess.run(["ollama", "pull", rec_tag], capture_output=False)
        if r.returncode == 0:
            _ok(f"House model '{rec_tag}' ready")
        else:
            _warn(f"Pull failed — run manually: ollama pull {rec_tag}")
            rec_tag = ""
    else:
        _warn("Ollama not found — house model download skipped")
        _warn("Install Ollama:  curl -fsSL https://ollama.com/install.sh | sh")
        rec_tag = ""

    if rec_tag:
        try:
            from nexoryx.training import train as train_mod, dataset as ds_mod
            st = ds_mod.stats()
            from nexoryx.training.train import MIN_EXAMPLES
            if st["total"] >= MIN_EXAMPLES:
                print(f"  {st['total']} examples — starting training …")
                out_dir = Path.home() / ".nexoryx" / "training"
                result  = train_mod.train(repo_root=out_dir)
                if result.get("action") == "trained":
                    _ok(f"House model trained (version {result.get('house_version', 1)})")
                elif result.get("action") == "script_generated":
                    _ok(f"Training script: {result['script']}")
                    _warn(f"Missing deps: pip install {' '.join(result['deps_missing'])} trl accelerate")
                    _warn(f"Then: python {result['script']}")
                else:
                    _warn(f"Training: {result.get('reason', result.get('error', 'unknown'))}")
            else:
                _ok(f"Training starts automatically after {MIN_EXAMPLES} examples  ({st['total']} collected)")
                _ok(f"Base: {hf_base}  ·  LoRA fine-tune  ·  stored locally")
        except Exception as exc:
            _warn(f"Training setup: {exc}")

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 1 of 3 — AI Providers
    # ══════════════════════════════════════════════════════════════════════════

    _step_header(1, "AI Providers", "Which cloud APIs do you want to use?")

    prov_labels = [
        "Anthropic Claude",
        "OpenAI GPT-4o",
        "Google Gemini",
        "Local only  (Ollama)",
    ]
    prov_descs = [
        "claude-opus-4, claude-sonnet-4 …  (recommended)",
        "gpt-4o, gpt-4-turbo, o3-mini …",
        "gemini-2.0-pro, gemini-1.5-flash …",
        "no cloud key required",
    ]
    key_map = {0: "ANTHROPIC_API_KEY", 1: "OPENAI_API_KEY", 2: "GEMINI_API_KEY"}

    chosen_providers = _multiselect_skippable(
        "Enable cloud providers:",
        prov_labels,
        descs=prov_descs,
        defaults=[0],
    )

    any_key = False
    if chosen_providers is not None:
        for idx in chosen_providers:
            env = key_map.get(idx)
            if env is None:
                continue
            pname    = prov_labels[idx].split("  (")[0].strip()
            existing = ""
            try:
                existing = cfg_mod.get_secret(env) or ""
            except Exception:
                pass
            if existing:
                _ok(f"{pname} — key already saved  {_DIM}(enter = keep){_RST}")
            else:
                print(f"\n  {_B}{pname}{_RST}  {_DIM}paste your API key (enter = skip){_RST}")
            try:
                value = getpass.getpass(f"  {env}: ").strip()
            except (EOFError, KeyboardInterrupt):
                _warn(f"{pname} skipped")
                continue
            if value:
                cfg_mod.set_secret(env, value)
                _ok(f"{pname} configured")
                any_key = True
            elif existing:
                _ok(f"{pname} — existing key kept")
                any_key = True
            else:
                _warn(f"{pname} skipped")

        if not any_key and 3 not in (chosen_providers or []):
            _warn("No cloud key set — nex will run locally via Ollama.")
    else:
        _warn("AI providers skipped — add later:  nex keys set anthropic")

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 2 of 3 — Tools & Connections
    # ══════════════════════════════════════════════════════════════════════════

    _step_header(2, "Tools & Connections", "Which integrations do you want to set up?")

    tool_labels = [
        "Telegram Bot",
        "Desktop GUI",
        "Autostart on login",
    ]
    tool_descs = [
        "chat with nex via Telegram  (@BotFather token required)",
        "pywebview — native window app",
        "systemd user service starts the nex daemon on login  (Linux)",
    ]

    chosen_tools = _multiselect_skippable(
        "Enable integrations:",
        tool_labels,
        descs=tool_descs,
        defaults=[],
    )

    do_telegram  = chosen_tools is not None and 0 in chosen_tools
    do_gui       = chosen_tools is not None and 1 in chosen_tools
    do_autostart = chosen_tools is not None and 2 in chosen_tools

    if do_telegram:
        print(f"\n  {_B}Telegram setup{_RST}")
        print(f"  {_DIM}Create a bot: @BotFather → /newbot  ·  Your ID: @userinfobot{_RST}")
        try:
            token    = getpass.getpass("  TELEGRAM_BOT_TOKEN: ").strip()
            admin_id = input("  Your Telegram user ID (number): ").strip()
        except (EOFError, KeyboardInterrupt):
            _warn("Telegram skipped")
            token, admin_id = "", ""
        if token:
            cfg_mod.set_secret("TELEGRAM_BOT_TOKEN", token)
            _ok("Telegram token saved")
        cfg_tg = cfg_mod.load()
        if admin_id:
            cfg_tg.telegram_admin_id = admin_id
            cfg_mod.save(cfg_tg)
            _ok(f"Telegram admin ID: {admin_id}")
        if token:
            _ok("Telegram ready — start with:  nex telegram")
    elif chosen_tools is not None:
        _warn("Telegram skipped — set up later:  nex admin telegram")

    if do_gui:
        _install_gui_deps()
    elif chosen_tools is not None:
        _warn("Desktop GUI skipped — install later:  pip install pywebview PyQt6")

    if do_autostart:
        _install_systemd_service()
    elif chosen_tools is not None and sys.platform == "linux":
        _warn("Autostart skipped — enable later:  nex admin service enable")

    if chosen_tools is None:
        _warn("Tools skipped — configure later:  nex admin")

    # Desktop-Icon immer erstellen (nex-gui muss installiert sein)
    _create_desktop_entry(with_desktop_link=(args.source != "server"))

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 3 of 3 — Allowed Documents
    # ══════════════════════════════════════════════════════════════════════════

    _step_header(3, "Allowed Documents", "Which Markdown files can nex read in your projects?")

    md_labels = [
        "CLAUDE.md",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "*.md  (all)",
    ]
    md_descs = [
        "project instructions for Claude Code  (recommended)",
        "project overview and quickstart",
        "version history",
        "contribution guidelines",
        "every Markdown file in the project",
    ]
    md_pattern_map = {
        0: "CLAUDE.md",
        1: "README.md",
        2: "CHANGELOG.md",
        3: "CONTRIBUTING.md",
        4: "*.md",
    }

    chosen_md = _multiselect_skippable(
        "Select allowed documents:",
        md_labels,
        descs=md_descs,
        defaults=[0, 1],
    )

    if chosen_md is not None:
        if 4 in chosen_md:
            allowed_md = ["*.md"]
        else:
            allowed_md = [md_pattern_map[i] for i in chosen_md if i in md_pattern_map]
        if not allowed_md:
            allowed_md = ["CLAUDE.md", "README.md"]
        try:
            cfg_md = cfg_mod.load()
            cfg_md.allowed_md_files = allowed_md  # type: ignore[attr-defined]
            cfg_mod.save(cfg_md)
        except Exception:
            pass
        _ok(f"Allowed documents: {', '.join(allowed_md)}")
    else:
        _warn("Documents skipped — default: CLAUDE.md, README.md")

    # ── Config speichern ───────────────────────────────────────────────────────
    cfg             = cfg_mod.load()
    cfg.role        = role
    cfg.install_source = args.source
    cfg.profile     = profile.name
    cfg.version     = __version__
    if rec_tag:
        cfg.house_base = rec_tag
    cfg_mod.save(cfg)

    # ── PATH ──────────────────────────────────────────────────────────────────
    venv_bin   = Path(sys.executable).parent
    path_line  = f'export PATH="{venv_bin}:$PATH"'
    path_added = False
    for rc in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
        if rc.exists() and str(venv_bin) not in rc.read_text():
            with rc.open("a") as f:
                f.write(f"\n# nex\n{path_line}\n")
            _ok(f"PATH added to {rc.name}")
            path_added = True

    # ── Fertig ─────────────────────────────────────────────────────────────────
    print()
    _bhr()
    msg = "nex is ready."
    pad = " " * ((_W - len(msg)) // 2)
    print(f"  {pad}{_G}{_B}{msg}{_RST}")
    _bhr()

    inst       = "admin" if role == "admin" else "user"
    shell_hint = (
        f"\n  {_Y}→ Open a new terminal or run:  source ~/.bashrc{_RST}"
        if path_added else ""
    )
    print(f"""
  {_B}Role:{_RST}  {_C}{role}{_RST}  ·  Profile: {_C}{profile.name}{_RST}  ·  Install: {inst}
{shell_hint}
  {_B}Get started:{_RST}
    {_C}nex-gui{_RST}               Open desktop GUI   {_DIM}← recommended{_RST}
    {_C}nex{_RST}                   Launch terminal harness
    {_C}nex doctor{_RST}            Hardware · profile · model gates
    {_C}nex chat{_RST}              Chat (every reply trains the model)

  {_DIM}Pull local model:   nex models pull house{_RST}
  {_DIM}Start training:     nex train run{_RST}
  {_DIM}Set cloud key:      nex keys set anthropic{_RST}
""")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(f"\n\n  {_Y}Setup abgebrochen.{_RST}\n")
        raise SystemExit(1)
