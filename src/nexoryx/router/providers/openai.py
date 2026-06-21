"""OpenAI-Provider (Cloud) — SDK-bevorzugt, urllib-Fallback.

Modell-ID konfigurierbar via NEXORYX_OPENAI_MODEL (Default `gpt-4o-mini`), um
unabhängig von Modell-Umbenennungen zu bleiben.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ...platform import config as cfg_mod
from ..base import ChatRequest, ChatResponse, ModelSpec, Provider, ProviderError

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("NEXORYX_OPENAI_MODEL", "gpt-4o-mini")


class OpenAIProvider(Provider):
    name = "openai"
    is_local = False

    def _key(self) -> str:
        return cfg_mod.get_key("OPENAI_API_KEY")

    def available(self) -> bool:
        return bool(self._key())

    def models(self) -> list[ModelSpec]:
        if not self.available():
            return []
        return [
            ModelSpec(
                name=DEFAULT_MODEL, provider=self.name, is_local=False,
                max_ctx=128_000, strengths=("chat", "coding", "summarize"),
                cost_in=0.5, cost_out=1.5,
            )
        ]

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        key = self._key()
        if not key:
            raise ProviderError("OPENAI_API_KEY fehlt")
        model = model or DEFAULT_MODEL
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        try:
            import openai  # type: ignore

            client = openai.OpenAI(api_key=key)
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=req.max_tokens
            )
            return ChatResponse(
                text=resp.choices[0].message.content or "", model=model, provider=self.name
            )
        except ImportError:
            pass

        payload = {"model": model, "messages": messages, "max_tokens": req.max_tokens}
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"OpenAI HTTP {exc.code}: {exc.read().decode(errors='ignore')[:200]}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"OpenAI-Fehler: {exc}") from exc
        text = data["choices"][0]["message"]["content"]
        return ChatResponse(text=text, model=model, provider=self.name, usage=data.get("usage", {}))
