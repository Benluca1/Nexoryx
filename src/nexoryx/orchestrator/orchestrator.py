"""Orchestrator — koordiniert Brain, Memory, Agenten, Router, Tools (Plan §6.2).

run(task): Memory-Recall → Planner → Lead-Antwort (mit Kontext) → Memory-Ingest,
Events auf den Bus. Optionale Tool-Schritte über den geprüften Pfad (Security-
Veto + Permission + Sandbox + Audit).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.base import AGENTS
from ..agents.security import security_veto
from ..brain import classify
from ..memory import MemoryStore
from ..platform import Hardware, Profile
from ..router import Router
from ..tools import ToolContext
from ..tools.registry import run_tool
from .bus import Bus


@dataclass
class TaskResult:
    answer: str
    plan: str = ""
    task_type: str = "chat"
    model: str = ""
    steps: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, hw: Hardware, profile: Profile,
                 memory: MemoryStore | None = None, bus: Bus | None = None) -> None:
        self.router = Router(hw, profile)
        self.profile = profile
        self.memory = memory
        self.bus = bus or Bus()

    def _context(self, query: str, project: str) -> str:
        if not self.memory:
            return ""
        hits = self.memory.recall(query, project=project, limit=4)
        prefs = self.memory.preferences()
        parts = []
        if prefs:
            parts.append("Bekannte Präferenzen: " + "; ".join(f"{k}={v}" for k, v in prefs.items()))
        if hits:
            parts.append("Relevante Erinnerungen:\n" + "\n".join(f"- {m.text}" for m in hits))
        return "\n".join(parts)

    def run(self, task: str, project: str = "", plan: bool = True,
            fast: bool = False) -> TaskResult:
        self.bus.publish("task.start", task=task)
        brain = classify(task)
        ctx = self._context(task, project)

        plan_text = ""
        if plan and self.profile.multi_agent and not brain.trivial:
            self.bus.publish("agent.planner", task=task)
            plan_text = AGENTS["planner"].act(self.router, task, prefer_fast=True, max_tokens=400)

        lead = AGENTS.get(brain.task_type, AGENTS["coder"] if brain.task_type == "coding"
                          else AGENTS["research"])
        lead_name = lead.name if brain.task_type in AGENTS else "research"
        prompt = task if not ctx else f"{ctx}\n\nAufgabe: {task}"
        self.bus.publish("agent.lead", agent=lead_name, task_type=brain.task_type)
        answer = lead.act(self.router, prompt, prefer_fast=fast)

        if self.memory:
            self.memory.remember(f"F: {task}\nA: {answer[:400]}", scope="long", project=project)

        self.bus.publish("task.done", task_type=brain.task_type)
        return TaskResult(answer=answer, plan=plan_text, task_type=brain.task_type,
                          model=lead_name)

    def exec_command(self, command: str, ctx: ToolContext,
                     confirm_cb=None):
        """Shell-Kommando über den vollen, geprüften Tool-Pfad ausführen."""
        veto = security_veto(command)
        if veto:
            self.bus.publish("tool.veto", command=command, reason=veto)
            from ..tools import ToolResult
            return ToolResult(False, "", veto)
        self.bus.publish("tool.exec", command=command, actor=ctx.actor)
        return run_tool("terminal", {"command": command}, ctx, confirm_cb=confirm_cb)

    # --- Agentic ReAct-Loop (Tool-Use) ------------------------------------

    def agentic_run(self, task: str, ctx: ToolContext, confirm_cb=None,
                    max_steps: int = 6, on_step=None) -> TaskResult:
        """Echter Agenten-Loop: das Modell wählt Tools, der Loop führt sie
        abgesichert aus (Security-Veto + Permission + Audit) und gibt die
        Beobachtung zurück, bis FINAL erreicht ist oder das Budget aus ist."""
        import json as _json
        from ..tools.registry import list_tools, run_tool

        tools = list_tools()
        tool_doc = "\n".join(f"- {t.name}: {t.description}" for t in tools)
        system = (
            "Du bist ein Nexoryx-Agent mit Werkzeugen. Arbeite in Schritten.\n"
            "Wenn du ein Werkzeug brauchst, antworte mit GENAU EINER Zeile:\n"
            '  ACTION: <tool> <json-args>\n'
            "Beispiele:\n"
            '  ACTION: web_search {"query": "Wetter Berlin"}\n'
            '  ACTION: terminal {"command": "ls -la"}\n'
            "Wenn du fertig bist, antworte mit:\n"
            "  FINAL: <deine Antwort>\n\n"
            f"Verfügbare Werkzeuge:\n{tool_doc}"
        )
        steps: list[str] = []
        transcript = f"Aufgabe: {task}"
        for _ in range(max_steps):
            req = ChatRequest(prompt=transcript, system=system,
                              task_type="reasoning", max_tokens=700)
            out = self.router.route(req).text.strip()
            action = self._parse_action(out)
            if action is None:
                answer = out.split("FINAL:", 1)[-1].strip() if "FINAL:" in out else out
                if self.memory:
                    self.memory.remember(f"Agent-Task: {task}\n→ {answer[:300]}", scope="long")
                return TaskResult(answer=answer, task_type="agentic", steps=steps)

            name, args = action
            if on_step:
                on_step(name, args)
            if name == "terminal":
                veto = security_veto(args.get("command", ""))
                if veto:
                    obs = veto
                    self.bus.publish("tool.veto", command=args.get("command"), reason=veto)
                    steps.append(f"{name} → VETO")
                    transcript += f"\nACTION: {name} {_json.dumps(args)}\nOBSERVATION: {obs}"
                    continue
            self.bus.publish("agent.tool", tool=name, args=args)
            result = run_tool(name, args, ctx, confirm_cb=confirm_cb)
            obs = (result.output or result.error or "(keine Ausgabe)")[:2000]
            steps.append(f"{name} → {'ok' if result.ok else 'fehler'}")
            transcript += f"\nACTION: {name} {_json.dumps(args)}\nOBSERVATION: {obs}"

        # Budget/Schritte erschöpft → letzte Zusammenfassung
        final = self.router.route(ChatRequest(
            prompt=transcript + "\n\nFasse das Ergebnis zusammen (FINAL).",
            system=system, max_tokens=500)).text
        return TaskResult(answer=final.split("FINAL:", 1)[-1].strip(),
                          task_type="agentic", steps=steps)

    @staticmethod
    def _parse_action(text: str):
        """Findet 'ACTION: <tool> <args>' und liefert (tool, args-dict) oder None."""
        import json as _json
        for line in text.splitlines():
            line = line.strip()
            if not line.upper().startswith("ACTION:"):
                continue
            rest = line[len("ACTION:"):].strip()
            tool, _, raw = rest.partition(" ")
            tool = tool.strip()
            raw = raw.strip()
            try:
                args = _json.loads(raw) if raw.startswith("{") else None
            except ValueError:
                args = None
            if args is None:  # weiches Parsing für schwache Modelle
                key = {"terminal": "command", "web_search": "query",
                       "http_fetch": "url", "grep": "pattern", "glob": "pattern",
                       "fs_read": "path", "git": "args"}.get(tool, "input")
                args = {key: raw}
            return tool, args
        return None
