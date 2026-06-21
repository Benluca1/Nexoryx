"""Provider-Basis-Typen: Request/Response, Modell-Metadaten, Provider-Interface."""

from __future__ import annotations

from dataclasses import dataclass, field


class ProviderError(Exception):
    """Provider konnte nicht antworten (Netzwerk, Auth, Rate-Limit, …)."""


@dataclass
class ChatRequest:
    prompt: str
    system: str = ""
    task_type: str = "chat"  # chat|coding|reasoning|research|summarize|intent
    max_tokens: int = 1024
    sensitive: bool = False  # bevorzugt lokal, wenn True


@dataclass
class ChatResponse:
    text: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)


@dataclass
class ModelSpec:
    """Capability-Metadaten eines Modells (für den Score-Router)."""

    name: str
    provider: str
    is_local: bool
    max_ctx: int = 8192
    min_ram_mb: int = 0
    needs_gpu: bool = False
    strengths: tuple[str, ...] = ()  # coding, reasoning, research, chat, summarize
    cost_in: float = 0.0  # $/1M tokens (lokal = 0)
    cost_out: float = 0.0


class Provider:
    """Abstrakte Provider-Schnittstelle. Adapter implementieren `generate`."""

    name: str = "base"
    is_local: bool = False

    def available(self) -> bool:  # pragma: no cover - trivial
        return False

    def models(self) -> list[ModelSpec]:  # pragma: no cover - trivial
        return []

    def generate(self, req: ChatRequest, model: str) -> ChatResponse:
        raise NotImplementedError

    def stream(self, req: ChatRequest, model: str):
        """Token-Stream. Default: einmalig die volle Antwort (kein echtes Streaming)."""
        yield self.generate(req, model).text
