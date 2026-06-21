"""Usage- & Kosten-Tracking + Budget-Guard (Plan §2.4).

Persistiert Tagesverbrauch in ~/.nexoryx/usage.json. Der Router fragt vor
Cloud-Calls `over_budget()` und schließt bei Überschreitung Cloud-Modelle aus
(Downrouting auf lokal).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import CONFIG_DIR, ensure_dir

USAGE_PATH = CONFIG_DIR / "usage.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _load() -> dict:
    if not USAGE_PATH.exists():
        return {}
    try:
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    ensure_dir()
    USAGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record(provider: str, model: str, in_tok: int, out_tok: int, cost: float) -> None:
    data = _load()
    day = data.setdefault(_today(), {"requests": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0, "by_model": {}})
    day["requests"] += 1
    day["in_tok"] += in_tok
    day["out_tok"] += out_tok
    day["cost"] = round(day["cost"] + cost, 6)
    m = day["by_model"].setdefault(f"{provider}/{model}", {"requests": 0, "cost": 0.0})
    m["requests"] += 1
    m["cost"] = round(m["cost"] + cost, 6)
    _save(data)


def today() -> dict:
    return _load().get(_today(), {"requests": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0, "by_model": {}})


def over_budget(daily_cap: float) -> bool:
    if daily_cap <= 0:
        return False
    return today().get("cost", 0.0) >= daily_cap
