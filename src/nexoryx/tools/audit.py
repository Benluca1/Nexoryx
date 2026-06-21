"""Append-only Audit-Log (Plan §7/§9). JSONL unter ~/.nexoryx/audit.log."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..platform.config import CONFIG_DIR, ensure_dir

AUDIT_PATH = CONFIG_DIR / "audit.log"


def audit(event: str, **fields) -> None:
    ensure_dir()
    record = {"ts": time.time(), "event": event, **fields}
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def tail(limit: int = 20) -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
