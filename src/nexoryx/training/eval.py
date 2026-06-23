"""Eval-Gate fürs Hausmodell (Plan §3.3 Schritt 5, §11.3 Punkt 8).

Ein frisch trainiertes ``nexoryx-house-vN`` wird NUR aktiviert, wenn es das
bisherige Modell (oder die Basis) auf einem Holdout aus Teacher-Beispielen
nicht unterbietet — sonst Rollback aufs alte Modell. Gemessen wird
lexikalisches Token-F1 gegen die Teacher-Referenzantwort: kein Cloud-/Judge-
Modell nötig, CPU-only, zero-dependency.

Holdout-Split ist deterministisch (stabiler MD5-Hash der Nutzerfrage), damit
Trainings- und Testmenge sich nie überschneiden — ``train._select_examples``
schließt exakt dieselben Holdout-Keys aus.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from . import dataset

# Holdout: ~1/6 der Teacher-Beispiele, gedeckelt
HOLDOUT_DIVISOR = 6
HOLDOUT_MAX     = 8
MIN_HOLDOUT     = 3
# Rausch-Toleranz: minimale Regression gilt nicht als „schlechter"
EPSILON         = 0.02
# kurze Antworten reichen zum Bewerten und halten die CPU-Last gering
EVAL_MAX_TOKENS = 200


def _first(ex: dict, role: str) -> str:
    for m in ex.get("messages", []):
        if m.get("role") == role:
            return m.get("content", "")
    return ""


def _stable_hash(text: str) -> int:
    """PYTHONHASHSEED-unabhängiger Hash (eingebautes hash() ist randomisiert)."""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _token_f1(pred: str, ref: str) -> float:
    """Token-Overlap-F1 (Multiset) zwischen Vorhersage und Referenz."""
    p, r = _tokens(pred), _tokens(ref)
    if not p or not r:
        return 0.0
    overlap = sum((Counter(p) & Counter(r)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(p)
    recall = overlap / len(r)
    return 2 * precision * recall / (precision + recall)


def _is_holdout(ex: dict) -> bool:
    if not ex.get("teacher"):
        return False
    user = _first(ex, "user").strip()
    answer = _first(ex, "assistant").strip()
    if len(user) < 3 or len(answer) < 15:
        return False
    return _stable_hash(user) % HOLDOUT_DIVISOR == 0


def holdout_keys() -> set[tuple[str, str]]:
    """(user, assistant)-Keys des Holdouts — von train zum Ausschluss genutzt."""
    keys: set[tuple[str, str]] = set()
    for ex in dataset.iter_examples():
        if _is_holdout(ex):
            keys.add((_first(ex, "user").strip().lower(),
                      _first(ex, "assistant").strip().lower()))
    return keys


def holdout_examples(max_n: int = HOLDOUT_MAX) -> list[dict]:
    out = [ex for ex in dataset.iter_examples() if _is_holdout(ex)]
    out.sort(key=lambda e: _stable_hash(_first(e, "user")))
    return out[:max_n]


def _generate(model_tag: str, prompt: str, system: str) -> str | None:
    """Returns None if inference fails — callers must not treat this as score 0.0."""
    from ..router.base import ChatRequest
    from ..router.providers.ollama import OllamaProvider

    req = ChatRequest(prompt=prompt, system=system, max_tokens=EVAL_MAX_TOKENS)
    try:
        return OllamaProvider().generate(req, model_tag).text
    except Exception:
        return None


def score_model(model_tag: str, examples: list[dict]) -> float | None:
    """Mittleres Token-F1 des Modells über die Holdout-Beispiele.

    Gibt None zurück wenn Ollama nicht erreichbar ist — Aufrufer entscheidet.
    """
    if not examples:
        return None
    scores = []
    for ex in examples:
        pred = _generate(model_tag, _first(ex, "user"), _first(ex, "system"))
        if pred is None:
            return None  # Ollama nicht erreichbar — kein Score möglich
        scores.append(_token_f1(pred, _first(ex, "assistant")))
    return sum(scores) / len(scores) if scores else None


def gate(candidate_tag: str, incumbent_tag: str, max_n: int = HOLDOUT_MAX) -> dict:
    """Entscheidet, ob `candidate_tag` `incumbent_tag` ablösen darf.

    Promotion, wenn der Kandidat die Baseline nicht (über EPSILON hinaus)
    unterbietet. Bei zu kleinem Holdout wird ohne Eval promotet. Bei nicht
    erreichbarem Ollama wird fail-closed entschieden (Rollback).
    """
    examples = holdout_examples(max_n)
    if len(examples) < MIN_HOLDOUT:
        return {
            "promote": True,
            "candidate_score": None,
            "incumbent_score": None,
            "n": len(examples),
            "reason": f"zu wenig Holdout ({len(examples)}<{MIN_HOLDOUT}) — Promotion ohne Eval",
        }

    cand = score_model(candidate_tag, examples)
    if cand is None:
        return {
            "promote": False,
            "candidate_score": None,
            "incumbent_score": None,
            "n": len(examples),
            "reason": "Eval-Infra nicht verfügbar (Ollama?) — Rollback auf Incumbent",
        }

    if incumbent_tag and incumbent_tag != candidate_tag:
        inc = score_model(incumbent_tag, examples)
        if inc is None:
            inc = 0.0  # Incumbent nicht scorebar → Kandidat bekommt Vorteil
    else:
        inc = 0.0

    promote = cand >= inc - EPSILON
    return {
        "promote": promote,
        "candidate_score": round(cand, 4),
        "incumbent_score": round(inc, 4),
        "n": len(examples),
        "epsilon": EPSILON,
        "reason": ("Kandidat ≥ Baseline — Promotion"
                   if promote else "Kandidat schlechter als Baseline — Rollback"),
    }
