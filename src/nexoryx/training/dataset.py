"""Trainings-Datensatz (Flywheel-Erfassung) — JSONL, zero-dependency.

Jede echte Modell-Antwort (Cloud ODER lokal) wird als ein Beispiel im ChatML-
ähnlichen Format angehängt. Cloud-Antworten werden als `teacher=true` markiert
(höherwertiges Distillation-Signal). Der lokale Regel-Fallback wird NICHT erfasst
(kein Lernsignal).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..platform.config import CONFIG_DIR, ensure_dir

DATASET_DIR = CONFIG_DIR / "training"
DATASET_PATH = DATASET_DIR / "dataset.jsonl"


def record_interaction(prompt: str, system: str, response: str, *,
                       provider: str, model: str, task_type: str,
                       is_local: bool) -> None:
    if provider == "local-fallback" or not response.strip():
        return
    ensure_dir()
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    messages.append({"role": "assistant", "content": response})
    example = {
        "ts": time.time(),
        "task_type": task_type,
        "provider": provider,
        "model": model,
        "teacher": not is_local,  # Cloud = stärkerer Lehrer
        "messages": messages,
    }
    try:
        with open(DATASET_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(example, ensure_ascii=False) + "\n")
    except OSError:
        pass


def iter_examples():
    if not DATASET_PATH.exists():
        return
    with open(DATASET_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def stats() -> dict:
    total = teacher = 0
    by_provider: dict[str, int] = {}
    by_task: dict[str, int] = {}
    for ex in iter_examples():
        total += 1
        teacher += 1 if ex.get("teacher") else 0
        by_provider[ex.get("provider", "?")] = by_provider.get(ex.get("provider", "?"), 0) + 1
        by_task[ex.get("task_type", "?")] = by_task.get(ex.get("task_type", "?"), 0) + 1
    size = DATASET_PATH.stat().st_size if DATASET_PATH.exists() else 0
    return {"total": total, "teacher": teacher, "by_provider": by_provider,
            "by_task": by_task, "bytes": size, "path": str(DATASET_PATH)}


def export_chatml(out_path: str, teacher_only: bool = False) -> int:
    """Datensatz als ChatML-JSONL exportieren (für Fine-Tuning). Anzahl Zeilen."""
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for ex in iter_examples():
            if teacher_only and not ex.get("teacher"):
                continue
            out.write(json.dumps({"messages": ex["messages"]}, ensure_ascii=False) + "\n")
            n += 1
    return n
