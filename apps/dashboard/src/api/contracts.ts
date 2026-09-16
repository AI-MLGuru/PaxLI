export type VerificationStatus =
  | "CREATED"
  | "CAPTURING"
  | "SUBMITTED"
  | "PROCESSING"
  | "COMPLETED"
  | "EXPIRED"
  | "CANCELLED";

export type AssuranceLevel = "STANDARD" | "HIGH" | "ENHANCED";

export type DecisionOutcome =
  | "VERIFIED"
  | "REJECTED"
  | "REVIEW_REQUIRED"
  | "INCONCLUSIVE";

export type EvidenceType = "SELFIE" | "DOCUMENT" | "LIVENESS";

export interface ResponseMeta {
  request_id: string;
}

export interface PolicyReference {
  id: string;
  version: number;
  hash: string;
}

export interface DecisionProjection {
  outcome: DecisionOutcome;
  reason_codes: string[];
  policy: PolicyReference;
}

export interface VerificationSession {
  id: string;
  tenant_id: string;
  external_reference: string | null;
  status: VerificationStatus;
  assurance_level: AssuranceLevel;
  created_at: string;
  expires_at: string;
  completed_at: string | null;
  decision: DecisionProjection | null;
}

export interface SessionEnvelope {
  data: VerificationSession;
  meta: ResponseMeta;
}

export interface EvidenceResponse {
  id: string;
  session_id: string;
  evidence_type: EvidenceType;
  source: "CLIENT";
  checksum: string;
  mime_type: string;
  size_bytes: number;
  metadata: Record<string, unknown>;
  created_at: string;
  retention_until: string | null;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
  };
  meta: ResponseMeta;
}

export interface CreateSessionRequest {
  external_reference?: string;
  assurance_level?: AssuranceLevel;
}
