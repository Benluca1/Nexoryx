"""Function-Calling Agentic Runner.

Nutzt Olamas OpenAI-kompatible API (openclaw) + hermes3 für native Tool-Calls.
Zuverlässiger als text-basiertes ReAct-Parsing — das Modell gibt strukturierte
Tool-Calls zurück, kein Parsing nötig.
"""
from __future__ import annotations

import json
import os
from typing import Callable

_OLLAMA_BASE = "http://localhost:11434/v1"

# Modell-Präferenz: hermes3 → nous-hermes2 → qwen2.5:latest → fallback
_FC_MODELS = ["hermes3", "nous-hermes2", "qwen2.5:latest", "qwen2.5:0.5b"]

_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": (
                "Führt ein Shell-Kommando auf dem PC des Nutzers aus. "
                "Für alles was den PC betrifft: Ordner/Dateien anlegen, "
                "Programme öffnen (xdg-open), Dateien kopieren/verschieben/löschen, "
                "Systeminfos abfragen, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Bash-Kommando. Nutze ~ für Home-Verzeichnis."
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": "Schreibt Text-Inhalt in eine Datei (erstellt/überschreibt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Dateipfad (absolut oder mit ~)"},
                    "content": {"type": "string", "description": "Dateiinhalt"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "Liest den Inhalt einer Datei.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Sucht im Internet nach aktuellen Informationen.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def available_model() -> str | None:
    """Gibt das beste verfügbare Function-Calling-Modell zurück oder None.

    Gibt den exakten installierten Modell-Namen zurück (z. B. 'qwen2.5:0.5b'),
    bevorzugt Modelle aus _FC_MODELS nach Qualität.
    """
    try:
        import ollama as _ol
        installed: list[str] = [m.model for m in _ol.list().models]
    except Exception:
        try:
            import httpx
            r = httpx.get(f"{_OLLAMA_BASE.replace('/v1', '')}/api/tags", timeout=2)
            installed = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return None

    if not installed:
        return None

    # Prüfe Präferenz-Liste zuerst (exakter Match oder Tag-Prefix-Match)
    for preferred in _FC_MODELS:
        # Exakter Match
        if preferred in installed:
            return preferred
        # Prefix-Match: 'qwen2.5' matcht 'qwen2.5:0.5b'
        prefix = preferred.split(":")[0]
        for name in installed:
            if name.split(":")[0] == prefix:
                return name  # echten installierten Namen zurückgeben

    # Irgendein verfügbares Modell als letzter Ausweg
    return installed[0]


def run_fc(
    task: str,
    ctx,
    confirm_cb: Callable | None = None,
    on_step: Callable | None = None,
    max_steps: int = 10,
    model: str | None = None,
    personality: dict | None = None,
    system_suffix: str = "",
) -> tuple[str, list[str]]:
    """Function-Calling Agentic Loop.

    Gibt (antwort, schritte) zurück.
    Wirft RuntimeError wenn kein FC-fähiges Modell verfügbar ist.
    """
    from ..tools.registry import run_tool, get_tool
    from ..agents.security import security_veto

    fc_model = model or available_model()
    if fc_model is None:
        raise RuntimeError("Kein Function-Calling-Modell verfügbar (hermes3 empfohlen).")

    from openai import OpenAI
    client = OpenAI(base_url=_OLLAMA_BASE, api_key="ollama")

    home = os.path.expanduser("~")

    # Persona-Kontext laden
    try:
        from ..memory.persona import get_context as _persona_ctx
        persona = _persona_ctx()
    except Exception:
        persona = ""

    if personality and personality.get("system_prompt"):
        base_system = personality["system_prompt"]
    else:
        base_system = (
            "Du bist Nexoryx, ein KI-Assistent der den PC des Nutzers direkt steuert. "
            "Antworte auf Deutsch. Bestätige kurz was du getan hast."
        )

    system = (
        f"{base_system}\n"
        f"Home-Verzeichnis: {home}\n"
        + (f"\n{persona}\n" if persona else "")
        + "Nutze die verfügbaren Tools um Aufgaben direkt auszuführen."
        + (f"\n\n{system_suffix}" if system_suffix else "")
    )

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    steps: list[str] = []

    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=fc_model,
            messages=messages,
            tools=_TOOL_DEFS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        # Kein Tool-Call → fertig
        if not msg.tool_calls:
            answer = (msg.content or "Erledigt.").strip()
            # Trainingsdaten aufzeichnen
            try:
                from ..training.dataset import record_interaction
                record_interaction(
                    prompt=task, system=system, response=answer,
                    provider="ollama", model=fc_model,
                    task_type="chat", is_local=True,
                )
            except Exception:
                pass
            return answer, steps

        messages.append({"role": "assistant",
                         "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}

            # Pfade expandieren
            if "path" in args:
                args["path"] = os.path.expanduser(args["path"])
            if "command" in args:
                args["command"] = args["command"].replace("~", home)

            if on_step:
                on_step(name, args)

            # Security-Veto
            if name == "terminal":
                veto = security_veto(args.get("command", ""))
                if veto:
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": f"Blockiert: {veto}"})
                    steps.append(f"{name} → veto")
                    continue

            # Confirmation gate
            tool_obj = get_tool(name)
            if tool_obj and tool_obj.permission == "confirm" and not ctx.auto_approve:
                approved = confirm_cb(tool_obj, args) if confirm_cb else False
                if not approved:
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": "Vom Nutzer abgelehnt."})
                    steps.append(f"{name} → abgelehnt")
                    continue

            result = run_tool(name, args, ctx)
            out = (result.output or result.error or "(leer)")[:2000]
            steps.append(f"{name} → {'ok' if result.ok else 'fehler'}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    return "Maximale Schritte erreicht.", steps
