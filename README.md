# Nexoryx

Nexoryx ist ein hochmodulares, **lokal + cloudfähiges** Multi-Agenten-KI-System.
Es läuft auf schwacher Hardware (alte Laptops, CPU-only), erkennt die Hardware
automatisch, wählt selbst das beste Modell (lokal oder Cloud) und ist per
Terminal und Telegram steuerbar.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/Benluca1/Nexoryx/main/install.sh | bash
```

.

### Voraussetzungen
- Python 3.11+
- curl, optional git

## Erste Schritte

```bash
python3 -m nexoryx doctor      # Hardware + Profil prüfen
python3 -m nexoryx ask "Hallo" # eine Frage (ab Phase 1)
```

## Hardware-Profile

| Profil | Hardware | Modelle |
|---|---|---|
| `ultra_lite` | alte Laptops, CPU-only (~4 GB RAM) | nur kleine lokale Modelle |
| `balanced` | normale Rechner (8 GB+) | kleine + mittlere Modelle, optional Cloud |
| `pro` | starke GPU (≥24 GB VRAM) / ≥48 GB RAM | große lokale Modelle, Multi-Agent |

## Modelle

- **nexoryx-tiny** — winziges „Control Brain" für Intent & Routing (immer dabei).
- **nexoryx-mini** — lokales Allzweck-Modell (ab `balanced`).
- **nexoryx-large** — bestes lokales Modell für Coding/Reasoning (ab `pro`).

Für Spitzenqualität routet Nexoryx automatisch in die Cloud (Anthropic, OpenAI,
Google) — Keys werden bei der Installation abgefragt.

## Telegram

Optional bei der Installation einrichten (Bot-Token + Telegram-User-ID). Danach
ist Nexoryx per Chat fernsteuerbar (`/ask`, `/run`, `/status`, …).

## Status

Lauffähig (zero-dependency-Kern, Cloud/Inferenz als optionale Extras):
- **Plattform:** Hardware-Erkennung + Profil + Modell-Gates (`nexoryx doctor`)
- **Rollen/Admin-Gating:** Admin nur via Server-Install (`192.168.13.100`)
- **Router + Brain:** `nexoryx ask` — Task-Klassifikation + Score-Router über
  lokal (Ollama) und Cloud (Anthropic/OpenAI/Gemini), Fallback-Kette
- **Memory:** `nexoryx memory` — SQLite-Multi-Layer + Recall/Forget
- **Multi-Agent:** `nexoryx run` — Planner + spezialisierte Agenten + Message Bus
- **Tools/Sandbox:** `nexoryx exec` — Terminal in Sandbox, Security-Veto,
  Permission-Gate, Audit-Log
- **Daemon:** `nexoryx daemon` — HTTP-API (`/status`, `/ask`)
- **Telegram:** `nexoryx telegram` — Bot mit Befehlen + Auth/Rollen
- **Admin:** `nexoryx admin keys|telegram|user|audit|memory|pair|profile|budget`

Kompetitiver Feature-Superset (was ein moderner Agenten-Assistent können muss):
- **Agentic Tool-Use (ReAct):** `nexoryx run --auto` — das Modell wählt Tools
  autonom, der Loop führt sie abgesichert aus (Security-Veto + Permission + Audit)
- **Tools:** terminal, fs_read/fs_write, http_fetch, web_search, glob, grep, git
- **Streaming + Multi-Turn:** `nexoryx chat` (interaktiv) und `ask --stream`
- **Usage-/Kosten-Tracking + Budget-Guard:** `nexoryx usage`, `admin budget`
  (Downrouting auf lokal bei überschrittenem Tages-Cap)
- **Config + Personas:** `nexoryx config get|set`, globaler System-Prompt
- **Plugins:** `~/.nexoryx/plugins/*.py` registrieren eigene Tools automatisch
- **Daemon-API** als gemeinsamer Kern für CLI/Telegram/Web





