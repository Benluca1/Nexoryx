# Nexoryx

Nexoryx ist ein hochmodulares, **lokal + cloudfähiges** Multi-Agenten-KI-System.
Es läuft auf schwacher Hardware (alte Laptops, CPU-only), erkennt die Hardware
automatisch, wählt selbst das beste Modell (lokal oder Cloud) und ist per
Terminal und Telegram steuerbar.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/Benluca1/Nexoryx/main/install.sh | bash
```

> Diese öffentliche Installation läuft im **User-Modus** (ohne Admin-Funktionen).
> Admin-Funktionen gibt es nur bei Installation über den Heim-Server
> (`http://192.168.13.100:3007`).

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

Frühe Entwicklung. Lauffähig sind aktuell: Hardware-Erkennung, Profil-Auswahl,
`nexoryx doctor` und das Rollen-/Admin-Gating. Router, Modelle, Agenten, Daemon
und Telegram folgen gemäß Entwicklungsplan.

## Lizenz

MIT. Öffentliches Repo — bitte keine Secrets committen (siehe `.gitignore`).
