# Averiq by PaxAlpha

**Identity Verification & Biometric Trust Infrastructure**

> **Verify with confidence.**

Averiq is a high-assurance identity verification platform designed for secure digital onboarding across banking, fintech, and other identity-sensitive applications.

The platform combines:

- Facial biometric verification
- Passive and active liveness / presentation-attack detection
- Document intelligence and OCR
- Identity consistency and risk reasoning
- Evidence-first verification decisions
- Session-based verification workflows
- Auditable model governance
- Benchmarking, calibration, and controlled continuous improvement

## Architectural principle

**Models produce evidence; the decision engine makes decisions.**

Averiq is intentionally being built as a new system. The former IDQORE Verification Engine is treated only as a reference implementation and learning baseline; its architecture and code are not being patched into Averiq.

## Initial architecture

```text
Capture Layer
    │
    ▼
Verification Session
    │
    ▼
Verification Orchestrator
    ├── Quality Engine
    ├── Face Engine
    ├── Liveness / PAD Engine
    ├── Document Engine
    ├── Identity Consistency
    └── Risk / Evidence
            │
            ▼
      Decision Engine
            │
      ┌─────┴─────┐
      ▼           ▼
   Result      Audit Event
      │
      ▼
Learning & Evaluation
```

## Repository status

This repository is the **FOUNDATION-001** scaffold. It establishes boundaries, configuration, API contracts, test infrastructure, and extension points before production biometric/document models are introduced.

## Development

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn apps.api.averiq_api.main:app --reload
```

API health endpoint:

```text
GET /health
GET /ready
```

## Database migrations

Production and staging schema changes are applied through Alembic, not
`Base.metadata.create_all()`. The app only auto-creates tables when
`APP_ENV=development` (the default), as a local-dev convenience.

```bash
alembic upgrade head          # apply all pending migrations
alembic revision --autogenerate -m "describe the change"   # after editing a model
alembic current                # show the applied revision
alembic downgrade -1           # roll back one revision
```

`migrations/env.py` reads the database URL from the application's own
`Settings` (env vars / `.env`), so migrations always target whatever
database the app itself would connect to.

## Verification states

- `VERIFIED`
- `REJECTED`
- `REVIEW_REQUIRED`
- `INCONCLUSIVE`
- `EXPIRED`
- `CANCELLED`

## Engineering principles

1. Evidence before verdicts.
2. Calibrated biometric thresholds, never magic numbers.
3. Verification sessions are first-class domain objects.
4. Production decisions are governed and auditable.
5. Model versions and evaluation evidence are traceable.
6. Sensitive identity data is minimized, protected, and retention-controlled.
7. Hardware-specific inference is hidden behind provider abstractions.
8. Continuous improvement is controlled rather than unrestricted online retraining.

## License

Proprietary — PaxAlpha.
