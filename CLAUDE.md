# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State — Greenfield

This repository currently contains **only `plan.txt`** — a detailed German architecture and build plan. No code, `pyproject.toml`, or git repo exists yet. `plan.txt` is both the architecture document and the executable build plan; treat it as the spec of record. When implementing, follow the phase order in `plan.txt` §11.3 and the directory layout in §11.2.

The plan is written in German; code, comments, and identifiers should follow normal English conventions unless a section specifies otherwise.

## What Nexoryx Is

A highly modular, local+cloud multi-agent framework designed to run on very weak hardware (old CPU-only laptops) and scale up to GPU workstations **without code branches** — a single hardware-adaptive capability profile drives every layer. It self-detects hardware, auto-selects the best model (local or cloud), has a tiny "Control Brain" model for routing/intent, persists rich user context, installs via one script, and is fully remote-controllable via Telegram.

**Guiding principle — Graceful Degradation:** every component has a downward fallback (cloud → large local → small local → tiny → rules). Nexoryx must boot on a 4 GB CPU laptop and an RTX workstation alike, differing only in capability.

## Confirmed Decisions (do not relitigate)

- Deliver full architecture **and** a buildable MVP scaffold.
- **Python-centric** stack; TypeScript only for the optional web dashboard (Phase 3).
- Tiny model trained **from scratch**, bootstrapped behind a `BrainInterface` by an existing tiny model (`Qwen2.5-0.5B-Instruct` GGUF Q4 or an embedding+rule classifier) so the MVP is never blocked. Swapping = one config value.
- Cloud router is **multi-provider: Anthropic + OpenAI + Google Gemini**.
- "Nexoryx Large" is the best *local* model (open weights 32–70B + LoRA/distill, GGUF Q4), **not** a frontier-model clone; frontier quality comes from the cloud router.
- GitHub account for sync is **Benluca1**, public repo.

## Architecture (the big picture)

Layered system; each layer reads the same `profile.yaml` produced by the HW detector:

```
INTERFACES     CLI (nexoryx) · Telegram bot · Web dashboard (optional, Phase 3)
CONTROL PLANE  Tiny "Control Brain" — intent classification, routing pre-decision
ORCHESTRATION  Orchestrator + async message bus; agents Planner/Coder/Research/Debug/Tool/Memory/Security
MODEL LAYER    Model Router → provider adapters (llama.cpp/Ollama local; Anthropic/OpenAI/Gemini cloud)
MEMORY LAYER   Short / Long / Project / Semantic(vector) / Preference
TOOL LAYER     Terminal / FS / Browser / HTTP / GitHub / Docker (permission + sandbox + audit)
PLATFORM       HW detector · config/profile · telemetry · logging
```

Key cross-cutting ideas that require reading multiple sections to grasp:

- **Single long-running daemon (`nexoryxd`)** keeps models warm; CLI/Telegram/Web are thin clients over a localhost Unix socket/HTTP. One logic core, three frontends → identical behavior everywhere. The daemon binds **localhost only** (Telegram uses polling, no open port).
- **Capability profiles, not hard modes.** `platform/profile.py` scores hardware into `ultra_lite | balanced | pro`. Profiles set router weights, parallelism, allowed tools, and which models exist. On `ultra_lite` agents run strictly sequentially; `pro` runs parallel agents.
- **Everything is a plugin** — providers, tools, agents, memory backends load via an entry-point registry. Extend without touching core.
- **Event-driven** — internal async pub/sub bus with topics (`task.*`, `agent.*`, `tool.*`, `notify.*`); every action emits auditable Pydantic messages carrying a `trace_id`.
- **Model Router** scores each available model per request: `w_quality·quality_fit + w_speed·speed_fit + w_cost·cost_fit + w_context·context_fit + w_privacy·privacy_fit − penalty(unavailable|over_budget|hw_insufficient)`. Weights come from the profile. Models exceeding the HW budget (`min_ram`/`min_vram`) are **hard-excluded**, guaranteeing runnability. A per-request fallback chain (primary → secondary → local → tiny → deterministic) handles timeouts/errors/rate-limits, plus a budget guard that force-downroutes to local when cloud cost caps are hit.
- **Hardware-gated models.** Nexoryx Large is only downloaded/activated when `min_vram`/`min_ram` thresholds are met; otherwise the installer skips it and the router excludes it. On weak hardware it simply doesn't exist → no slowdown, no crash. `nexoryx models pull large` fetches it after a hardware upgrade.
- **Security is an agent, not a post-filter.** The Security agent has veto power over risky actions *before* execution, inside the orchestration graph.

## Anthropic / LLM Work

This project integrates the Anthropic SDK (`anthropic`) alongside `openai` and `google-genai` as cloud provider adapters under `src/nexoryx/router/providers/`. Per the global CLAUDE.md trigger rules, **read the `claude-api` skill before writing or modifying any Anthropic/Claude-related code** (model IDs, pricing, tool use, streaming, caching) rather than answering from memory. Default to the latest, most capable Claude models. Note the multi-provider router means OpenAI/Gemini code lives here too.

## Planned Layout (target — see plan.txt §11.2)

```
Nexoryx/
├─ pyproject.toml          # package "nexoryx"; entry points: nexoryx (CLI), nexoryxd (daemon)
├─ install.sh              # curl|bash → invokes bootstrap.py
├─ bootstrap.py            # HW analysis, venv, model pulls, API keys, Telegram setup
├─ src/nexoryx/
│  ├─ platform/  detect.py profile.py config.py logging.py
│  ├─ brain/     interface.py bootstrap_model.py  (later) tiny/
│  ├─ router/    router.py policy.py registry.py  providers/{base,local_llamacpp,ollama,anthropic,openai,gemini}.py
│  ├─ orchestrator/ bus.py orchestrator.py task.py
│  ├─ agents/    base.py planner.py coder.py research.py debug.py tool.py memory.py security.py
│  ├─ memory/    store.py vector.py layers.py ingest.py
│  ├─ tools/     base.py terminal.py filesystem.py http.py github.py docker.py sandbox.py permissions.py
│  ├─ interfaces/ cli.py  telegram/{bot,handlers,auth}.py
│  └─ daemon/    server.py
├─ training/     data_gen.py pretrain.py finetune.py distill.py export_gguf.py eval.py
│  └─ large/     base_select.py lora_finetune.py distill.py merge.py export_gguf.py eval.py
├─ web/          public/{index.html,install.html,assets/} serve.sh nexoryx-web.service
└─ tests/
```

## Build Phases (plan.txt §11.3 — implement in order)

- **Phase 0** — Foundation: `pyproject`, package skeleton, `platform.detect()` + `profile.py`, `config.py`, `nexoryx doctor`, logging. Done when `nexoryx doctor` shows the correct HW profile.
- **Phase 1** — Single-model path: `local_llamacpp` + `anthropic` adapters, minimal rule-policy router, `BrainInterface` with bootstrap model, `nexoryx ask`.
- **Phase 2** — Memory (SQLite + sqlite-vec) + auto-ingest; Terminal tool in sandbox with permission + audit.
- **Phase 3** — Multi-agent: message bus, orchestrator, Planner+Coder+Tool+Security agents; OpenAI & Gemini adapters; full score-router with fallback chain + budget guard.
- **Phase 4** — Telegram: bot as daemon client, commands, auth/roles, notifications, approve/deny gate, file upload.
- **Phase 5** — Installer + hardening: `install.sh`/`bootstrap.py` end-to-end, systemd/launchd service, profile-based model downloads, docs.
- **Parallel track A** (from week 2): Tiny model training in `training/` — only switch config to `nexoryx-tiny` when its eval gate beats the bootstrap baseline. Never blocks the MVP.
- **Parallel track B** (post-MVP): Mini/Large in `training/large/`.

## Commands (planned — none exist yet; defined by the phases above)

These come into existence as the phases are built; check the actual `pyproject.toml`/code before assuming they work.

```bash
# Install / setup
curl -fsSL <url>/install.sh | bash      # or: pipx install nexoryx
python bootstrap.py                      # HW analysis, venv, models, keys, Telegram

# CLI (Typer-based entry point `nexoryx`)
nexoryx doctor                           # self-test of all layers; smoke test
nexoryx ask "..." [--quality|--fast]     # route a request (logs show model choice + fallback)
nexoryx run <task>                       # agent task run
nexoryx models pull <tiny|mini|large>    # hardware-gated model download
nexoryx memory [query] / memory forget <query>
nexoryx panic                            # kill switch

# Daemon
nexoryxd                                 # FastAPI/asyncio daemon (binds localhost only)

# Tests
pytest                                   # unit + integration with mocked providers
pytest tests/path::test_name             # single test
pytest -k <expr>                         # subset by name

# Web docs/portal (LAN, this server is 192.168.13.100)
web/serve.sh                             # python -m http.server 3007 --bind 192.168.13.100 --directory web/public

# Git sync to github.com/Benluca1/Nexoryx
./sync.sh ["commit message"]             # idempotent: init, set remote, commit only if changes, push
```

## Conventions & Constraints

- **Tech choices (plan.txt §10):** Python 3.11+, Typer+Rich (CLI), FastAPI+uvicorn (daemon), `llama-cpp-python`+Ollama (local inference), PyTorch+`tokenizers` (tiny training), `anthropic`/`openai`/`google-genai` (cloud), **sqlite-vec** (default vector DB, → Qdrant on pro), SQLite+SQLModel/Pydantic (structured), `python-telegram-bot` async, Docker→bubblewrap/firejail (sandbox), YAML+pydantic-settings (config).
- **Secrets** live in `~/.nexoryx/secrets` (chmod 600), never in chat or logs. State (config, profile, DBs, models) lives under `~/.nexoryx/`, not in the repo.
- **`.gitignore` is a security boundary** (plan.txt §15.1): never commit `.env*`, `*.key`, `secrets/`, `~/.nexoryx/`, `models/`, `*.gguf`, `*.safetensors`, `*.bin`, `*.log`, `*.sqlite`, `*.db`. The repo is **public** — verify with `git status` before any commit that no secret or model artifact is tracked.
- **Web page vs README split:** the LAN web page (`web/`) is the "cool" distinctive dark-theme version (use the `frontend-design` skill — no generic Inter/purple-gradient AI aesthetic). The repo `README.md` is the quieter plain-Markdown version. Keep them distinct.
- Tool execution defaults: network off except for HTTP/Research tools; FS writes jailed to allowed project roots; risky actions gated by permission level (`auto | confirm | admin-only`) and append-only audit log.

## Message Schema (orchestration)

Pydantic message: `{id, parent_id, sender, recipient, type(request|response|event), payload, trace_id, ts}` — fully auditable, threaded via `parent_id`, traceable across layers via `trace_id`. Agents call agents over the bus (request → response) with recursion + per-task budget limits to prevent infinite loops.
