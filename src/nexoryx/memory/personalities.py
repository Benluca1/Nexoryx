"""Persönlichkeits-System — wechselbare Charaktere für Nexoryx.

Persönlichkeiten liegen als .json in ~/.nexoryx/personalities/.
Standard: "nex" (vorinstalliert).
"""
from __future__ import annotations

import json
from pathlib import Path
from ..platform.config import CONFIG_DIR

PERSONALITIES_DIR = CONFIG_DIR / "personalities"

# Standard-Persönlichkeit, die beim ersten Start angelegt wird
_DEFAULT_PERSONALITIES: dict[str, dict] = {
    "nex": {
        "name": "nex",
        "display_name": "Nex",
        "tone": "freundlich, direkt, kompetent",
        "language": "Deutsch",
        "is_default": True,
        "system_prompt": (
            "Du bist Nex, ein kompetenter und freundlicher KI-Assistent. "
            "Du hilfst dem Nutzer bei allem — Fragen beantworten, Dateien erstellen, "
            "Programme öffnen, den PC steuern. "
            "Antworte immer auf Deutsch. Sei präzise und halte Antworten kurz."
        ),
    },
    "coder": {
        "name": "coder",
        "display_name": "Coder",
        "tone": "technisch, sachlich, präzise",
        "language": "Deutsch",
        "is_default": False,
        "system_prompt": (
            "Du bist Coder, ein technischer Programmier-Assistent. "
            "Du fokussierst dich auf Code, Debugging und technische Erklärungen. "
            "Antworte präzise, nutze Code-Blöcke wo sinnvoll, sei knapp."
        ),
    },
}


def _ensure_defaults() -> None:
    PERSONALITIES_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in _DEFAULT_PERSONALITIES.items():
        p = PERSONALITIES_DIR / f"{name}.json"
        if not p.exists():
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_personalities() -> list[dict]:
    _ensure_defaults()
    result = []
    for p in sorted(PERSONALITIES_DIR.glob("*.json")):
        try:
            result.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return result


def get(name: str) -> dict | None:
    _ensure_defaults()
    p = PERSONALITIES_DIR / f"{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_default() -> dict:
    _ensure_defaults()
    for p in list_personalities():
        if p.get("is_default"):
            return p
    return _DEFAULT_PERSONALITIES["nex"]


def set_default(name: str) -> bool:
    _ensure_defaults()
    # Erst alle is_default = false
    for p in sorted(PERSONALITIES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["is_default"] = False
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            continue
    # Dann gewünschte = true
    target = PERSONALITIES_DIR / f"{name}.json"
    if not target.exists():
        return False
    data = json.loads(target.read_text(encoding="utf-8"))
    data["is_default"] = True
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def create(name: str, display_name: str, tone: str, language: str,
           system_prompt: str, is_default: bool = False) -> dict:
    _ensure_defaults()
    data = {
        "name": name,
        "display_name": display_name,
        "tone": tone,
        "language": language,
        "is_default": is_default,
        "system_prompt": system_prompt,
    }
    if is_default:
        set_default("__none__")  # alle auf false
    p = PERSONALITIES_DIR / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if is_default:
        set_default(name)
    return data


def delete(name: str) -> bool:
    if name in ("nex",):  # Standard schützen
        return False
    p = PERSONALITIES_DIR / f"{name}.json"
    if p.exists():
        p.unlink()
        return True
    return False
