"""platform/scanner.py — Automatischer Hintergrund-Malware-Scan beim Programmstart.

Ablauf bei jedem Start:
  1. check_pending()      — Befunde des letzten Scans sofort anzeigen (kein Warten).
  2. start_background_scan() — Neuen Scan im Daemon-Thread starten; Ergebnis in Datei.
  3. Nächster Start zeigt neue Befunde — Startup-Verzögerung = null.

Scan höchstens 1× pro 24 h (Timestamp-Lock). Kein Ergebnis = keine Ausgabe.

Backends (Priorität):
  1. ClamAV (clamscan)      — weit verbreitet, Linux/macOS
  2. rkhunter               — Linux Rootkit-Erkennung
  3. Windows Defender        — Windows (MpCmdRun.exe via PowerShell)
  4. Python-Heuristik        — Immer verfügbar, kein Zusatz-Tool nötig
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# --- Pfade -------------------------------------------------------------------

_DIR = Path.home() / ".nexoryx"
_PENDING_FILE = _DIR / ".scan_pending.json"   # Befunde des letzten Scans
_STAMP_FILE = _DIR / ".scan_stamp"            # letzter Scan-Zeitpunkt (Unix-Ts)
_LOG_FILE = _DIR / "logs" / "security.log"
_SCAN_INTERVAL = 86_400                       # 24 h

# --- Farben (nur wenn TTY) ---------------------------------------------------

_IS_TTY = sys.stderr.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


# --- Öffentliche API ---------------------------------------------------------


def check_pending() -> bool:
    """Ausstehende Befunde des letzten Scans anzeigen. Gibt True zurück wenn Bedrohungen vorhanden."""
    if not _PENDING_FILE.exists():
        return False
    try:
        data = json.loads(_PENDING_FILE.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    threats: list[dict] = data.get("threats", [])
    if not threats:
        _PENDING_FILE.unlink(missing_ok=True)
        return False

    scanned_at = data.get("scanned_at", "?")
    backend = data.get("backend", "?")

    # Warnung ausgeben
    print(_c("\n╔══════════════════════════════════════════════════════╗", "31;1"), file=sys.stderr)
    print(_c("║  SICHERHEITSWARNUNG — Nexoryx Malware-Scan            ║", "31;1"), file=sys.stderr)
    print(_c("╚══════════════════════════════════════════════════════╝", "31;1"), file=sys.stderr)
    print(_c(f"  Scan vom {scanned_at} via {backend}", "33"), file=sys.stderr)
    print(_c(f"  {len(threats)} Bedrohung(en) gefunden:\n", "31"), file=sys.stderr)
    for t in threats:
        sev_color = "31;1" if t.get("severity") == "high" else "33"
        print(_c(f"  [{t.get('severity','?').upper()}]", sev_color) +
              f" {t.get('path', '?')}", file=sys.stderr)
        if t.get("detail"):
            print(_c(f"       → {t['detail']}", "2"), file=sys.stderr)
    print(file=sys.stderr)
    print(_c("  Empfehlung: Verdächtige Dateien prüfen und ggf. löschen.", "33"), file=sys.stderr)
    print(_c("  Log: ~/.nexoryx/logs/security.log\n", "2"), file=sys.stderr)

    _PENDING_FILE.unlink(missing_ok=True)
    return True


def start_background_scan() -> None:
    """Startet Scan-Daemon-Thread falls der letzte Scan > 24 h her ist."""
    if _scan_recent():
        return
    t = threading.Thread(target=_run_scan, daemon=True, name="nexoryx-scanner")
    t.start()


# --- Internes ----------------------------------------------------------------


def _scan_recent() -> bool:
    try:
        last = float(_STAMP_FILE.read_text().strip())
        return (time.time() - last) < _SCAN_INTERVAL
    except (OSError, ValueError):
        return False


def _run_scan() -> None:
    threats: list[dict] = []
    backend = "heuristics"

    try:
        if shutil.which("clamscan"):
            threats, backend = _scan_clamav(), "ClamAV"
        elif shutil.which("rkhunter"):
            threats, backend = _scan_rkhunter(), "rkhunter"
        elif sys.platform == "win32" and _defender_available():
            threats, backend = _scan_defender(), "Windows Defender"
        else:
            threats, backend = _scan_heuristics(), "heuristics"
    except Exception as exc:  # noqa: BLE001
        _log(f"Scan-Fehler ({backend}): {exc}")
        return

    # Timestamp aktualisieren
    _DIR.mkdir(parents=True, exist_ok=True)
    _STAMP_FILE.write_text(str(time.time()))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    _log(f"[{now}] Scan ({backend}): {len(threats)} Bedrohung(en)")

    if threats:
        # Befunde für nächsten Start speichern
        _PENDING_FILE.write_text(json.dumps({
            "scanned_at": now,
            "backend": backend,
            "threats": threats,
        }, ensure_ascii=False, indent=2), "utf-8")
        # Sofort-Benachrichtigung in laufendem Daemon / long-running Prozess
        _notify_telegram(threats, now, backend)


# --- Backend: ClamAV ---------------------------------------------------------

_CLAMAV_PATHS = [
    Path("/tmp"),
    Path("/var/tmp"),
    Path.home() / ".local" / "bin",
    Path.home() / ".config" / "autostart",
    Path.home() / ".nexoryx",
    Path("/etc/cron.d"),
    Path("/etc/cron.daily"),
    Path("/etc/cron.hourly"),
]


def _scan_clamav() -> list[dict]:
    paths = [str(p) for p in _CLAMAV_PATHS if p.exists()]
    if not paths:
        return []
    cmd = [
        "clamscan",
        "--infected",       # nur infizierte ausgeben
        "--no-summary",
        "--recursive",
        "--max-filesize=50M",
        "--max-scansize=200M",
        "--quiet",
    ] + paths
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [{"path": "(Timeout)", "detail": "ClamAV-Scan abgebrochen (>120 s)", "severity": "medium"}]

    threats = []
    for line in result.stdout.splitlines():
        # Format: "/pfad/datei: Virus.Name FOUND"
        if " FOUND" in line:
            parts = line.split(":", 1)
            path = parts[0].strip()
            detail = parts[1].strip() if len(parts) > 1 else ""
            threats.append({"path": path, "detail": detail, "severity": "high"})
    return threats


# --- Backend: rkhunter -------------------------------------------------------


def _scan_rkhunter() -> list[dict]:
    cmd = ["rkhunter", "--check", "--skip-keypress", "--quiet", "--noappend-log"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return [{"path": "(Timeout)", "detail": "rkhunter abgebrochen (>180 s)", "severity": "medium"}]

    threats = []
    warn_re = re.compile(r"Warning:\s+(.+)", re.IGNORECASE)
    found_re = re.compile(r"\[(.+)\]\s+.*Warning", re.IGNORECASE)
    for line in (result.stdout + result.stderr).splitlines():
        m = warn_re.search(line)
        if m:
            threats.append({"path": "(system)", "detail": m.group(1).strip(), "severity": "high"})
    return threats


# --- Backend: Windows Defender -----------------------------------------------


def _defender_available() -> bool:
    mppath = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / \
        "Windows Defender" / "MpCmdRun.exe"
    return mppath.exists()


def _scan_defender() -> list[dict]:
    mppath = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / \
        "Windows Defender" / "MpCmdRun.exe"
    cmd = [str(mppath), "-Scan", "-ScanType", "1"]  # Quick Scan
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return [{"path": "(Timeout)", "detail": "Defender-Scan abgebrochen (>180 s)", "severity": "medium"}]

    threats = []
    for line in (result.stdout + result.stderr).splitlines():
        if "threat" in line.lower() or "found" in line.lower():
            threats.append({"path": "(Windows)", "detail": line.strip(), "severity": "high"})
    return threats


# --- Backend: Python-Heuristik (immer verfügbar) -----------------------------

_SUSP_PATTERNS = re.compile(
    r"(curl|wget|python|perl|ruby|bash|sh)\s.*\|.*\s*(bash|sh|python)",
    re.IGNORECASE,
)

_HIGH_RISK_DIRS = [Path("/tmp"), Path("/var/tmp")] + (
    [Path(os.environ.get("TEMP", "C:/Temp"))] if sys.platform == "win32" else []
)

_SHELL_INIT = [
    Path.home() / ".bashrc",
    Path.home() / ".bash_profile",
    Path.home() / ".profile",
    Path.home() / ".zshrc",
    Path.home() / ".config" / "fish" / "config.fish",
]


def _scan_heuristics() -> list[dict]:
    threats: list[dict] = []

    # 1. Ausführbare Dateien in Temp-Verzeichnissen
    for tmpdir in _HIGH_RISK_DIRS:
        if not tmpdir.exists():
            continue
        try:
            for p in tmpdir.iterdir():
                if p.is_file() and os.access(str(p), os.X_OK):
                    threats.append({
                        "path": str(p),
                        "detail": "Ausführbare Datei in Temp-Verzeichnis",
                        "severity": "high",
                    })
        except PermissionError:
            pass

    # 2. Shell-Init-Dateien: verdächtige Download+Execute-Muster
    for rc in _SHELL_INIT:
        if not rc.exists():
            continue
        try:
            content = rc.read_text("utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            if _SUSP_PATTERNS.search(line) and not line.strip().startswith("#"):
                threats.append({
                    "path": f"{rc}:{lineno}",
                    "detail": f"Verdächtiger Download+Execute-Aufruf: {line.strip()[:80]}",
                    "severity": "high",
                })

    # 3. SUID-Dateien im Home-Verzeichnis (sollte es nicht geben)
    if sys.platform != "win32":
        home = Path.home()
        try:
            result = subprocess.run(
                ["find", str(home), "-maxdepth", "4", "-perm", "/4000", "-type", "f"],
                capture_output=True, text=True, timeout=20,
            )
            for line in result.stdout.splitlines():
                if line.strip():
                    threats.append({
                        "path": line.strip(),
                        "detail": "SUID-Datei im Home-Verzeichnis",
                        "severity": "medium",
                    })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # 4. Cron-Einträge mit verdächtigen Download-Patterns
    cron_dirs = [Path("/etc/cron.d"), Path("/etc/cron.daily"), Path("/var/spool/cron")]
    for crondir in cron_dirs:
        if not crondir.exists():
            continue
        try:
            for cfile in crondir.iterdir():
                if not cfile.is_file():
                    continue
                try:
                    text = cfile.read_text("utf-8", errors="replace")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if _SUSP_PATTERNS.search(line) and not line.strip().startswith("#"):
                        threats.append({
                            "path": f"{cfile}:{lineno}",
                            "detail": f"Verdächtiger Cron-Eintrag: {line.strip()[:80]}",
                            "severity": "high",
                        })
        except PermissionError:
            pass

    # 5. Prozesse aus Temp-Verzeichnissen (Linux /proc)
    if sys.platform == "linux" and Path("/proc").exists():
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                exe = pid_dir / "exe"
                try:
                    target = os.readlink(str(exe))
                    if any(target.startswith(str(d)) for d in _HIGH_RISK_DIRS):
                        threats.append({
                            "path": target,
                            "detail": f"Prozess (PID {pid_dir.name}) aus Temp-Verzeichnis gestartet",
                            "severity": "high",
                        })
                except (OSError, PermissionError):
                    pass
        except PermissionError:
            pass

    return threats


# --- Logging & Notification --------------------------------------------------


def _log(message: str) -> None:
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        pass


def _notify_telegram(threats: list[dict], scanned_at: str, backend: str) -> None:
    """Telegram-Benachrichtigung falls Bot konfiguriert (optional)."""
    try:
        from ..platform import config as cfg_mod
        cfg = cfg_mod.load()
        token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
        admin_id = cfg.telegram_admin_id
        if not token or not admin_id:
            return
        import urllib.request, urllib.parse
        lines = [f"🚨 *Nexoryx Sicherheitswarnung* ({scanned_at}, via {backend})"]
        for t in threats[:10]:
            sev = "🔴" if t.get("severity") == "high" else "🟡"
            lines.append(f"{sev} `{t.get('path','?')}`")
            if t.get("detail"):
                lines.append(f"   _{t['detail'][:100]}_")
        text = "\n".join(lines)
        data = urllib.parse.urlencode({
            "chat_id": admin_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        urllib.request.urlopen(url, data=data, timeout=8)
    except Exception:  # noqa: BLE001
        pass
