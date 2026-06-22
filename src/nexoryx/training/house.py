"""Haus-Modell-Konfiguration.

Basismodell ist immer qwen2.5:0.5b — läuft auf jeder Hardware (CPU-only, 4 GB RAM).
Nach dem Training heißt das Modell nexoryx-house-vN und wird in Ollama registriert.
"""

from __future__ import annotations

from ..platform.detect import Hardware
from ..platform.profile import Profile

HOUSE_BASE = "qwen2.5:0.5b"
HOUSE_HF   = "Qwen/Qwen2.5-0.5B-Instruct"

# Für größere Hardware: optionale bessere Basis beim Pull
HOUSE_BASES = {
    "ultra_lite": {"ollama": "qwen2.5:0.5b",  "hf": "Qwen/Qwen2.5-0.5B-Instruct"},
    "balanced":   {"ollama": "qwen2.5:3b",    "hf": "Qwen/Qwen2.5-3B-Instruct"},
    "pro":        {"ollama": "qwen2.5:14b",   "hf": "Qwen/Qwen2.5-14B-Instruct"},
}


def recommended_base(profile: Profile, hw: Hardware | None = None) -> dict:
    base = dict(HOUSE_BASES.get(profile.name, HOUSE_BASES["balanced"]))
    base["profile"] = profile.name
    return base
