from core.verification.models import VerificationSession


class VerificationOrchestrator:
    """Coordinates verification engines without owning their implementation details."""

    async def process(self, session: VerificationSession) -> VerificationSession:
        # Foundation milestone: engine adapters will be wired here incrementally.
        return session
