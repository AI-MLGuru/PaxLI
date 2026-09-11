# PaxLI by PaxAlpha

# Decision & Verification Semantics Specification

## Part VII - Security & Governance

**Semantic Contract:** v1.0  
**Document Status:** Normative  
**Product:** PaxLI by PaxAlpha  
**Positioning:** Identity Verification & Biometric Trust Infrastructure  
**Tagline:** Verify with confidence.

## 7.0 Purpose and Scope

This part defines the normative security, access-control, credential, cryptographic, governance, and abuse-prevention requirements for PaxLI.

PaxLI processes identity information, biometric evidence, authentication credentials, verification decisions, and tenant-owned operational data. Security is therefore a system property rather than an isolated infrastructure feature.

This part defines security boundaries, authentication, authorization, tenant isolation, credential lifecycle, privileged access, cryptographic controls, key management, secret handling, session security, biometric security, administrative security, policy governance, audit, incident handling, abuse prevention, adversarial input, testing, exceptions, and conformance. It does not prescribe a cloud provider, HSM vendor, database, framework, or cryptographic library.

### Requirements

- **SEC-7.0.1** Security controls MUST preserve Parts II-VI.
- **SEC-7.0.2** Security controls MUST be enforced at trusted server-side boundaries.
- **SEC-7.0.3** Security failure MUST NOT silently become verification success.
- **SEC-7.0.4** A required security control that cannot be established MUST follow safe workflow and decision failure semantics.

## 7.1 Security Principles

PaxLI security is based on least privilege, explicit authorization, tenant isolation, defense in depth, secure defaults, fail-safe behavior, credential minimization, cryptographic protection, auditability, separation of duties, controlled administration, privacy by design, and continuous verification of security assumptions.

### Requirements

- **SEC-7.1.1** Every protected operation MUST have an explicit authorization requirement.
- **SEC-7.1.2** Network location, request origin, resource identifier, and client metadata MUST NOT create implicit trust.
- **SEC-7.1.3** Controls MUST apply consistently to synchronous, asynchronous, scheduled, retry, webhook, and administrative paths.
- **SEC-7.1.4** Security-sensitive defaults MUST deny access unless explicitly permitted.
- **SEC-7.1.5** Availability MUST NOT be preserved by weakening controls that could create unauthorized access or false verification.

## 7.2 Security Boundaries

PaxLI maintains boundaries between tenants, verification operations, management operations, sensitive evidence, credentials, infrastructure, and external providers.

```text
                    PAXLI
                       |
        +--------------+--------------+
        |                             |
 Verification Plane            Management Plane
 Sessions / Evidence            Policies / Credentials
 Results / Processing            Webhooks / Configuration
        |                             |
        +--------------+--------------+
                       |
                 Tenant Boundary
```

### Requirements

- **SEC-7.2.1** PaxLI MUST maintain explicit boundaries between tenants, operational verification, management, evidence, credentials, infrastructure, and providers.
- **SEC-7.2.2** Boundary crossing MUST require explicit authorization or documented trusted system operation.
- **SEC-7.2.3** Internal network placement MUST NOT substitute for application authorization.
- **SEC-7.2.4** Security boundaries MUST be represented in architecture and conformance tests.

## 7.3 Authentication

Authentication establishes the identity of a requesting principal. Mechanisms may include API credentials, service credentials, administrative credentials, internally authenticated system actors, and future standards-based mechanisms.

### Requirements

- **SEC-7.3.1** Protected external operations MUST require an authenticated principal unless explicitly public.
- **SEC-7.3.2** Authentication MUST occur before authorization.
- **SEC-7.3.3** Credentials MUST be validated according to lifecycle state.
- **SEC-7.3.4** Expired or revoked credentials MUST NOT authenticate.
- **SEC-7.3.5** Authentication failures MUST NOT disclose secrets.
- **SEC-7.3.6** Authentication MUST resist trivial enumeration and applicable replay.
- **SEC-7.3.7** System actors MUST have explicit authentication or trusted execution semantics.

## 7.4 Authorization

Authorization determines whether an authenticated principal may perform a specific operation against a resource in a tenant context.

### Requirements

- **SEC-7.4.1** Authentication MUST NOT imply authorization.
- **SEC-7.4.2** Authorization MUST occur before the protected side effect.
- **SEC-7.4.3** Equivalent authorization context and policy state MUST produce deterministic decisions.
- **SEC-7.4.4** Authorization MUST be enforced server-side.
- **SEC-7.4.5** Resource IDs, headers, query parameters, bodies, and API versions MUST NOT bypass authorization.
- **SEC-7.4.6** Authorization failures MUST NOT expose unnecessary protected-resource information.

## 7.5 Tenant Isolation

PaxLI is tenant-scoped by default. Platform-level operations require explicit authorization.

### Requirements

- **SEC-7.5.1** Every tenant-owned resource MUST have an unambiguous ownership boundary.
- **SEC-7.5.2** Ownership MUST derive from trusted authentication and authorization context.
- **SEC-7.5.3** Client-supplied tenant identifiers MUST NOT override authenticated context.
- **SEC-7.5.4** Repository, service, API, storage, cache, search, and audit operations MUST preserve tenant boundaries.
- **SEC-7.5.5** Tenants MUST NOT retrieve another tenant's sessions, evidence, decisions, policies, credentials, webhooks, audits, or biometric representations.
- **SEC-7.5.6** Cross-tenant biometric matching or search MUST be disabled by default.
- **SEC-7.5.7** Legitimate cross-tenant operations MUST be explicitly platform-authorized and governed.
- **SEC-7.5.8** Tenant-isolation tests MUST include positive and adversarial cross-tenant attempts.

## 7.6 Roles and Permissions

Roles group privileges; permissions represent individual capabilities. Representative operational permissions are `verification:create`, `verification:read`, and `verification:cancel`. Administrative permissions include `policy:read`, `policy:manage`, `credential:manage`, `webhook:manage`, `audit:read`, and `configuration:manage`.

### Requirements

- **SEC-7.6.1** Permissions MUST be explicitly defined.
- **SEC-7.6.2** Roles MUST NOT acquire undocumented permissions.
- **SEC-7.6.3** High-risk permissions MUST NOT be granted by default.
- **SEC-7.6.4** Credential-management privileges MUST remain distinct from verification privileges.
- **SEC-7.6.5** Policy-management privileges MUST remain distinct from verification privileges.
- **SEC-7.6.6** Audit access MUST be explicitly authorized.
- **SEC-7.6.7** Permission checks MUST use the effective principal and tenant context.

## 7.7 Authorization Context

Security-sensitive execution context is recorded through a typed `AuthorizationContext`.

```json
{
  "actor_type": "HUMAN_OPERATOR",
  "actor_id": "actor_...",
  "tenant_id": "tenant_...",
  "credential_id": "cred_...",
  "authentication_method": "API_KEY",
  "permission_used": "verification:create",
  "request_id": "req_...",
  "source": "api",
  "timestamp": "..."
}
```

System operations identify `actor_type=SYSTEM`, an explicit service actor, authentication method, and permission.

### Requirements

- **SEC-7.7.1** Security-sensitive operations MUST have identifiable authorization context.
- **SEC-7.7.2** Context MUST identify actor type.
- **SEC-7.7.3** Tenant-scoped context MUST identify the effective tenant.
- **SEC-7.7.4** Context MUST identify the permission used.
- **SEC-7.7.5** System actors MUST be explicitly identified as `SYSTEM`.
- **SEC-7.7.6** Context MUST NOT contain raw credentials, tokens, private keys, or equivalent secrets.
- **SEC-7.7.7** Context MUST support audit correlation without unnecessary sensitive data.

## 7.8 Credential Lifecycle

Credentials have explicit lifecycle states:

```text
ISSUED -> ACTIVE -> EXPIRED
                    or
                    REVOKED
```

Controlled rotation MAY support bounded overlapping validity.

### Requirements

- **SEC-7.8.1** Every credential MUST have an identifiable lifecycle state.
- **SEC-7.8.2** Only active credentials MAY authenticate.
- **SEC-7.8.3** Expired credentials MUST NOT authenticate.
- **SEC-7.8.4** Revoked credentials MUST NOT authenticate.
- **SEC-7.8.5** Rotation MUST support controlled transition without unsafe secret exposure.
- **SEC-7.8.6** Emergency revocation MUST take effect without a normal deployment cycle.
- **SEC-7.8.7** Credential lifecycle operations MUST be auditable.

## 7.9 Credential Storage

Credentials are security-sensitive data.

### Requirements

- **SEC-7.9.1** Recoverable API secrets MUST NOT be stored in plaintext.
- **SEC-7.9.2** Secret verification MUST use an approved password/secret hashing mechanism appropriate to the threat model.
- **SEC-7.9.3** Memory-hard hashing such as Scrypt or an approved equivalent MAY be used.
- **SEC-7.9.4** Credential verification MUST use constant-time comparison where applicable.
- **SEC-7.9.5** Raw credentials MUST NOT enter ordinary logs.
- **SEC-7.9.6** Raw credentials MUST NOT enter audit events.
- **SEC-7.9.7** Raw credentials MUST NOT be returned after authorized one-time issuance.

## 7.10 Credential Issuance

Credential issuance is privileged.

### Requirements

- **SEC-7.10.1** Issuance MUST require explicit authorization.
- **SEC-7.10.2** New secrets MUST be exposed only through an authorized issuance mechanism.
- **SEC-7.10.3** Plaintext secrets MUST NOT be retrievable after initial exposure.
- **SEC-7.10.4** Credential identifiers MAY remain retrievable while secrets remain unrecoverable.
- **SEC-7.10.5** Issuance MUST generate an audit event.

## 7.11 Credential Rotation and Revocation

Credential rotation limits compromise impact and supports continuity.

### Requirements

- **SEC-7.11.1** Credentials MUST support explicit revocation.
- **SEC-7.11.2** Rotation MUST NOT expose historical secrets.
- **SEC-7.11.3** Any overlap period MUST be explicitly bounded.
- **SEC-7.11.4** Revocation MUST take effect immediately or within a documented security propagation bound.
- **SEC-7.11.5** Rotation and revocation MUST be auditable.

## 7.12 Administrative and Operational Credential Separation

Operational credentials perform verification operations; administrative credentials administer the platform.

### Requirements

- **SEC-7.12.1** Operational credentials MUST NOT automatically possess administrative permissions.
- **SEC-7.12.2** Administrative credentials MUST NOT be required for ordinary verification.
- **SEC-7.12.3** Credential-management permissions MUST be separately authorized.
- **SEC-7.12.4** Policy-management permissions MUST be separately authorized.
- **SEC-7.12.5** Administrative credentials SHOULD have stronger authentication and monitoring.
- **SEC-7.12.6** Operational credential compromise MUST NOT automatically provide tenant administration.

## 7.13 Secret Handling

Secrets include API keys, credential secrets, webhook signing secrets, encryption keys, private keys, provider credentials, database credentials, and infrastructure secrets.

### Requirements

- **SEC-7.13.1** Secrets MUST NOT be committed to source control.
- **SEC-7.13.2** Secrets MUST NOT enter ordinary logs.
- **SEC-7.13.3** Secrets MUST NOT enter API errors.
- **SEC-7.13.4** Secrets MUST NOT enter ordinary audit metadata.
- **SEC-7.13.5** Components MUST receive secrets only when operationally necessary.
- **SEC-7.13.6** Secret access SHOULD be auditable where feasible.
- **SEC-7.13.7** Secret management MUST support controlled rotation.

## 7.14 Cryptographic Protection

Cryptography protects data in transit, at rest, and during controlled security-sensitive operations.

### Requirements

- **SEC-7.14.1** Sensitive data crossing untrusted networks MUST use approved authenticated encryption or secure transport.
- **SEC-7.14.2** Highly sensitive identity and biometric data MUST have appropriate at-rest encryption.
- **SEC-7.14.3** Algorithms and parameters MUST follow current security standards and threat-model requirements.
- **SEC-7.14.4** Deprecated or broken algorithms MUST NOT be introduced for new protected data.
- **SEC-7.14.5** Cryptographic protection MUST include key lifecycle management.

## 7.15 Key Management

Application components SHOULD use an explicit cryptographic boundary rather than own unrestricted long-lived master keys.

Conceptual abstraction:

```python
class KeyProvider(Protocol):
    async def encrypt(self, plaintext: bytes, key_id: str) -> bytes: ...
    async def decrypt(self, ciphertext: bytes, key_id: str) -> bytes: ...
    async def rotate_key(self, key_id: str) -> str: ...
```

### Requirements

- **SEC-7.15.1** Application code MUST NOT require unrestricted master-key access.
- **SEC-7.15.2** Key operations MUST be isolated behind an explicit cryptographic boundary.
- **SEC-7.15.3** Key rotation MUST be supported for protected long-lived data where required.
- **SEC-7.15.4** Key identifiers MUST NOT be treated as secret material.
- **SEC-7.15.5** Key management MUST support approved managed KMS, Vault-like, or HSM-backed providers without changing application semantics.
- **SEC-7.15.6** Suspected key compromise MUST trigger defined rotation or revocation response.

## 7.16 Evidence Security

Evidence security preserves Part III semantics.

### Requirements

- **SEC-7.16.1** Evidence MUST remain tenant-scoped.
- **SEC-7.16.2** Evidence MUST be protected against unauthorized retrieval.
- **SEC-7.16.3** Evidence integrity MUST be verifiable.
- **SEC-7.16.4** Evidence access MUST be auditable where required.
- **SEC-7.16.5** Evidence MUST NOT enter ordinary logs.
- **SEC-7.16.6** Evidence MUST NOT enter generic errors.
- **SEC-7.16.7** Evidence deletion MUST follow authorized, audited deletion semantics.

## 7.17 Biometric Security

Biometric information includes face images, embeddings, liveness evidence, quality measurements, and model outputs. It requires elevated protection and cannot be treated as an ordinary password.

### Requirements

- **SEC-7.17.1** Biometric data MUST receive the highest applicable access and protection controls.
- **SEC-7.17.2** Biometric representations MUST remain tenant-scoped unless explicitly authorized otherwise.
- **SEC-7.17.3** Embeddings MUST NOT be treated as ordinary identifiers.
- **SEC-7.17.4** Embeddings MUST NOT be assumed irreversible merely because they are not raw images.
- **SEC-7.17.5** Raw model inputs and embeddings MUST NOT enter ordinary errors or logs.
- **SEC-7.17.6** 1:1 verification and 1:N search MUST remain distinct capabilities.
- **SEC-7.17.7** 1:N search is `FUTURE` for v1.0 and MUST NOT be enabled unless promoted through specification governance with explicit semantics and authorization.
- **SEC-7.17.8** Cross-tenant biometric search MUST NOT arise incidentally from shared infrastructure and remains prohibited unless explicitly promoted through governance.

## 7.18 Identity and Biometric Enumeration Resistance

Responses MUST limit leakage about whether protected identity or biometric records exist.

### Requirements

- **SEC-7.18.1** Authentication and authorization responses MUST NOT unnecessarily reveal protected identity existence.
- **SEC-7.18.2** Unauthorized requests MUST NOT provide a reliable identity-enumeration mechanism.
- **SEC-7.18.3** Verification results MUST be exposed only to authorized principals.
- **SEC-7.18.4** Enumeration controls MUST NOT distort authorized authoritative results.

## 7.19 Session Security

Verification sessions are security-sensitive workflows.

### Requirements

- **SEC-7.19.1** Every session MUST be tenant-associated.
- **SEC-7.19.2** Session IDs MUST be sufficiently unpredictable to prevent practical guessing.
- **SEC-7.19.3** Knowledge of a session ID MUST NOT alone authorize access.
- **SEC-7.19.4** Session operations MUST verify ownership and authorization.
- **SEC-7.19.5** Expired or cancelled sessions MUST reject prohibited operations.
- **SEC-7.19.6** State transitions MUST be protected against unauthorized concurrent modification.

## 7.20 Replay Protection

Replay may affect API requests, evidence submissions, webhooks, authentication, and provider interactions.

### Requirements

- **SEC-7.20.1** Security-sensitive operations MUST define replay behavior.
- **SEC-7.20.2** Idempotency MUST prevent duplicate side effects where applicable.
- **SEC-7.20.3** Webhook events MUST include identity and timing information for replay detection.
- **SEC-7.20.4** Replay protection MUST NOT silently accept contradictory duplicate operations.

## 7.21 Input Security and Adversarial Requests

External input may be malicious, malformed, oversized, contradictory, or resource-exhausting. Inputs include malformed JSON, oversized payloads, invalid media, decompression bombs, metadata, policies, pathological expressions, replays, invalid identifiers, unexpected Unicode, and unsupported content types.

### Requirements

- **SEC-7.21.1** External input MUST be validated before unsafe processing.
- **SEC-7.21.2** Size limits MUST be enforced before expensive processing where feasible.
- **SEC-7.21.3** Malformed input MUST NOT cause uncontrolled process termination.
- **SEC-7.21.4** Malformed input MUST NOT bypass authentication or authorization.
- **SEC-7.21.5** Policy input MUST undergo schema and semantic validation before activation.
- **SEC-7.21.6** Adversarial inputs MUST be included in security and reliability tests.

## 7.22 File and Media Security

Uploaded documents and biometric media are untrusted input.

### Requirements

- **SEC-7.22.1** Uploaded files MUST be treated as untrusted.
- **SEC-7.22.2** File type validation MUST NOT rely solely on client MIME type or filename.
- **SEC-7.22.3** Size limits MUST be enforced.
- **SEC-7.22.4** Unsupported or malformed media MUST fail safely.
- **SEC-7.22.5** Media processing MUST NOT expose filesystem or infrastructure access through attacker-controlled content.
- **SEC-7.22.6** Stored media MUST remain tenant-scoped and access-controlled.

## 7.23 Policy Security and Governance

Policies determine how evidence is interpreted and are high-impact control-plane resources.

### Requirements

- **SEC-7.23.1** Policy creation MUST require explicit authorization.
- **SEC-7.23.2** Activation MUST require schema and semantic validation.
- **SEC-7.23.3** Invalid policies MUST NOT become active.
- **SEC-7.23.4** Historical policy versions MUST remain immutable.
- **SEC-7.23.5** Changes MUST be attributable to an authorized actor.
- **SEC-7.23.6** Changes MUST generate durable audit records.
- **SEC-7.23.7** Changes MUST NOT silently rewrite historical decisions.
- **SEC-7.23.8** Policies MUST NOT contain arbitrary code, unrestricted database access, network calls, or equivalent unsafe execution.

## 7.24 Policy Change Governance

A policy change creates a new decision environment. A conceptual audit event includes policy ID, previous/new versions, actor, authorization context, reason, timestamp, and summary.

### Requirements

- **SEC-7.24.1** Every activated policy version MUST have unique version identity.
- **SEC-7.24.2** Policy changes MUST record previous and new versions where applicable.
- **SEC-7.24.3** Changes MUST identify the authorized actor or system process.
- **SEC-7.24.4** Changes MUST retain sufficient authorization context for reconstruction.
- **SEC-7.24.5** Historical decisions MUST retain their original policy version.

## 7.25 Administrative Access

Administrative access can affect an entire tenant or platform.

### Requirements

- **SEC-7.25.1** Administrative operations MUST require explicit authorization.
- **SEC-7.25.2** Administrative access MUST be auditable.
- **SEC-7.25.3** Administrative credentials MUST NOT be shared through ordinary application configuration or source control.
- **SEC-7.25.4** Sensitive administrative access SHOULD use stronger authentication and monitoring.
- **SEC-7.25.5** Administrative access MUST be least-privilege.
- **SEC-7.25.6** Emergency administrative access MUST follow documented procedures.

## 7.26 Sandbox and Production Separation

Sandbox and production are distinct trust environments.

### Requirements

- **SEC-7.26.1** Sandbox and production credentials MUST be distinct.
- **SEC-7.26.2** Production credentials MUST NOT be required for ordinary sandbox testing.
- **SEC-7.26.3** Production identity or biometric data MUST NOT enter sandbox without explicit authorization and controls.
- **SEC-7.26.4** Sandbox configuration MUST NOT silently grant production privileges.
- **SEC-7.26.5** Production access MUST require environment-specific authorization.

## 7.27 External Provider Security

External providers include identity registries, biometric and document services, notification providers, and infrastructure services.

### Requirements

- **SEC-7.27.1** Every provider integration MUST have an explicit trust boundary.
- **SEC-7.27.2** Provider credentials MUST be isolated from ordinary tenant credentials.
- **SEC-7.27.3** Provider responses MUST be validated before being trusted as evidence.
- **SEC-7.27.4** Provider availability MUST NOT equal provider verification success.
- **SEC-7.27.5** Provider failure MUST follow Parts IV and V safe-failure semantics.
- **SEC-7.27.6** Provider data MUST NOT bypass tenant authorization.
- **SEC-7.27.7** Material provider changes MUST be detected, reviewed, and governed.

## 7.28 Security and Decision Authority

Security controls preserve the Decision Engine's exclusive verdict authority.

### Requirements

- **SEC-7.28.1** Security, biometric, document, liveness, and provider components MUST NOT independently declare final verdicts.
- **SEC-7.28.2** A security component MAY block an operation but MUST NOT fabricate a verification decision.
- **SEC-7.28.3** Required security evidence that cannot be established MUST follow Part V safe-failure semantics.
- **SEC-7.28.4** Security unavailability MUST NOT become biometric or identity mismatch.

## 7.29 Audit and Security Traceability

Auditable security actions include credential lifecycle, privileged authentication, policy and permission changes, webhook and tenant configuration, evidence deletion, privileged access, and incident actions.

### Requirements

- **SEC-7.29.1** Security-sensitive administrative operations MUST generate durable audit events.
- **SEC-7.29.2** Audit events MUST identify relevant authorization context.
- **SEC-7.29.3** Audit records MUST NOT contain raw secrets.
- **SEC-7.29.4** Audit records MUST NOT contain raw biometric or document content.
- **SEC-7.29.5** Audit events MUST be protected against unauthorized modification.
- **SEC-7.29.6** Security audit records MUST support investigation of suspicious activity.

## 7.30 Security Event Ordering

Security state changes and required audit events have explicit ordering.

### Requirements

- **SEC-7.30.1** Required audit MUST be durably accepted before an operation is externally successful.
- **SEC-7.30.2** Required security-audit failure MUST NOT be silently ignored.
- **SEC-7.30.3** Best-effort telemetry MUST remain distinct from mandatory security audit.
- **SEC-7.30.4** The system MUST define which security actions require durable audit before completion.

## 7.31 Security Incident Handling

Security incidents include suspected or confirmed credential compromise, unauthorized or cross-tenant access, evidence exposure, malicious manipulation, policy compromise, provider or key compromise, and security-control bypass.

### Requirements

- **SEC-7.31.1** Documented procedures MUST cover detection, containment, investigation, recovery, and review.
- **SEC-7.31.2** Incidents MUST have identifiable incident records.
- **SEC-7.31.3** Compromised credentials MUST support emergency revocation.
- **SEC-7.31.4** Compromised keys MUST trigger defined key-response procedures.
- **SEC-7.31.5** Suspected cross-tenant exposure MUST be high severity.
- **SEC-7.31.6** Relevant audit and forensic information MUST be preserved subject to privacy and retention.
- **SEC-7.31.7** Incident response MUST NOT modify historical decisions to conceal or simplify an incident.

## 7.32 Abuse Prevention

Potential abuse includes credential attacks, enumeration, verification flooding, storage abuse, provider abuse, replay, resource exhaustion, and biometric probing.

### Requirements

- **SEC-7.32.1** Controls MUST prevent unauthorized resource consumption.
- **SEC-7.32.2** Abuse controls MUST preserve tenant isolation and legitimate availability.
- **SEC-7.32.3** Rate limiting MUST follow Part VI.
- **SEC-7.32.4** Repeated authentication failures SHOULD be observable.
- **SEC-7.32.5** Abuse controls MUST NOT silently become verification rejection.

## 7.33 Security Logging

Logging supports security investigation but creates a secondary data-exposure risk.

### Requirements

- **SEC-7.33.1** Security logs MUST NOT contain plaintext credentials.
- **SEC-7.33.2** Security logs MUST NOT contain raw biometric images.
- **SEC-7.33.3** Security logs MUST NOT contain raw document images.
- **SEC-7.33.4** Security logs MUST NOT contain raw access or refresh tokens.
- **SEC-7.33.5** Sensitive identity values MUST be minimized or sanitized.
- **SEC-7.33.6** Logs MUST retain sufficient non-sensitive investigation context.
- **SEC-7.33.7** Log sanitization MUST have regression tests.

## 7.34 Security Testing

Security testing includes unit, integration, API contract, authorization, tenant-isolation, adversarial-input, dependency-failure, credential-lifecycle, secret-leakage, and regression testing.

### Requirements

- **SEC-7.34.1** Every security-sensitive authorization boundary MUST have automated tests.
- **SEC-7.34.2** Tenant isolation MUST have adversarial tests.
- **SEC-7.34.3** Credential issuance, rotation, expiration, and revocation MUST have automated tests.
- **SEC-7.34.4** Sensitive leakage through errors and logs MUST have automated tests.
- **SEC-7.34.5** Security tests MUST include malformed and hostile inputs.
- **SEC-7.34.6** Alternate API paths MUST NOT perform unauthorized operations.
- **SEC-7.34.7** Security regression tests MUST be retained after vulnerabilities are fixed.

## 7.35 Security Failure Semantics

Security failures are distinct from verification failures, including authentication, authorization, credential-service, key-management, audit-control, tenant-context, and security-dependency failures.

### Requirements

- **SEC-7.35.1** Authentication failure MUST NOT be represented as `REJECTED` verification.
- **SEC-7.35.2** Authorization failure MUST NOT be represented as `REJECTED` verification.
- **SEC-7.35.3** Required cryptographic-service failure MUST NOT be represented as identity mismatch.
- **SEC-7.35.4** Required security-control failure MUST follow API or workflow error semantics.
- **SEC-7.35.5** A security dependency preventing safe processing MUST follow Decision Engine safe-failure semantics.

## 7.36 Security Governance and Exceptions

Security requirements are normative. Exceptions require explicit review and governance.

### Requirements

- **SEC-7.36.1** Requirements MUST NOT be bypassed through undocumented exceptions.
- **SEC-7.36.2** Every approved exception MUST have a unique identifier.
- **SEC-7.36.3** Exceptions MUST document affected requirement, reason, scope, risk, controls, authority, dates, and expiration/renewal.
- **SEC-7.36.4** Exceptions MUST be recorded in the Approved Exception Registry defined by Part II.
- **SEC-7.36.5** Expired exceptions MUST NOT remain silently active.
- **SEC-7.36.6** Exceptions MUST NOT authorize cross-tenant access, secret exposure, or false verification outcomes without explicit approval.

## 7.37 Conformance Requirements

Security conformance MUST be evaluated at normative-requirement level.

Suggested structure:

```text
tests/contracts/security/
|- test_authentication.py
|- test_authorization.py
|- test_tenant_isolation.py
|- test_credentials.py
|- test_secrets.py
|- test_key_management.py
|- test_evidence_security.py
|- test_biometric_security.py
|- test_session_security.py
|- test_replay.py
|- test_adversarial_input.py
|- test_policy_security.py
|- test_audit_security.py
|- test_incident_controls.py
`- test_data_leakage.py
```

### Requirements

- **SEC-7.37.1** Every applicable v1.0 security requirement MUST map to implementation evidence or an automated test; deferred capability scope or an approved exception MUST NOT be treated as conformance without Part II governance.
- **SEC-7.37.2** Conformance MUST include expected-use and adversarial-use cases.
- **SEC-7.37.3** Conformance MUST include cross-tenant attacks.
- **SEC-7.37.4** Conformance MUST include credential lifecycle scenarios.
- **SEC-7.37.5** Conformance MUST include secret-leakage regression tests.
- **SEC-7.37.6** Conformance MUST prove administrative permissions cannot be obtained through operational credentials.
- **SEC-7.37.7** Conformance MUST prove alternate identifiers and API paths cannot bypass authorization.
- **SEC-7.37.8** Conformance MUST prove security failures do not become false verification rejection or approval.
- **SEC-7.37.9** Conformance MUST prove required audit generation for security-sensitive operations.
- **SEC-7.37.10** Results MUST be suitable for the overall release conformance report.

## 7.38 Constitutional Principle

Security protects the integrity of PaxLI, its tenants, evidence, decisions, and the people whose identities are processed. Only an authorized principal may cause an authorized state change within an authorized tenant boundary.

A security failure is not evidence of identity failure. Unavailable credential services, key management, authorization context, audit controls, or dependencies MUST NOT become fabricated identity mismatches. Successful authentication, authorization, biometric matching, or document extraction does not itself establish identity verification. The Decision Engine remains the sole final-verdict authority.

### Final Constitutional Rule

> **PaxLI MUST enforce least privilege, explicit authorization, tenant isolation, cryptographic protection, controlled credential lifecycles, auditable privileged operations, and safe security failure while preserving the exclusive authority of the Decision Engine over final verification outcomes.**

## End of Part VII
