"""nex_admin — spezialisiertes Modell für Coding und Security-Research.

Erstellt via Ollama Modelfile (CPU-tauglich, kein GPU nötig).
Basis: qwen2.5:0.5b  →  nex_admin (Ollama-Tag)

Themen: CTF, Pentest (autorisiert), Exploit-Entwicklung, Code-Analyse,
        Shell-Scripting, Netzwerk-Security, Bug-Hunting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODELFILE = _REPO_ROOT / "training" / "modelfiles" / "nex_admin.modelfile"
_ADMIN_BASE = "qwen2.5:0.5b"
MODEL_TAG = "nex_admin"


def _ollama_available() -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _model_exists(tag: str) -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return tag in r.stdout
    except Exception:
        return False


def _check_admin() -> None:
    """Wirft PermissionError wenn die laufende Instanz keine Admin-Rolle hat."""
    from ..platform import config as cfg_mod
    cfg = cfg_mod.load()
    if not cfg.is_admin():
        raise PermissionError(
            "nex_admin ist nur für Admin-Instanzen verfügbar. "
            "Rolle upgraden: nexoryx admin  (Passwort eingeben)"
        )


def train_admin(log_fn=print) -> dict:
    """Erstellt oder aktualisiert das nex_admin-Modell via Ollama Modelfile.

    Nur für Admin-Instanzen. Gibt einen Status-Report zurück.
    """
    _check_admin()
    if not _ollama_available():
        return {
            "action": "failed",
            "error": "Ollama nicht verfügbar. Starte mit: ollama serve",
        }

    if not _MODELFILE.exists():
        return {
            "action": "failed",
            "error": f"Modelfile nicht gefunden: {_MODELFILE}",
        }

    log_fn(f"[nex_admin] Lese Modelfile: {_MODELFILE}")
    log_fn(f"[nex_admin] Erstelle Modell '{MODEL_TAG}' via Ollama…")

    result = subprocess.run(
        ["ollama", "create", MODEL_TAG, "-f", str(_MODELFILE)],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()[:500]
        return {"action": "failed", "error": err}

    modelfile_lines = _MODELFILE.read_text(encoding="utf-8").splitlines()
    msg_count = sum(1 for l in modelfile_lines if l.startswith("MESSAGE user"))

    log_fn(f"[nex_admin] ✓ Modell '{MODEL_TAG}' erfolgreich erstellt ({msg_count} Trainingsbeispiele)")
    return {
        "action": "trained",
        "model_tag": MODEL_TAG,
        "base": _ADMIN_BASE,
        "modelfile": str(_MODELFILE),
        "examples": msg_count,
    }


def admin_status() -> dict:
    _check_admin()
    return {
        "model_tag": MODEL_TAG,
        "model_exists": _model_exists(MODEL_TAG),
        "ollama_available": _ollama_available(),
        "modelfile_exists": _MODELFILE.exists(),
        "modelfile_path": str(_MODELFILE),
    }
