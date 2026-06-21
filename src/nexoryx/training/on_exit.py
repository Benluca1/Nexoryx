"""On-Exit-Hook: Training + Trainingsdaten-Upload nach Schließen der TUI.

Läuft nach dem Haupt-Loop — wenn der Nutzer `nex` beendet:
1. Neue Trainingsdaten in Repo-Ordner training/data/ kopieren
2. Persona-Wissen (memory/*.md) in Repo-Ordner training/persona/ spiegeln
3. Wenn genug Daten UND Deps vorhanden: Trainings-Skript erzeugen / Training starten
4. Alles zu GitHub pushen (sync.sh)
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .dataset import DATASET_PATH, stats, export_chatml
from ..platform.config import CONFIG_DIR

REPO_ROOT = Path(__file__).resolve().parents[3]
TRAINING_DATA_DIR = REPO_ROOT / "training" / "data"
PERSONA_MIRROR_DIR = REPO_ROOT / "training" / "persona"
MEMORY_DIR = CONFIG_DIR / "memory"

MIN_NEW_FOR_UPLOAD = 1   # ab 1 neuem Beispiel → pushen
MIN_FOR_TRAINING   = 20  # ab 20 Beispielen → Trainings-Skript erzeugen


def run(console=None, silent: bool = False) -> dict:
    """Haupt-Einstieg des On-Exit-Hooks.

    console: Rich-Console oder None (dann print)
    Gibt einen Status-Dict zurück.
    """
    report: dict = {"uploaded": False, "trained": False, "errors": []}

    def log(msg: str) -> None:
        if silent:
            return
        if console:
            console.print(f"  [dim]{msg}[/dim]")
        else:
            print(f"  {msg}")

    # ── 1. Trainingsdaten in Repo kopieren ────────────────────────────────────
    if not DATASET_PATH.exists():
        log("Keine Trainingsdaten vorhanden — nichts zu tun.")
        return report

    st = stats()
    if st["total"] < MIN_NEW_FOR_UPLOAD:
        log(f"Noch nicht genug Trainingsdaten ({st['total']}) — wird übersprungen.")
        return report

    try:
        TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = TRAINING_DATA_DIR / "dataset.jsonl"

        # Export als ChatML (saubereres Format für Training)
        n = export_chatml(str(dest))
        log(f"Trainingsdaten exportiert: {n} Beispiele → training/data/dataset.jsonl")
        report["examples"] = n
    except Exception as exc:
        report["errors"].append(f"Export: {exc}")
        log(f"Export fehlgeschlagen: {exc}")

    # ── 2. Persona-Dateien spiegeln ───────────────────────────────────────────
    try:
        if MEMORY_DIR.exists():
            PERSONA_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
            for md in MEMORY_DIR.glob("*.md"):
                shutil.copy2(md, PERSONA_MIRROR_DIR / md.name)
            log(f"Persona gespiegelt: {list(MEMORY_DIR.glob('*.md'))}")
    except Exception as exc:
        report["errors"].append(f"Persona: {exc}")

    # ── 3. Training auslösen (wenn Schwelle erreicht) ────────────────────────
    if st["total"] >= MIN_FOR_TRAINING:
        try:
            from .train import train
            train_report = train(repo_root=TRAINING_DATA_DIR.parent)
            report["train_action"] = train_report.get("action", "?")
            if train_report.get("action") == "trained":
                log("Eigenes Modell trainiert!")
                report["trained"] = True
            elif train_report.get("action") == "script_generated":
                log(f"Trainings-Skript erzeugt: {train_report.get('script')}")
            else:
                log(f"Training: {train_report.get('reason', train_report.get('action'))}")
        except Exception as exc:
            report["errors"].append(f"Training: {exc}")
            log(f"Training-Fehler: {exc}")

    # ── 4. Zu GitHub pushen ───────────────────────────────────────────────────
    sync = REPO_ROOT / "sync.sh"
    if not sync.exists():
        log("sync.sh nicht gefunden — Upload übersprungen.")
        return report

    try:
        log("Lade Trainingsdaten zu GitHub hoch …")
        msg = f"training: {st['total']} Beispiele, Sitzung {_ts()}"
        result = subprocess.run(
            ["bash", str(sync), msg],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
        )
        if result.returncode == 0:
            report["uploaded"] = True
            log("Trainingsdaten erfolgreich hochgeladen.")
        else:
            err = (result.stderr or result.stdout).strip()[:200]
            report["errors"].append(f"sync.sh: {err}")
            log(f"Upload fehlgeschlagen: {err}")
    except subprocess.TimeoutExpired:
        report["errors"].append("sync.sh: Timeout")
        log("Upload-Timeout — wird beim nächsten Mal erneut versucht.")
    except Exception as exc:
        report["errors"].append(f"sync.sh: {exc}")
        log(f"Upload-Fehler: {exc}")

    return report


def run_background(console=None) -> None:
    """Startet den On-Exit-Hook in einem Hintergrund-Thread."""
    import threading
    t = threading.Thread(target=run, kwargs={"console": console}, daemon=True)
    t.start()
    t.join(timeout=90)  # max. 90 Sekunden warten


def _ts() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M")
