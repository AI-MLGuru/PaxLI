# API

Planned verification-session endpoints:

- `POST /v1/verification-sessions`
- `POST /v1/verification-sessions/{id}/selfie`
- `POST /v1/verification-sessions/{id}/document`
- `POST /v1/verification-sessions/{id}/liveness`
- `GET /v1/verification-sessions/{id}`

Planned webhooks:

- `verification.completed`
- `verification.failed`
- `verification.review_required`
