from dataclasses import dataclass


@dataclass(frozen=True)
class LearningEvent:
    verification_id: str
    outcome: str
    source: str


class LearningPipeline:
    """Controlled improvement boundary: observe, evaluate, validate, then deploy."""

    def record(self, event: LearningEvent) -> None:
        # Persistence and evaluation workflows will be implemented in later milestones.
        return None
