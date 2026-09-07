from fastapi import FastAPI

from apps.api.averiq_api.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Averiq API",
    description="Identity verification and biometric trust infrastructure by PaxAlpha.",
    version=settings.app_version,
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "averiq-api", "version": settings.app_version}


@app.get("/ready", tags=["system"])
async def readiness() -> dict[str, str]:
    # Foundation milestone: dependency probes will be added behind infrastructure adapters.
    return {"status": "ready"}
