from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessEvidence:
    live_score: float | None
    attack_score: float | None
    signals: tuple[str, ...] = ()


class LivenessProvider(ABC):
    """Contract for passive/active presentation-attack detection providers."""

    @abstractmethod
    async def assess(self, frames: list[bytes]) -> LivenessEvidence:
        raise NotImplementedError
