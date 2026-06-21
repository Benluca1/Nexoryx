"""Google-Gemini-Provider (Cloud) — SDK-bevorzugt, urllib-Fallback.

Modell-ID konfigurierbar via NEXORYX_GEMINI_MODEL (Default `gemini-2.0-flash`).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ...platform import config as cfg_mod
from ..base import ChatRequest, ChatResponse, ModelSpec, Provider, ProviderError

DEFAULT_MODEL = os.environ.get("NEXORYX_GEMINI_MODEL", "gemini-2.0-flash")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(Provider):
    name = "gemini"
    is_local = False

    def _key(self) -> str:
        return cfg_mod.get_key("GEMINI_API_KEY") or cfg_mod.get_key("GOOGLE_API_KEY")

    def available(self) -> bool:
        return bool(self._key())

    def models(self) -> list[ModelSpec]:
        if not self.available():
            return []
        return [
            ModelSpec(
                name=DEFAULT_MODEL, provider=self.name, is_local=False,
                max_ctx=1_000_000, strengths=("chat", "research", "summarize"),
                cost_in=0.1, cost_out=0.4,
            )
        ]

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        key = self._key()
        if not key:
            raise ProviderError("GEMINI_API_KEY fehlt")
        model = model or DEFAULT_MODEL

        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=key)
            prompt = (req.system + "\n\n" + req.prompt) if req.system else req.prompt
            resp = client.models.generate_content(model=model, contents=prompt)
            return ChatResponse(text=resp.text or "", model=model, provider=self.name)
        except ImportError:
            pass

        prompt = (req.system + "\n\n" + req.prompt) if req.system else req.prompt
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        url = f"{API_BASE}/{model}:generateContent?key={key}"
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Gemini HTTP {exc.code}: {exc.read().decode(errors='ignore')[:200]}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"Gemini-Fehler: {exc}") from exc
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Gemini: unerwartete Antwort: {str(data)[:200]}") from exc
        return ChatResponse(text=text, model=model, provider=self.name)
