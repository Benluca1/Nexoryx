"""Nexoryx CLI (`nexoryx`) — Phase-0-Stand.

Zero-dependency (argparse), damit es sofort ohne Installation läuft:
    python3 -m nexoryx doctor

Funktionsfähig: doctor, models list, admin status, version, panic (stub).
ask/run/models pull sind in dieser Phase Stubs, die sauber melden, dass die
Modell-/Router-Schicht erst in Phase 1+ kommt (siehe plan).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .platform import detect, choose_profile, model_gates
from .platform import config as cfg_mod

# --- kleine Ausgabe-Helfer (kein externes "rich") -------------------------

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{_RESET}"


def _header(text: str) -> None:
    print(_c(f"\n{text}", _BOLD))
    print(_c("─" * len(text), _DIM))


def _kv(key: str, value: str) -> None:
    print(f"  {key:<22} {value}")


# --- Befehle ---------------------------------------------------------------


def cmd_doctor(_args: argparse.Namespace) -> int:
    hw = detect()
    profile = choose_profile(hw)
    gates = model_gates(hw)
    cfg = cfg_mod.load()

    _header("Nexoryx Doctor")
    _kv("Version", __version__)

    _header("Hardware")
    _kv("OS", f"{hw.os_name} {hw.os_version} ({hw.arch})")
    _kv("CPU", hw.cpu_model)
    _kv("Kerne", f"{hw.cpu_cores_physical} physisch / {hw.cpu_cores_logical} logisch")
    _kv("RAM", f"{hw.ram_mb} MB" if hw.ram_mb else "unbekannt")
    gpu = hw.gpu
    gpu_str = gpu.vendor if gpu.vendor != "none" else "keine dedizierte GPU"
    if gpu.name:
        gpu_str = gpu.name
    if gpu.vram_mb:
        gpu_str += f" ({gpu.vram_mb} MB VRAM)"
    _kv("GPU", gpu_str)
    _kv("Freier Speicher", f"{hw.disk_free_mb} MB" if hw.disk_free_mb else "unbekannt")

    _header("Profil")
    _kv("Modus", _c(profile.name, _GREEN))
    _kv("Multi-Agent", "ja" if profile.multi_agent else "nein")
    _kv("GPU-Beschleunigung", "ja" if profile.gpu_accel else "nein")
    _kv("Max. parallele Agenten", str(profile.max_parallel_agents))
    _kv("Begründung", profile.reason)

    _header("Modell-Gates")
    for model, allowed in gates.items():
        mark = _c("✓ erlaubt", _GREEN) if allowed else _c("✗ HW zu schwach", _YELLOW)
        _kv(model, mark)

    _header("Instanz")
    _kv("Rolle", _c(cfg.role, _GREEN if cfg.is_admin() else _DIM))
    _kv("Install-Quelle", cfg.install_source)

    _header("Checks")
    _check("Hardware erkannt", bool(hw.cpu_model))
    _check("RAM ermittelt", hw.ram_mb > 0)
    _check("Profil gewählt", bool(profile.name))
    _check("Tiny-Modell lauffähig", gates.get("nexoryx-tiny", False))
    print()
    return 0


def _check(label: str, ok: bool) -> None:
    mark = _c("OK", _GREEN) if ok else _c("FEHLT", _RED)
    print(f"  [{mark}] {label}")


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"nexoryx {__version__}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    hw = detect()
    gates = model_gates(hw)
    if args.models_action == "list":
        _header("Modelle")
        for model, allowed in gates.items():
            status = "erlaubt" if allowed else "HW zu schwach"
            _kv(model, status)
        print()
        return 0
    if args.models_action == "pull":
        name = args.name
        if name not in gates:
            print(_c(f"Unbekanntes Modell: {name}", _RED))
            return 1
        if not gates[name]:
            print(_c(f"'{name}' ist auf dieser Hardware nicht erlaubt (Gate).", _YELLOW))
            return 1
        print(f"[stub] Würde '{name}' herunterladen — Download-Backend folgt in Phase 1.")
        return 0
    return 1


def cmd_ask(args: argparse.Namespace) -> int:
    print(_c("Router/Modell-Schicht noch nicht aktiv (Phase 1).", _YELLOW))
    print(f"  Frage erkannt: {args.text!r}")
    print("  In Phase 1 routet das Tiny-Brain hier zu lokal/Cloud.")
    return 0


def cmd_panic(_args: argparse.Namespace) -> int:
    print(_c("PANIC: Kill-Switch ausgelöst — alle Tasks/Agenten würden gestoppt.", _RED))
    print("  (Daemon existiert noch nicht; in Phase 3+ stoppt das laufende Agenten.)")
    return 0


# --- Admin (gated, Plan §16) ----------------------------------------------


def _require_admin() -> cfg_mod.Config | None:
    cfg = cfg_mod.load()
    if not cfg.is_admin():
        print(_c("Admin-Funktionen sind nur via Server-Install (192.168.13.100) verfügbar.", _YELLOW))
        print(_c("Diese Instanz läuft im User-Modus.", _DIM))
        return None
    return cfg


def cmd_admin(args: argparse.Namespace) -> int:
    if args.admin_action == "status":
        cfg = cfg_mod.load()
        _header("Admin-Status")
        _kv("Rolle", cfg.role)
        _kv("Install-Quelle", cfg.install_source)
        _kv("Admin aktiv", "ja" if cfg.is_admin() else "nein")
        _kv("Telegram-Admin-ID", cfg.telegram_admin_id or "—")
        print()
        return 0

    cfg = _require_admin()
    if cfg is None:
        return 1

    if args.admin_action == "profile":
        if args.value not in ("ultra_lite", "balanced", "pro"):
            print(_c("Profil muss ultra_lite|balanced|pro sein.", _RED))
            return 1
        cfg.profile = args.value
        cfg_mod.save(cfg)
        print(f"Profil-Override gesetzt: {cfg.profile}")
        return 0

    print(f"[stub] admin {args.admin_action} — Backend folgt in Phase 3–5.")
    return 0


# --- Parser ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nexoryx", description="Nexoryx — Multi-Agenten-KI-Framework")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Hardware + Profil + Checks anzeigen").set_defaults(func=cmd_doctor)
    sub.add_parser("version", help="Version anzeigen").set_defaults(func=cmd_version)

    ask = sub.add_parser("ask", help="Eine KI-Anfrage stellen")
    ask.add_argument("text", help="Die Frage")
    ask.set_defaults(func=cmd_ask)

    models = sub.add_parser("models", help="Lokale Modelle verwalten")
    msub = models.add_subparsers(dest="models_action", required=True)
    msub.add_parser("list", help="Modelle + Gates anzeigen")
    pull = msub.add_parser("pull", help="Modell herunterladen")
    pull.add_argument("name")
    models.set_defaults(func=cmd_models)

    sub.add_parser("panic", help="Kill-Switch: alle Tasks/Agenten stoppen").set_defaults(func=cmd_panic)

    admin = sub.add_parser("admin", help="Admin-Funktionen (nur Owner-Instanz)")
    asub = admin.add_subparsers(dest="admin_action", required=True)
    asub.add_parser("status", help="Admin-/Rollen-Status")
    prof = asub.add_parser("profile", help="Profil-Override setzen")
    prof.add_argument("value", help="ultra_lite|balanced|pro")
    for stub in ("keys", "budget", "user", "pair", "audit", "memory", "daemon"):
        asub.add_parser(stub, help=f"{stub} (Stub, Phase 3–5)")
    admin.set_defaults(func=cmd_admin)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
