"""Model-Router — gewichtete Score-Funktion + Fallback-Kette (Plan §2).

Wählt pro Request das beste verfügbare Modell und versucht bei Fehlern die
nächstbesten, bis hin zum garantierten lokalen Fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..platform import Hardware, Profile
from ..platform import config as cfg_mod
from ..platform import usage as usage_mod
from .base import ChatRequest, ChatResponse, ModelSpec, Provider, ProviderError
from .registry import available_models


@dataclass
class Weights:
    quality: float
    speed: float
    cost: float
    privacy: float


# Profil → Gewichte (Plan §2.2). Ultra-Lite gewichtet Kosten/Speed/Privacy hoch.
PROFILE_WEIGHTS = {
    "ultra_lite": Weights(quality=0.5, speed=1.0, cost=1.0, privacy=0.8),
    "balanced": Weights(quality=1.0, speed=0.6, cost=0.6, privacy=0.5),
    "pro": Weights(quality=1.5, speed=0.4, cost=0.3, privacy=0.5),
}


class Router:
    def __init__(self, hw: Hardware, profile: Profile) -> None:
        self.hw = hw
        self.profile = profile
        self.weights = PROFILE_WEIGHTS.get(profile.name, PROFILE_WEIGHTS["balanced"])

    def _score(self, spec: ModelSpec, req: ChatRequest, prefer_fast: bool) -> float:
        w = self.weights
        # quality: Stärke passend zum Task?
        quality = 1.0 if req.task_type in spec.strengths else 0.4
        if not spec.is_local:
            quality += 0.3  # Cloud meist stärker
        # speed: lokal/klein schneller; fast-Flag verschiebt Gewicht
        speed = 1.0 if spec.is_local else 0.5
        speed_w = w.speed * (2.0 if prefer_fast else 1.0)
        # cost: lokal = 0 Kosten
        cost = 1.0 if spec.is_local else max(0.0, 1.0 - spec.cost_out / 30.0)
        # privacy: sensible Tasks bevorzugen lokal
        privacy = 1.0 if spec.is_local else (0.0 if req.sensitive else 0.6)

        score = (
            w.quality * quality
            + speed_w * speed
            + w.cost * cost
            + w.privacy * privacy
        )
        # HW-Gate: Modell, das die Maschine sprengt, hart ausschließen.
        if spec.min_ram_mb and self.hw.ram_mb and spec.min_ram_mb > self.hw.ram_mb:
            return float("-inf")
        if spec.needs_gpu and self.hw.gpu.vendor == "none":
            return float("-inf")
        # Fallback-Provider nur als letzte Wahl.
        if spec.provider == "local-fallback":
            score -= 100.0
        return score

    def rank(self, req: ChatRequest, prefer_fast: bool = False) -> list[tuple[ModelSpec, Provider]]:
        candidates = available_models()
        # Budget-Guard: bei überschrittenem Tages-Cap Cloud hart ausschließen.
        cap = cfg_mod.load().daily_budget
        if usage_mod.over_budget(cap):
            candidates = [(s, p) for s, p in candidates if s.is_local]
        scored = [
            (self._score(spec, req, prefer_fast), spec, prov)
            for spec, prov in candidates
        ]
        scored = [c for c in scored if c[0] != float("-inf")]
        scored.sort(key=lambda c: c[0], reverse=True)
        return [(spec, prov) for _, spec, prov in scored]

    def route(self, req: ChatRequest, prefer_fast: bool = False) -> ChatResponse:
        """Beste Wahl treffen, bei Fehlern die Fallback-Kette durchlaufen."""
        chain = self.rank(req, prefer_fast)
        last_err: Exception | None = None
        for spec, provider in chain:
            try:
                resp = provider.generate(req, spec.name)
                self._track(spec, req, resp)
                self._learn(spec, req, resp.text)
                return resp
            except ProviderError as exc:
                last_err = exc
                continue
        if last_err:
            raise last_err
        raise ProviderError("Kein Modell verfügbar")

    @staticmethod
    def _learn(spec: ModelSpec, req: ChatRequest, text: str) -> None:
        """Flywheel: jede echte Antwort (Cloud ODER lokal) als Trainingsdatum."""
        if not cfg_mod.load().learn:
            return
        try:
            from ..training import record_interaction
            record_interaction(
                req.prompt, req.system, text,
                provider=spec.provider, model=spec.name,
                task_type=req.task_type, is_local=spec.is_local,
            )
        except Exception:  # Datenerfassung darf nie den Request brechen
            pass

    def stream(self, req: ChatRequest, prefer_fast: bool = False):
        """Token-Stream über das bestbewertete Modell (Fallback vor erstem Token)."""
        chain = self.rank(req, prefer_fast)
        last_err: Exception | None = None
        for spec, provider in chain:
            try:
                got = False
                parts: list[str] = []
                for chunk in provider.stream(req, spec.name):
                    got = True
                    parts.append(chunk)
                    yield chunk
                if got:
                    self._learn(spec, req, "".join(parts))
                    return
            except ProviderError as exc:
                last_err = exc
                continue
        if last_err:
            raise last_err

    @staticmethod
    def _track(spec: ModelSpec, req: ChatRequest, resp: ChatResponse) -> None:
        if spec.is_local:
            return  # lokal = kostenlos, nicht tracken
        in_tok = int(resp.usage.get("input_tokens") or len(req.prompt) / 4)
        out_tok = int(resp.usage.get("output_tokens") or len(resp.text) / 4)
        cost = (in_tok / 1e6) * spec.cost_in + (out_tok / 1e6) * spec.cost_out
        usage_mod.record(spec.provider, spec.name, in_tok, out_tok, cost)
