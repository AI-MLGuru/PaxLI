import { ApiError, categoryForStatus, networkError, safeMessageForStatus } from "./errors";
import type {
  AssuranceLevel,
  CreateSessionRequest,
  EvidenceResponse,
  EvidenceType,
  SessionEnvelope,
  VerificationSession,
} from "./contracts";
import type { ErrorEnvelope } from "./contracts";

export interface ApiClientOptions {
  baseUrl: string;
  credential: string;
  fetcher?: typeof fetch;
  correlationId?: string;
}

export interface UploadOptions {
  idempotencyKey?: string;
}

const STATUS_VALUES = new Set([
  "CREATED",
  "CAPTURING",
  "SUBMITTED",
  "PROCESSING",
  "COMPLETED",
  "EXPIRED",
  "CANCELLED",
]);
const ASSURANCE_VALUES = new Set(["STANDARD", "HIGH", "ENHANCED"]);
const OUTCOME_VALUES = new Set(["VERIFIED", "REJECTED", "REVIEW_REQUIRED", "INCONCLUSIVE"]);
const EVIDENCE_VALUES = new Set(["SELFIE", "DOCUMENT", "LIVENESS"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isSession(value: unknown): value is VerificationSession {
  if (!isRecord(value)) return false;
  const decision = value.decision;
  const validDecision = decision === null || (
    isRecord(decision) &&
    OUTCOME_VALUES.has(String(decision.outcome)) &&
    Array.isArray(decision.reason_codes) &&
    decision.reason_codes.every((code) => typeof code === "string") &&
    isRecord(decision.policy) &&
    isNonEmptyString(decision.policy.id) &&
    typeof decision.policy.version === "number" &&
    isNonEmptyString(decision.policy.hash)
  );
  return (
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.tenant_id) &&
    (value.external_reference === null || typeof value.external_reference === "string") &&
    typeof value.status === "string" && STATUS_VALUES.has(value.status) &&
    typeof value.assurance_level === "string" && ASSURANCE_VALUES.has(value.assurance_level) &&
    isNonEmptyString(value.created_at) &&
    isNonEmptyString(value.expires_at) &&
    (value.completed_at === null || typeof value.completed_at === "string") &&
    validDecision
  );
}

function isSessionEnvelope(value: unknown): value is SessionEnvelope {
  return isRecord(value) && isSession(value.data) && isResponseMeta(value.meta);
}

function isResponseMeta(value: unknown): value is { request_id: string } {
  return isRecord(value) && isNonEmptyString(value.request_id);
}

function isEvidence(value: unknown): value is EvidenceResponse {
  return (
    isRecord(value) &&
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.session_id) &&
    typeof value.evidence_type === "string" && EVIDENCE_VALUES.has(value.evidence_type) &&
    value.source === "CLIENT" &&
    isNonEmptyString(value.checksum) &&
    isNonEmptyString(value.mime_type) &&
    typeof value.size_bytes === "number" && value.size_bytes >= 0 &&
    isRecord(value.metadata) &&
    isNonEmptyString(value.created_at) &&
    (value.retention_until === null || typeof value.retention_until === "string")
  );
}

function makeRequestId(): string {
  return `req_${crypto.randomUUID()}`;
}

function makeCorrelationId(): string {
  return `corr_${crypto.randomUUID()}`;
}

export class PaxliApiClient {
  private readonly baseUrl: string;
  private readonly credential: string;
  private readonly fetcher: typeof fetch;
  private readonly correlationId: string;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.credential = options.credential;
    this.fetcher = options.fetcher ?? fetch;
    this.correlationId = options.correlationId ?? makeCorrelationId();
  }

  createSession(payload: CreateSessionRequest = {}): Promise<SessionEnvelope> {
    return this.request<SessionEnvelope>("/v1/verification-sessions", {
      method: "POST",
      body: JSON.stringify({
        external_reference: payload.external_reference,
        assurance_level: payload.assurance_level ?? ("STANDARD" satisfies AssuranceLevel),
      }),
      idempotencyKey: makeRequestId(),
      validate: isSessionEnvelope,
    });
  }

  uploadDocument(sessionId: string, file: File, options: UploadOptions = {}): Promise<EvidenceResponse> {
    return this.uploadSingle(sessionId, "document", file, "DOCUMENT", options);
  }

  uploadSelfie(sessionId: string, file: File, options: UploadOptions = {}): Promise<EvidenceResponse> {
    return this.uploadSingle(sessionId, "selfie", file, "SELFIE", options);
  }

  uploadLiveness(sessionId: string, frames: File[], options: UploadOptions = {}): Promise<EvidenceResponse> {
    if (frames.length < 1 || frames.length > 5) {
      throw new ApiError({
        category: "VALIDATION",
        code: "INVALID_LIVENESS_FRAME_COUNT",
        message: "Temporal Liveness Demo requires between 1 and 5 frames.",
        requestId: null,
        retryable: false,
        status: 422,
      });
    }
    const body = new FormData();
    frames.forEach((frame) => body.append("frames", frame, frame.name));
    return this.request<EvidenceResponse>(`/v1/verification-sessions/${sessionId}/liveness`, {
      method: "POST",
      body,
      idempotencyKey: options.idempotencyKey ?? makeRequestId(),
      validate: isEvidence,
    });
  }

  submitSession(sessionId: string): Promise<SessionEnvelope> {
    return this.request<SessionEnvelope>(`/v1/verification-sessions/${sessionId}/submit`, {
      method: "POST",
      validate: isSessionEnvelope,
    });
  }

  getSession(sessionId: string): Promise<SessionEnvelope> {
    return this.request<SessionEnvelope>(`/v1/verification-sessions/${sessionId}`, {
      method: "GET",
      validate: isSessionEnvelope,
    });
  }

  private uploadSingle(
    sessionId: string,
    endpoint: "document" | "selfie",
    file: File,
    evidenceType: EvidenceType,
    options: UploadOptions,
  ): Promise<EvidenceResponse> {
    const body = new FormData();
    body.append("file", file, file.name);
    return this.request<EvidenceResponse>(`/v1/verification-sessions/${sessionId}/${endpoint}`, {
      method: "POST",
      body,
      idempotencyKey: options.idempotencyKey ?? makeRequestId(),
      validate: (value): value is EvidenceResponse => isEvidence(value) && value.evidence_type === evidenceType,
    });
  }

  private async request<T>(
    path: string,
    options: {
      method: "GET" | "POST";
      body?: BodyInit;
      idempotencyKey?: string;
      validate: (value: unknown) => value is T;
    },
  ): Promise<T> {
    const requestId = makeRequestId();
    const headers = new Headers({
      Authorization: `Bearer ${this.credential}`,
      Accept: "application/json",
      "X-Request-ID": requestId,
      "X-Correlation-ID": this.correlationId,
    });
    if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");

    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        method: options.method,
        headers,
        body: options.body,
      });
    } catch {
      throw networkError();
    }

    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) throw this.toApiError(response.status, payload, requestId);
    if (!options.validate(payload)) {
      throw new ApiError({
        category: "INTERNAL",
        code: "MALFORMED_RESPONSE",
        message: "The verification service returned an invalid response.",
        requestId,
        retryable: false,
        status: response.status,
      });
    }
    return payload;
  }

  private toApiError(status: number, payload: unknown, fallbackRequestId: string): ApiError {
    const errorPayload = isRecord(payload) && isRecord(payload.error) ? payload as Partial<ErrorEnvelope> : null;
    const requestId = isRecord(errorPayload?.meta) && isNonEmptyString(errorPayload.meta.request_id)
      ? errorPayload.meta.request_id
      : fallbackRequestId;
    const code = isRecord(errorPayload?.error) && isNonEmptyString(errorPayload.error.code)
      ? errorPayload.error.code
      : "REQUEST_ERROR";
    return new ApiError({
      category: categoryForStatus(status),
      code,
      message: safeMessageForStatus(status),
      requestId,
      retryable: status === 408 || status === 429 || status >= 500,
      status,
    });
  }
}
