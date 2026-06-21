"""Capability-Profil — leitet aus der Hardware den Betriebsmodus ab.

Drei Profile (ultra_lite | balanced | pro) plus Modell-Gates, die hart
entscheiden, welche Modelle auf dieser Maschine überhaupt erlaubt sind.
Leitprinzip: lieber konservativ einstufen → garantiert lauffähig.
"""

from __future__ import annotations

from dataclasses import dataclass

from .detect import Hardware

# Modell-Schwellen (siehe Plan §3). vram ODER ram erfüllt → erlaubt.
MODEL_REQUIREMENTS = {
    "nexoryx-tiny": {"min_ram_mb": 0, "min_vram_mb": 0},
    "nexoryx-mini": {"min_ram_mb": 8_000, "min_vram_mb": 6_000},
    "nexoryx-large": {"min_ram_mb": 48_000, "min_vram_mb": 24_000},
}


@dataclass
class Profile:
    name: str  # ultra_lite | balanced | pro
    multi_agent: bool
    gpu_accel: bool
    max_parallel_agents: int
    reason: str


def choose_profile(hw: Hardware) -> Profile:
    """Profil anhand RAM, Kernen und GPU/VRAM wählen."""
    ram = hw.ram_mb
    cores = hw.cpu_cores_logical
    has_strong_gpu = hw.gpu.vendor in ("nvidia", "apple") and (
        hw.vram_mb >= 8_000 or hw.gpu.vendor == "apple"
    )

    # Pro: kräftige GPU oder sehr viel RAM + viele Kerne.
    if has_strong_gpu and (hw.vram_mb >= 16_000 or ram >= 32_000):
        return Profile(
            name="pro",
            multi_agent=True,
            gpu_accel=True,
            max_parallel_agents=max(2, min(8, cores // 2)),
            reason=f"Starke GPU ({hw.gpu.name or hw.gpu.vendor}) / {ram} MB RAM",
        )

    # Ultra-Lite: wenig RAM oder wenige Kerne, keine nutzbare GPU.
    if ram and ram < 6_000 or cores <= 2:
        return Profile(
            name="ultra_lite",
            multi_agent=False,
            gpu_accel=False,
            max_parallel_agents=1,
            reason=f"Schwache Hardware: {ram} MB RAM, {cores} Kerne",
        )

    # Balanced: alles dazwischen.
    return Profile(
        name="balanced",
        multi_agent=cores >= 4,
        gpu_accel=hw.gpu.vendor in ("nvidia", "amd", "apple"),
        max_parallel_agents=max(1, min(3, cores // 2)),
        reason=f"Mittelklasse: {ram} MB RAM, {cores} Kerne, GPU={hw.gpu.vendor}",
    )


def model_gates(hw: Hardware) -> dict[str, bool]:
    """Welche Modelle darf diese Maschine laden? (hartes Gate)"""
    gates: dict[str, bool] = {}
    for model, req in MODEL_REQUIREMENTS.items():
        ok_ram = hw.ram_mb >= req["min_ram_mb"] if hw.ram_mb else req["min_ram_mb"] == 0
        ok_vram = hw.vram_mb >= req["min_vram_mb"] if req["min_vram_mb"] else False
        # Tiny ist immer erlaubt; sonst RAM ODER ausreichende VRAM.
        gates[model] = req["min_ram_mb"] == 0 or ok_ram or ok_vram
    return gates
