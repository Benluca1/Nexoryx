"""Provider-Registry — entdeckt verfügbare Provider + ihre Modelle.

Reihenfolge bewusst: lokale Provider zuerst (Ollama → Fallback), dann Cloud.
Der Fallback-Provider ist immer dabei (garantierte Lauffähigkeit).
"""

from __future__ import annotations

from .base import ModelSpec, Provider
from .providers.anthropic import AnthropicProvider
from .providers.echo import EchoProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider


def all_providers() -> list[Provider]:
    return [
        OllamaProvider(),
        AnthropicProvider(),
        OpenAIProvider(),
        GeminiProvider(),
        EchoProvider(),  # immer zuletzt = letzter Fallback
    ]


def available_providers() -> list[Provider]:
    return [p for p in all_providers() if p.available()]


def available_models() -> list[tuple[ModelSpec, Provider]]:
    out: list[tuple[ModelSpec, Provider]] = []
    for provider in available_providers():
        for spec in provider.models():
            out.append((spec, provider))
    return out
