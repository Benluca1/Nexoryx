"""Hardware-basierte Auswahl des Start-/House-Modells.

Wie beim Modell-Gating (§3): pro Profil ein bestehendes Modell als Basis —
klein auf schwacher, groß auf starker Hardware. Dieses Modell wird genutzt,
solange das eigene noch nicht trainiert ist, und ist die Distillation-Basis.
"""

from __future__ import annotations

from ..platform.detect import Hardware
from ..platform.profile import Profile

# Pro Profil: Ollama-Tag (lokal ziehbar) + HuggingFace-ID (für Fine-Tuning).
HOUSE_BASES = {
    "ultra_lite": {
        "ollama": "qwen2.5:0.5b",
        "hf": "Qwen/Qwen2.5-0.5B-Instruct",
        "note": "winzig, CPU-only",
    },
    "balanced": {
        "ollama": "qwen2.5:3b",
        "hf": "Qwen/Qwen2.5-3B-Instruct",
        "note": "klein-mittel",
    },
    "pro": {
        "ollama": "qwen2.5:14b",
        "hf": "Qwen/Qwen2.5-14B-Instruct",
        "note": "groß, GPU empfohlen",
    },
}


def recommended_base(profile: Profile, hw: Hardware | None = None) -> dict:
    base = dict(HOUSE_BASES.get(profile.name, HOUSE_BASES["balanced"]))
    base["profile"] = profile.name
    return base
