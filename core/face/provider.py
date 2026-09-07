from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FaceEvidence:
    detected: bool
    embedding: tuple[float, ...] | None = None
    quality_score: float | None = None


class FaceProvider(ABC):
    """Hardware/runtime-neutral contract for face intelligence providers."""

    @abstractmethod
    async def extract_evidence(self, image: bytes) -> FaceEvidence:
        raise NotImplementedError
