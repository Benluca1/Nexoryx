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
    import subprocess
    from .training import recommended_base
    hw = detect()
    profile = choose_profile(hw)
    gates = model_gates(hw)

    if args.models_action == "recommend":
        base = recommended_base(profile, hw)
        _header("Empfohlenes Start-Modell (hardware-basiert)")
        _kv("Profil", profile.name)
        _kv("Ollama-Tag", base["ollama"])
        _kv("HuggingFace", base["hf"])
        _kv("Hinweis", base["note"])
        print(_c("\n  Ziehen mit:  nexoryx models pull house", _DIM))
        return 0

    if args.models_action == "list":
        _header("Modell-Gates (eigene Familie)")
        for model, allowed in gates.items():
            _kv(model, "erlaubt" if allowed else "HW zu schwach")
        from .router import available_models
        _header("Aktuell verfügbar (Router)")
        for spec, prov in available_models():
            _kv(spec.name, f"{prov.name} ({'lokal' if spec.is_local else 'cloud'})")
        print()
        return 0

    if args.models_action == "pull":
        name = args.name
        if name == "house":
            base = recommended_base(profile, hw)
            tag = base["ollama"]
            if not shutil_which("ollama"):
                print(_c("Ollama nicht gefunden. Installiere Ollama, dann erneut.", _YELLOW))
                print(f"  Manuell:  ollama pull {tag}")
                return 1
            print(f"→ ziehe Start-Modell {tag} via Ollama …")
            rc = subprocess.run(["ollama", "pull", tag]).returncode
            if rc == 0:
                cfg = cfg_mod.load(); cfg.house_base = tag; cfg_mod.save(cfg)
                print(f"✓ House-Base gesetzt: {tag}")
            return rc
        print(f"[stub] '{name}': eigenes Modell-Training via 'nexoryx train'.")
        return 0
    return 1


def shutil_which(cmd: str):
    import shutil
    return shutil.which(cmd)


def cmd_train(args: argparse.Namespace) -> int:
    import os
    from .training import train, train_report, export_chatml
    if args.train_action == "status":
        r = train_report()
        st = r["dataset"]
        _header("Flywheel / House-Model")
        _kv("Gesammelte Beispiele", str(st["total"]))
        _kv("davon Teacher (Cloud)", str(st["teacher"]))
        _kv("Quellen", ", ".join(f"{k}:{v}" for k, v in st["by_provider"].items()) or "—")
        _kv("House-Base", r["house_base"])
        _kv("Eigenes trainiert", "ja v%d" % r["house_version"] if r["house_trained"] else "nein")
        _kv("Trainings-Deps fehlen", ", ".join(r["deps_missing"]) or "keine")
        _kv("Bereit zum Training", "ja" if r["ready"] else "nein (mehr Daten sammeln)")
        print()
        return 0
    if args.train_action == "export":
        n = export_chatml(args.path, teacher_only=args.teacher_only)
        print(f"{n} Beispiele exportiert → {args.path}")
        return 0
    # run
    from pathlib import Path
    rep = train(repo_root=Path(os.getcwd()) / "training")
    _header("Training")
    if rep["action"] == "skipped":
        print(_c(rep["reason"], _YELLOW))
    elif rep["action"] == "script_generated":
        print(f"Datensatz exportiert: {rep['exported']['lines']} Zeilen → {rep['exported']['path']}")
        print(f"Trainings-Skript erzeugt: {rep['script']}")
        print(_c("\nNächster Schritt (GPU empfohlen):", _BOLD))
        print(f"  {rep['instructions']}")
    elif rep["action"] == "trained":
        print(_c(f"✓ Eigenes Modell trainiert (v{rep['house_version']}).", _GREEN))
    else:
        print(_c(f"Fehler: {rep.get('error','?')}", _RED))
    return 0



def cmd_panic(_args: argparse.Namespace) -> int:
    print(_c("PANIC: Kill-Switch ausgelöst — alle Tasks/Agenten würden gestoppt.", _RED))
    print("  (Daemon existiert noch nicht; in Phase 3+ stoppt das laufende Agenten.)")
    return 0


# --- Orchestrierung / Tools / Memory / Interfaces -------------------------


def _orchestrator():
    from .memory import MemoryStore
    from .orchestrator import Orchestrator
    hw = detect()
    return Orchestrator(hw, choose_profile(hw), memory=MemoryStore())


def cmd_run(args: argparse.Namespace) -> int:
    import os
    from .tools import ToolContext
    orch = _orchestrator()
    if args.auto:
        cfg = cfg_mod.load()

        def confirm(tool, reason) -> bool:
            ans = input(_c(f"{reason} — ausführen? [y/N] ", _YELLOW)).strip().lower()
            return ans in ("y", "j", "yes", "ja")

        ctx = ToolContext(role=cfg.role, project_root=os.getcwd(), actor="cli",
                          auto_approve=cfg.is_admin())

        def on_step(name, a):
            print(_c(f"  → {name} {a}", _DIM))

        res = orch.agentic_run(args.task, ctx, confirm_cb=confirm, on_step=on_step)
        _header("Ergebnis")
        print(res.answer.rstrip())
        print(_c(f"\n— {len(res.steps)} Tool-Schritte: {', '.join(res.steps)}", _DIM))
        return 0
    res = orch.run(args.task, project=os.getcwd(), plan=not args.no_plan, fast=args.fast)
    if res.plan:
        _header("Plan")
        print(res.plan)
    _header("Antwort")
    print(res.answer.rstrip())
    print(_c(f"\n— agent={res.model} (task={res.task_type})", _DIM))
    return 0


def cmd_chat(_args: argparse.Namespace) -> int:
    """Interaktiver Multi-Turn-Chat mit Memory + Streaming."""
    from .brain import classify
    from .router import ChatRequest, Router, ProviderError
    from .memory import MemoryStore
    hw = detect()
    router = Router(hw, choose_profile(hw))
    mem = MemoryStore()
    cfg = cfg_mod.load()
    history: list[str] = []
    print(_c("Nexoryx Chat — 'exit' zum Beenden.", _BOLD))
    while True:
        try:
            user = input(_c("\nDu: ", _GREEN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user.lower() in ("exit", "quit", ":q"):
            break
        if not user:
            continue
        brain = classify(user)
        ctx = mem.recall(user, limit=3)
        ctx_text = "\n".join(f"- {m.text}" for m in ctx)
        convo = "\n".join(history[-6:])
        prompt = (f"Bisheriger Verlauf:\n{convo}\n\n" if convo else "") + \
                 (f"Erinnerungen:\n{ctx_text}\n\n" if ctx_text else "") + f"User: {user}"
        system = "Du bist Nexoryx, ein hilfsbereiter Assistent." + (
            f" {cfg.persona}" if cfg.persona else "")
        print(_c("Nexoryx: ", _BOLD), end="", flush=True)
        parts: list[str] = []
        try:
            for chunk in router.stream(ChatRequest(prompt=prompt, system=system, task_type=brain.task_type)):
                parts.append(chunk)
                print(chunk, end="", flush=True)
            print()
        except ProviderError as exc:
            print(_c(f"Fehler: {exc}", _RED))
            continue
        answer = "".join(parts).strip()
        history.append(f"User: {user}")
        history.append(f"Nexoryx: {answer[:300]}")
        mem.remember(f"Chat: {user} → {answer[:200]}", scope="long")
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    """Einfaches Key-Management ohne Admin-Gate.

    Jedes Gerät kann damit seinen GitHub-PAT (und Cloud-Keys) setzen,
    damit Training-Uploads und API-Calls funktionieren.
    """
    _KEY_MAP = {
        "github":    ("GITHUB_PAT",        "github.com/settings/tokens → Classic Token, Scope: repo"),
        "anthropic": ("ANTHROPIC_API_KEY", "console.anthropic.com → API Keys"),
        "openai":    ("OPENAI_API_KEY",    "platform.openai.com → API Keys"),
        "gemini":    ("GEMINI_API_KEY",    "aistudio.google.com → API Key"),
    }

    if args.keys_action == "list":
        _header("API-Keys & GitHub-PAT")
        for name, (env, hint) in _KEY_MAP.items():
            val = cfg_mod.get_key(env)
            status = _c("gesetzt", _GREEN) if val else _c("—", _DIM)
            _kv(name, f"{status}  [dim]{hint}[/dim]" if not val else status)
        print()
        _header("Training-Upload Status")
        from .training.on_exit import PAT_FILE, _device_id
        _kv("Gerät", _device_id())
        _kv("PAT-Datei", str(PAT_FILE))
        _kv("Upload aktiv", _c("ja", _GREEN) if PAT_FILE.exists() else _c("nein (kein PAT)", _YELLOW))
        print()
        return 0

    if args.keys_action == "set":
        import getpass
        name = args.provider.lower()
        if name not in _KEY_MAP:
            print(_c(f"Unbekannt: {name}. Verfügbar: {', '.join(_KEY_MAP)}", _RED))
            return 1
        env, hint = _KEY_MAP[name]
        print(f"  {_c(hint, _DIM)}")

        # GitHub-PAT: direkt in ~/.nexoryx/secrets/github_pat speichern
        if name == "github":
            value = getpass.getpass(f"GitHub PAT (verborgen): ").strip()
            if not value:
                print(_c("Abgebrochen.", _YELLOW)); return 1
            from .platform.config import CONFIG_DIR
            pat_dir = CONFIG_DIR / "secrets"
            pat_dir.mkdir(parents=True, exist_ok=True)
            pat_file = pat_dir / "github_pat"
            pat_file.write_text(value, encoding="utf-8")
            import os as _os; _os.chmod(pat_file, 0o600)
            print(_c(f"✓ GitHub-PAT gespeichert ({pat_file})", _GREEN))
            print(_c("  Training-Uploads werden jetzt von diesem Gerät hochgeladen.", _DIM))
            return 0

        value = getpass.getpass(f"{env} (verborgen): ").strip()
        if not value:
            print(_c("Abgebrochen.", _YELLOW)); return 1
        cfg_mod.set_secret(env, value)
        print(_c(f"✓ {env} gespeichert.", _GREEN))
        return 0

    return 1


def cmd_usage(_args: argparse.Namespace) -> int:
    from .platform import usage as usage_mod
    t = usage_mod.today()
    _header("Cloud-Verbrauch heute")
    _kv("Requests", str(t.get("requests", 0)))
    _kv("Tokens in/out", f"{t.get('in_tok', 0)} / {t.get('out_tok', 0)}")
    _kv("Kosten", f"${t.get('cost', 0.0):.4f}")
    cap = cfg_mod.load().daily_budget
    _kv("Budget-Cap", f"${cap:.2f}/Tag" if cap else "unbegrenzt")
    for model, m in t.get("by_model", {}).items():
        _kv(model, f"{m['requests']}× / ${m['cost']:.4f}")
    print()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = cfg_mod.load()
    if args.config_action == "get":
        from dataclasses import asdict
        data = asdict(cfg)
        if args.key:
            print(data.get(args.key, "(unbekannt)"))
        else:
            for k, v in data.items():
                if k not in ("telegram_allowlist",):
                    _kv(k, str(v))
        return 0
    # set
    field_name, value = args.key, args.value
    if not hasattr(cfg, field_name):
        print(_c(f"Unbekannter Schlüssel: {field_name}", _RED))
        return 1
    cur = getattr(cfg, field_name)
    try:
        casted = type(cur)(value) if not isinstance(cur, bool) else value.lower() in ("1", "true", "ja", "yes")
    except (ValueError, TypeError):
        casted = value
    setattr(cfg, field_name, casted)
    cfg_mod.save(cfg)
    print(f"{field_name} = {casted}")
    return 0


def cmd_tools(_args: argparse.Namespace) -> int:
    from .tools import list_tools
    from .tools.registry import load_plugins
    plugins = load_plugins()
    _header("Tools")
    for t in list_tools():
        _kv(t.name, f"[{t.permission}] {t.description}")
    if plugins:
        print(_c(f"  Plugins geladen: {', '.join(plugins)}", _DIM))
    print()
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    import os
    from .tools import ToolContext
    cfg = cfg_mod.load()
    orch = _orchestrator()

    def confirm(tool, reason) -> bool:
        ans = input(_c(f"{reason} — ausführen? [y/N] ", _YELLOW)).strip().lower()
        return ans in ("y", "j", "yes", "ja")

    ctx = ToolContext(role=cfg.role, project_root=os.getcwd(),
                      actor="cli", auto_approve=cfg.is_admin())
    result = orch.exec_command(args.command, ctx, confirm_cb=confirm)
    if result.output:
        print(result.output.rstrip())
    if result.error:
        print(_c(result.error.rstrip(), _RED))
    print(_c(f"\n[{'ok' if result.ok else 'fehler'}] sandbox={result.meta.get('sandbox','-')}", _DIM))
    return 0 if result.ok else 1


def cmd_memory(args: argparse.Namespace) -> int:
    from .memory import MemoryStore
    mem = MemoryStore()
    if args.memory_action == "remember":
        mem.remember(args.text, scope="long", importance=2.0)
        print("Gemerkt.")
    elif args.memory_action == "search":
        hits = mem.recall(args.query, limit=10)
        for m in hits:
            print(f"  • {m.text[:160]}")
        if not hits:
            print("  (nichts gefunden)")
    elif args.memory_action == "forget":
        n = mem.forget(args.query)
        print(f"{n} Einträge gelöscht.")
    else:  # list
        for m in mem.recent(15):
            print(f"  • [{m.scope}] {m.text[:140]}")
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    import os
    from .memory import MemoryStore
    mem = MemoryStore()
    if args.project_action == "list":
        rows = mem.db.execute(
            "SELECT DISTINCT project FROM memories WHERE project!=''"
        ).fetchall()
        _header("Projekte")
        for r in rows:
            print(f"  {r['project']}")
        if not rows:
            print("  (keine projekt-spezifischen Erinnerungen)")
    else:  # info
        cwd = os.getcwd()
        cnt = mem.db.execute("SELECT COUNT(*) c FROM memories WHERE project=?", (cwd,)).fetchone()["c"]
        _header("Projekt")
        _kv("Pfad", cwd)
        _kv("Erinnerungen", str(cnt))
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from .agents import AGENTS
    _header("Agenten")
    for name, agent in AGENTS.items():
        _kv(name, agent.system.split(".")[0])
    print(f"  {_c('security', _DIM)}  Veto-Prüfung vor Tool-Ausführung")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    from .daemon import serve
    serve(host=args.host, port=args.port)
    return 0


def cmd_telegram(_args: argparse.Namespace) -> int:
    from .interfaces.telegram import run_bot
    return run_bot()


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

    if args.admin_action == "keys":
        _KEY_NAMES = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "github": "GITHUB_PAT",
        }
        if args.keys_action == "list":
            _header("API-Keys")
            for provider, env in _KEY_NAMES.items():
                status = "gesetzt" if cfg_mod.get_key(env) else "—"
                _kv(provider, _c(status, _GREEN if status == "gesetzt" else _DIM))
            print()
            return 0
        if args.keys_action == "set":
            env = _KEY_NAMES.get(args.provider)
            if not env:
                print(_c(f"Unbekannter Provider: {args.provider}", _RED))
                return 1
            import getpass
            value = getpass.getpass(f"{env} (Eingabe verborgen): ").strip()
            if not value:
                print(_c("Kein Wert eingegeben — abgebrochen.", _YELLOW))
                return 1
            cfg_mod.set_secret(env, value)
            print(f"{env} gespeichert in {cfg_mod.SECRETS_PATH} (chmod 600).")
            return 0
        return 1

    if args.admin_action == "telegram":
        import getpass
        token = getpass.getpass("TELEGRAM_BOT_TOKEN (verborgen): ").strip()
        if token:
            cfg_mod.set_secret("TELEGRAM_BOT_TOKEN", token)
        admin_id = input("Deine Telegram-User-ID (admin): ").strip()
        if admin_id:
            cfg.telegram_admin_id = admin_id
            cfg_mod.save(cfg)
        print("Telegram konfiguriert. Start:  nexoryx telegram")
        return 0

    if args.admin_action == "user":
        if args.user_action == "add" or args.user_action == "role":
            cfg.telegram_allowlist[str(args.user_id)] = args.role
            cfg_mod.save(cfg)
            print(f"{args.user_id} → {args.role}")
        elif args.user_action == "rm":
            cfg.telegram_allowlist.pop(str(args.user_id), None)
            cfg_mod.save(cfg)
            print(f"{args.user_id} entfernt")
        return 0

    if args.admin_action == "budget":
        cfg.daily_budget = float(args.amount)
        cfg_mod.save(cfg)
        print(f"Tages-Budget-Cap gesetzt: ${cfg.daily_budget:.2f}")
        return 0

    if args.admin_action == "pair":
        import secrets as _s
        code = _s.token_hex(3).upper()
        print(f"Pairing-Code: {code}\n(Im Bot mit /pair {code} koppeln — Feature folgt.)")
        return 0

    if args.admin_action == "audit":
        from .tools.audit import tail
        _header("Audit-Log (letzte 15)")
        for r in tail(15):
            print(f"  {r.get('event'):<14} {r.get('tool','')} "
                  f"{'ok' if r.get('ok') else ''} {r.get('actor','')}")
        return 0

    if args.admin_action == "memory":
        from .memory import MemoryStore
        mem = MemoryStore()
        if getattr(args, "mem_query", None):
            n = mem.forget(args.mem_query)
            print(f"{n} Einträge gelöscht.")
        else:
            for m in mem.recent(15):
                print(f"  • [{m.scope}] {m.text[:140]}")
        return 0

    print(f"[stub] admin {args.admin_action} — Backend folgt.")
    return 0


# --- Parser ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nexoryx", description="Nexoryx — Multi-Agenten-KI-Framework")
    sub = p.add_subparsers(dest="command", required=False)

    sub.add_parser("doctor", help="Hardware + Profil + Checks anzeigen").set_defaults(func=cmd_doctor)
    sub.add_parser("version", help="Version anzeigen").set_defaults(func=cmd_version)

    models = sub.add_parser("models", help="Lokale Modelle verwalten")
    msub = models.add_subparsers(dest="models_action", required=True)
    msub.add_parser("list", help="Modelle + Gates + verfügbare anzeigen")
    msub.add_parser("recommend", help="hardware-empfohlenes Start-Modell")
    pull = msub.add_parser("pull", help="Modell ziehen ('house' = Start-Modell)")
    pull.add_argument("name")
    models.set_defaults(func=cmd_models)

    train = sub.add_parser("train", help="Eigenes Modell aus gesammelten Daten trainieren")
    tsub = train.add_subparsers(dest="train_action", required=True)
    tsub.add_parser("status", help="Flywheel-/Datensatz-Status")
    tsub.add_parser("run", help="Training auslösen (oder Skript erzeugen)")
    te = tsub.add_parser("export", help="Datensatz als ChatML exportieren")
    te.add_argument("path")
    te.add_argument("--teacher-only", action="store_true", help="nur Cloud-Beispiele")
    train.set_defaults(func=cmd_train)

    sub.add_parser("panic", help="Kill-Switch: alle Tasks/Agenten stoppen").set_defaults(func=cmd_panic)

    run = sub.add_parser("run", help="Aufgabe über Orchestrator (Planner+Lead)")
    run.add_argument("task")
    run.add_argument("--no-plan", action="store_true", help="ohne Planner-Schritt")
    run.add_argument("--auto", action="store_true", help="Agentic Tool-Use-Loop (ReAct)")
    run.add_argument("--fast", action="store_true")
    run.set_defaults(func=cmd_run)

    sub.add_parser("chat", help="Interaktiver Multi-Turn-Chat (Streaming)").set_defaults(func=cmd_chat)
    sub.add_parser("usage", help="Cloud-Verbrauch + Budget anzeigen").set_defaults(func=cmd_usage)
    sub.add_parser("tools", help="Verfügbare Tools (inkl. Plugins) auflisten").set_defaults(func=cmd_tools)

    conf = sub.add_parser("config", help="Konfiguration lesen/setzen")
    csub = conf.add_subparsers(dest="config_action", required=True)
    cg = csub.add_parser("get"); cg.add_argument("key", nargs="?", default="")
    cs = csub.add_parser("set"); cs.add_argument("key"); cs.add_argument("value")
    conf.set_defaults(func=cmd_config)

    ex = sub.add_parser("exec", help="Shell-Kommando in Sandbox (Security+Permission+Audit)")
    ex.add_argument("command")
    ex.set_defaults(func=cmd_exec)

    mem = sub.add_parser("memory", help="Speicher anzeigen/suchen/löschen")
    msub = mem.add_subparsers(dest="memory_action", required=True)
    msub.add_parser("list", help="letzte Einträge")
    ms = msub.add_parser("search", help="suchen"); ms.add_argument("query")
    mf = msub.add_parser("forget", help="löschen"); mf.add_argument("query")
    mr = msub.add_parser("remember", help="Fakt merken"); mr.add_argument("text")
    mem.set_defaults(func=cmd_memory)

    proj = sub.add_parser("project", help="Projektverwaltung")
    psub = proj.add_subparsers(dest="project_action", required=True)
    psub.add_parser("info", help="aktuelles Projekt (cwd)")
    psub.add_parser("list", help="bekannte Projekte")
    proj.set_defaults(func=cmd_project)

    ag = sub.add_parser("agent", help="Agenten auflisten")
    asub2 = ag.add_subparsers(dest="agent_action", required=False)
    asub2.add_parser("list")
    ag.set_defaults(func=cmd_agent)

    dmn = sub.add_parser("daemon", help="HTTP-Daemon (nexoryxd) starten")
    dmn.add_argument("--host", default="127.0.0.1")
    dmn.add_argument("--port", type=int, default=3008)
    dmn.set_defaults(func=cmd_daemon)

    sub.add_parser("telegram", help="Telegram-Bot starten").set_defaults(func=cmd_telegram)

    # keys — für alle Geräte, kein Admin-Gate
    keys_top = sub.add_parser("keys", help="API-Keys + GitHub-PAT verwalten (alle Geräte)")
    ksub_top = keys_top.add_subparsers(dest="keys_action", required=True)
    ksub_top.add_parser("list", help="Keys-Status anzeigen")
    kset_top = ksub_top.add_parser("set", help="Key setzen")
    kset_top.add_argument("provider", help="github|anthropic|openai|gemini")
    keys_top.set_defaults(func=cmd_keys)

    admin = sub.add_parser("admin", help="Admin-Funktionen (nur Owner-Instanz)")
    asub = admin.add_subparsers(dest="admin_action", required=True)
    asub.add_parser("status", help="Admin-/Rollen-Status")
    prof = asub.add_parser("profile", help="Profil-Override setzen")
    prof.add_argument("value", help="ultra_lite|balanced|pro")
    keys = asub.add_parser("keys", help="Cloud-API-Keys verwalten")
    ksub = keys.add_subparsers(dest="keys_action", required=True)
    ksub.add_parser("list", help="Keys-Status anzeigen")
    kset = ksub.add_parser("set", help="Key setzen")
    kset.add_argument("provider", help="anthropic|openai|gemini")
    asub.add_parser("telegram", help="Telegram Bot-Token + Admin-ID setzen")
    asub.add_parser("pair", help="Pairing-Code erzeugen")
    asub.add_parser("audit", help="Audit-Log anzeigen")
    user = asub.add_parser("user", help="Telegram-Allowlist/Rollen verwalten")
    usub = user.add_subparsers(dest="user_action", required=True)
    ua = usub.add_parser("add"); ua.add_argument("user_id"); ua.add_argument("role")
    ur = usub.add_parser("rm"); ur.add_argument("user_id")
    uo = usub.add_parser("role"); uo.add_argument("user_id"); uo.add_argument("role")
    amem = asub.add_parser("memory", help="Speicher anzeigen / gezielt löschen")
    amem.add_argument("mem_query", nargs="?", default="")
    abud = asub.add_parser("budget", help="Tages-Budget-Cap (USD) setzen")
    abud.add_argument("amount", type=float)
    admin.set_defaults(func=cmd_admin)

    return p


def main(argv: list[str] | None = None) -> int:
    # Hintergrund-Malware-Scan: Befunde des letzten Scans zeigen, neuen starten.
    try:
        from .platform.scanner import check_pending, start_background_scan
        check_pending()
        start_background_scan()
    except Exception:
        pass

    # Plugins früh laden, damit ihre Tools überall registriert sind.
    try:
        from .tools.registry import load_plugins
        load_plugins()
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        from .interfaces.tui import run as _tui
        return _tui()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
