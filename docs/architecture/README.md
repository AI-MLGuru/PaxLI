# Architecture

PaxLI is organized around a verification-session domain and independently replaceable intelligence engines.

## Dependency direction

`apps` → `core` → infrastructure/integration adapters.

Core verification logic should not depend directly on a model runtime, database driver, cloud storage provider, or external identity provider.

## Evidence flow

Capture → Quality → Face/Liveness/Document → Identity Consistency → Risk → Decision → Audit → Learning & Evaluation.
