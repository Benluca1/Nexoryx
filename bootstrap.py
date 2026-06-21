#!/usr/bin/env python3
"""Nexoryx Bootstrap-Installer.

Wird von install.sh aufgerufen. Macht in dieser Phase:
  1. Python-Version prüfen
  2. Hardware analysieren + Profil wählen
  3. Rolle bestimmen (Admin NUR via Server-Install-Token, Plan §16.3)
  4. Config nach ~/.nexoryx/ schreiben
  5. Zusammenfassung + nächste Schritte ausgeben

Spätere Phasen ergänzen hier venv-Erstellung, Modell-Download und
Telegram-Setup (Plan §4).

Aufruf-Beispiele:
  python3 bootstrap.py                                   # User-Modus
  python3 bootstrap.py --role=admin --admin-enable=TOK   # via Server (Admin)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# bootstrap.py liegt im Repo-Root neben src/ → src/ importierbar machen.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nexoryx import __version__  # noqa: E402
from nexoryx.platform import detect, choose_profile, model_gates  # noqa: E402
from nexoryx.platform import config as cfg_mod  # noqa: E402

MIN_PY = (3, 11)


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexoryx Bootstrap-Installer")
    parser.add_argument("--role", default="user", choices=["user", "admin"])
    parser.add_argument("--admin-enable", default="", help="Server-Admin-Token (nur via Server-Install)")
    parser.add_argument("--source", default="manual", choices=["server", "public", "manual"])
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args(argv)

    print("\n\033[1mNexoryx Installer\033[0m")
    print(f"  Version {__version__}\n")

    # 1) Python-Version
    if sys.version_info < MIN_PY:
        _warn(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ empfohlen (gefunden {sys.version.split()[0]}).")
    else:
        _ok(f"Python {sys.version.split()[0]}")

    # 2) Hardware + Profil
    print("\n\033[1mHardware-Analyse\033[0m")
    hw = detect()
    profile = choose_profile(hw)
    gates = model_gates(hw)
    _ok(f"{hw.cpu_model} — {hw.cpu_cores_logical} Kerne, {hw.ram_mb} MB RAM")
    _ok(f"GPU: {hw.gpu.name or hw.gpu.vendor}" + (f" ({hw.vram_mb} MB VRAM)" if hw.vram_mb else ""))
    _ok(f"Profil: \033[32m{profile.name}\033[0m — {profile.reason}")
    allowed = [m for m, ok in gates.items() if ok]
    _ok(f"Erlaubte Modelle: {', '.join(allowed)}")

    # 3) Rolle bestimmen (Admin-Gating)
    role = cfg_mod.resolve_role(args.admin_enable, args.source)
    print("\n\033[1mInstanz-Rolle\033[0m")
    if role == "admin":
        _ok("Admin/Owner-Modus aktiviert (Install über Server erkannt).")
    else:
        _warn("User-Modus (keine Admin-Funktionen — nur via Server-Install, §16.3).")

    # 4) Config schreiben
    cfg = cfg_mod.load()
    cfg.role = role
    cfg.install_source = args.source
    cfg.profile = profile.name
    cfg.version = __version__
    cfg_mod.save(cfg)
    _ok(f"Config gespeichert: {cfg_mod.CONFIG_PATH}")

    # 5) Nächste Schritte
    print("\n\033[1mFertig.\033[0m Nächste Schritte:")
    print("  nexoryx doctor      # Hardware + Profil prüfen")
    print("  nexoryx ask \"...\"   # (Phase 1)")
    if role == "admin":
        print("  nexoryx admin status")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
