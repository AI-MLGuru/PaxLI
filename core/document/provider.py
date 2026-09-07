from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentEvidence:
    document_type: str | None
    fields: dict[str, str]
    quality_score: float | None = None
    authenticity_signals: tuple[str, ...] = ()


class DocumentProvider(ABC):
    """Contract for document detection, OCR, extraction and authenticity signals."""

    @abstractmethod
    async def extract_evidence(self, image: bytes) -> DocumentEvidence:
        raise NotImplementedError
