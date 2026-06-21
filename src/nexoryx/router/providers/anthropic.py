"""Anthropic-Provider (Cloud).

Bevorzugt das offizielle `anthropic`-SDK, wenn installiert; sonst Fallback auf
die Messages-API per urllib (damit der Kern ohne Abhängigkeiten läuft).

Modell-IDs gemäß aktueller Claude-API-Referenz: Default `claude-opus-4-8`
(höchste Qualität), `claude-haiku-4-5` als günstige/schnelle Variante.
Hinweis: keine `temperature`/`top_p`/`thinking`-Parameter — auf Opus 4.8 sind
Sampling-Parameter entfernt; adaptives Denken ist Default.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ...platform import config as cfg_mod
from ..base import ChatRequest, ChatResponse, ModelSpec, Provider, ProviderError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

MODELS = {
    "claude-opus-4-8": ModelSpec(
        name="claude-opus-4-8", provider="anthropic", is_local=False,
        max_ctx=1_000_000, strengths=("coding", "reasoning", "research"),
        cost_in=5.0, cost_out=25.0,
    ),
    "claude-haiku-4-5": ModelSpec(
        name="claude-haiku-4-5", provider="anthropic", is_local=False,
        max_ctx=200_000, strengths=("chat", "summarize"),
        cost_in=1.0, cost_out=5.0,
    ),
}


class AnthropicProvider(Provider):
    name = "anthropic"
    is_local = False

    def _key(self) -> str:
        return cfg_mod.get_key("ANTHROPIC_API_KEY")

    def available(self) -> bool:
        return bool(self._key())

    def models(self) -> list[ModelSpec]:
        return list(MODELS.values()) if self.available() else []

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        key = self._key()
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY fehlt")
        model = model if model in MODELS else "claude-opus-4-8"

        # 1) Offizielles SDK bevorzugen, falls vorhanden.
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic(api_key=key)
            kwargs = {
                "model": model,
                "max_tokens": req.max_tokens,
                "messages": [{"role": "user", "content": req.prompt}],
            }
            if req.system:
                kwargs["system"] = req.system
            msg = client.messages.create(**kwargs)
            if getattr(msg, "stop_reason", None) == "refusal":
                raise ProviderError("Anfrage wurde vom Modell abgelehnt (refusal)")
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            return ChatResponse(text=text, model=model, provider=self.name)
        except ImportError:
            pass  # → urllib-Fallback

        # 2) Fallback: Messages-API direkt.
        payload = {
            "model": model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            payload["system"] = req.system
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "x-api-key": key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Anthropic HTTP {exc.code}: {exc.read().decode(errors='ignore')[:200]}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"Anthropic-Fehler: {exc}") from exc
        if data.get("stop_reason") == "refusal":
            raise ProviderError("Anfrage wurde vom Modell abgelehnt (refusal)")
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        return ChatResponse(
            text=text, model=model, provider=self.name, usage=data.get("usage", {})
        )
