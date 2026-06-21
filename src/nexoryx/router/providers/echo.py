"""Deterministischer lokaler Fallback-Provider.

Das letzte Glied der Fallback-Kette (Plan §2.4): kein echtes LLM, aber immer
verfügbar und ohne Abhängigkeiten. Gibt eine ehrliche, hilfreiche Antwort statt
eines Fehlers — verkörpert „Graceful Degradation". Wird durch das Tiny-Model
bzw. lokale GGUF-Modelle ersetzt, sobald vorhanden.
"""

from __future__ import annotations

from ..base import ChatRequest, ChatResponse, ModelSpec, Provider


class EchoProvider(Provider):
    name = "local-fallback"
    is_local = True

    def available(self) -> bool:
        return True

    def models(self) -> list[ModelSpec]:
        return [
            ModelSpec(
                name="rule-fallback",
                provider=self.name,
                is_local=True,
                max_ctx=2048,
                strengths=("chat", "intent"),
            )
        ]

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        text = (
            "Nexoryx läuft aktuell ohne echtes Sprachmodell (kein lokales Modell "
            "installiert und keine Cloud-Keys gesetzt). Deine Anfrage:\n\n"
            f"  „{req.prompt.strip()}“\n\n"
            "So aktivierst du echte Antworten:\n"
            "  • Lokal:  Ollama installieren + `nexoryx models pull` (Phase 1)\n"
            "  • Cloud:  `nexoryx admin keys set anthropic`  (ANTHROPIC_API_KEY)\n"
        )
        return ChatResponse(text=text, model="rule-fallback", provider=self.name)
