"""On-Exit-Hook: Training + Trainingsdaten-Upload nach Schließen der TUI.

Läuft nach dem Haupt-Loop — wenn der Nutzer `nex` beendet:
1. Neue Trainingsdaten gerätespezifisch in training/data/<device>.jsonl schreiben
2. Persona-Wissen (memory/*.md) in training/persona/ spiegeln
3. Wenn genug Daten: Training auslösen / Skript erzeugen
4. Via Python-Git-Push zu GitHub hochladen (kein sync.sh nötig → funktioniert
   auf JEDEM Gerät, solange ein GitHub-PAT in ~/.nexoryx/secrets/github_pat liegt)

Gerätespezifische Dateien (training/data/<device>.jsonl) vermeiden Merge-Konflikte
wenn mehrere Geräte gleichzeitig pushen.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from .dataset import DATASET_PATH, stats, export_chatml
from ..platform.config import CONFIG_DIR

REPO_ROOT       = Path(__file__).resolve().parents[3]
TRAINING_DIR    = REPO_ROOT / "training"
TRAINING_DATA   = TRAINING_DIR / "data"
PERSONA_MIRROR  = TRAINING_DIR / "persona"
MEMORY_DIR      = CONFIG_DIR / "memory"
SECRETS_DIR     = CONFIG_DIR / "secrets"
PAT_FILE        = SECRETS_DIR / "github_pat"

MIN_NEW_FOR_UPLOAD = 1   # ab 1 neuem Beispiel → pushen
MIN_FOR_TRAINING   = 20  # ab 20 Beispielen → Trainings-Skript


def _device_id() -> str:
    """Eindeutiger, stabiler Gerätename (hostname, bereinigt)."""
    raw = socket.gethostname().lower()
    # nur alphanum + bindestrich, max 30 Zeichen
    clean = "".join(c if c.isalnum() or c == "-" else "-" for c in raw)[:30]
    return clean or "device"


def run(console=None, silent: bool = False) -> dict:
    """Haupt-Einstieg — wird nach dem Schließen der TUI aufgerufen."""
    report: dict = {"uploaded": False, "trained": False, "errors": []}

    def log(msg: str) -> None:
        if silent:
            return
        if console:
            console.print(f"  [dim]{msg}[/dim]")
        else:
            print(f"  {msg}")

    st = stats()

    # ── 1. Trainingsdaten exportieren ─────────────────────────────────────────
    if not DATASET_PATH.exists() or st["total"] < MIN_NEW_FOR_UPLOAD:
        log(f"Trainingsdaten: {st['total']} Beispiele — nichts zu pushen.")
        return report

    try:
        TRAINING_DATA.mkdir(parents=True, exist_ok=True)
        device = _device_id()
        dest = TRAINING_DATA / f"{device}.jsonl"
        n = export_chatml(str(dest))
        log(f"Trainingsdaten: {n} Beispiele → training/data/{device}.jsonl")
        report["examples"] = n
    except Exception as exc:
        report["errors"].append(f"Export: {exc}")
        log(f"Export fehlgeschlagen: {exc}")
        return report

    # ── 2. Persona-Dateien spiegeln ───────────────────────────────────────────
    try:
        if MEMORY_DIR.exists():
            PERSONA_MIRROR.mkdir(parents=True, exist_ok=True)
            for md in MEMORY_DIR.glob("*.md"):
                shutil.copy2(md, PERSONA_MIRROR / f"{device}_{md.name}")
    except Exception as exc:
        report["errors"].append(f"Persona: {exc}")

    # ── 3. Training (wenn Schwelle) ───────────────────────────────────────────
    if st["total"] >= MIN_FOR_TRAINING:
        try:
            from .train import train
            tr = train(repo_root=TRAINING_DIR)
            report["train_action"] = tr.get("action")
            if tr.get("action") == "trained":
                report["trained"] = True
                log("Modell trainiert!")
            elif tr.get("action") == "script_generated":
                log(f"Trainings-Skript: {tr.get('script')}")
            else:
                log(f"Training: {tr.get('reason', tr.get('action', '?'))}")
        except Exception as exc:
            report["errors"].append(f"Training: {exc}")

    # ── 4. GitHub-Push (von jedem Gerät) ─────────────────────────────────────
    ok, err = _git_push(log, st["total"])
    report["uploaded"] = ok
    if err:
        report["errors"].append(err)

    return report


def _git_push(log, example_count: int) -> tuple[bool, str]:
    """Git commit + push — nutzt PAT aus ~/.nexoryx/secrets/github_pat.

    Funktioniert ohne sync.sh auf jedem Gerät.
    """
    # PAT laden
    pat = _read_pat()
    if not pat:
        log("Kein GitHub-PAT gefunden (nexoryx admin keys set github) — Upload übersprungen.")
        return False, "kein PAT"

    # Remote-URL mit PAT zusammenbauen
    try:
        remote_raw = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT, text=True, timeout=5,
        ).strip()
    except Exception:
        log("Kein git-Remote gefunden — Upload übersprungen.")
        return False, "kein remote"

    remote_url = _inject_pat(remote_raw, pat)
    device = _device_id()
    commit_msg = f"training: {example_count} Beispiele von {device} ({_ts()})"

    try:
        # Erst pullen (--rebase) damit gerätespezifische Dateien anderer Geräte ankommen
        subprocess.run(
            ["git", "pull", "--rebase", "--autostash", remote_url, "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )

        # Stage nur training/ Ordner (keine Secrets, kein .env)
        subprocess.run(
            ["git", "add", "training/"],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=10,
        )

        # Prüfen ob es überhaupt Änderungen gibt
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_ROOT, timeout=5,
        )
        if diff.returncode == 0:
            log("Keine neuen Trainingsdaten seit letztem Push.")
            return True, ""

        # Commit
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=10,
        )
        log(f"Commit: {commit_msg}")

        # Push
        result = subprocess.run(
            ["git", "push", remote_url, "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=45,
        )
        if result.returncode == 0:
            log(f"Trainingsdaten hochgeladen ({device}).")
            return True, ""
        else:
            err = (result.stderr or result.stdout).strip()[:150]
            log(f"Push fehlgeschlagen: {err}")
            return False, err

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except subprocess.CalledProcessError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _read_pat() -> str:
    """Liest GitHub-PAT aus Secrets."""
    # 1. Datei
    if PAT_FILE.exists():
        try:
            return PAT_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    # 2. Umgebungsvariable
    return os.environ.get("GITHUB_PAT", "")


def _inject_pat(url: str, pat: str) -> str:
    """Fügt PAT in HTTPS-URL ein: https://github.com → https://PAT@github.com"""
    if "github.com" not in url:
        return url
    if "@" in url:
        # schon drin — ersetzen
        url = url.split("@", 1)[1]
        url = f"https://{url}"
    url = url.replace("https://", f"https://{pat}@")
    return url


def run_background(console=None) -> None:
    """Startet den Hook in einem Hintergrund-Thread (max. 90 s)."""
    import threading
    t = threading.Thread(target=run, kwargs={"console": console}, daemon=True)
    t.start()
    t.join(timeout=90)


def _ts() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M")
