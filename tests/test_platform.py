"""Smoke-Tests für die Plattform-Schicht (Phase 0)."""

from nexoryx.platform import detect, choose_profile, model_gates
from nexoryx.platform import config as cfg_mod


def test_detect_never_raises_and_has_basics():
    hw = detect()
    assert hw.os_name
    assert hw.cpu_cores_logical >= 1


def test_profile_is_one_of_three():
    hw = detect()
    profile = choose_profile(hw)
    assert profile.name in ("ultra_lite", "balanced", "pro")
    assert profile.max_parallel_agents >= 1


def test_tiny_always_allowed():
    gates = model_gates(detect())
    assert gates["nexoryx-tiny"] is True


def test_admin_gating_requires_server_token():
    # Öffentliche Quelle ODER fehlender Token → user
    assert cfg_mod.resolve_role("", "public") == "user"
    assert cfg_mod.resolve_role("sometoken", "public") == "user"
    assert cfg_mod.resolve_role("", "server") == "user"
    # Server + gültiger Token → admin
    assert cfg_mod.resolve_role("sometoken", "server") == "admin"
