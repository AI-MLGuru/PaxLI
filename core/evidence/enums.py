from enum import StrEnum


class EvidenceType(StrEnum):
    SELFIE = "SELFIE"
    DOCUMENT = "DOCUMENT"
    LIVENESS = "LIVENESS"


class EvidenceSource(StrEnum):
    CLIENT = "CLIENT"
