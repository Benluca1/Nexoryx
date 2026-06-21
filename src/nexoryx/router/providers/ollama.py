"""Ollama-Provider (lokal) via HTTP-API auf localhost:11434.

Zero-dependency (urllib). Wird nur als verfügbar gemeldet, wenn der Ollama-
Daemon erreichbar ist und mindestens ein Modell installiert ist.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..base import ChatRequest, ChatResponse, ModelSpec, Provider, ProviderError

BASE = os.environ.get("NEXORYX_OLLAMA_URL", "http://127.0.0.1:11434")


def _get(path: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


class OllamaProvider(Provider):
    name = "ollama"
    is_local = True

    def __init__(self) -> None:
        self._tags: list[str] | None = None

    def _list(self) -> list[str]:
        if self._tags is None:
            data = _get("/api/tags")
            self._tags = (
                [m["name"] for m in data.get("models", [])] if data else []
            )
        return self._tags

    def available(self) -> bool:
        return bool(self._list())

    def models(self) -> list[ModelSpec]:
        specs = []
        for name in self._list():
            specs.append(
                ModelSpec(
                    name=name,
                    provider=self.name,
                    is_local=True,
                    max_ctx=8192,
                    strengths=("chat", "coding", "reasoning"),
                )
            )
        return specs

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        payload = {
            "model": model,
            "prompt": req.prompt,
            "system": req.system or None,
            "stream": False,
            "options": {"num_predict": req.max_tokens},
        }
        body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode()
        request = urllib.request.Request(
            BASE + "/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"Ollama-Fehler: {exc}") from exc
        return ChatResponse(
            text=data.get("response", ""), model=model, provider=self.name
        )

    def stream(self, req: ChatRequest, model: str):
        payload = {
            "model": model, "prompt": req.prompt,
            "system": req.system or None, "stream": True,
            "options": {"num_predict": req.max_tokens},
        }
        body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode()
        request = urllib.request.Request(
            BASE + "/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if chunk.get("response"):
                        yield chunk["response"]
                    if chunk.get("done"):
                        break
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderError(f"Ollama-Stream-Fehler: {exc}") from exc
