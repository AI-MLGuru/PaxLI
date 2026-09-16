export type DemoStatus =
  | "landing"
  | "session_created"
  | "document_capture"
  | "selfie_capture"
  | "liveness_demo_optional"
  | "ready_to_submit"
  | "submitting"
  | "processing"
  | "completed_verified"
  | "completed_rejected"
  | "completed_review_required"
  | "completed_inconclusive"
  | "expired"
  | "cancelled"
  | "recoverable_error"
  | "terminal_error";

export type DemoOutcome =
  | "VERIFIED"
  | "REJECTED"
  | "REVIEW_REQUIRED"
  | "INCONCLUSIVE";

export interface DemoTimelineEntry {
  id: string;
  name: string;
  startedAt: string;
  endedAt: string | null;
  outcome: "success" | "failure" | "retryable" | "info" | "pending";
  requestId?: string;
  resourceId?: string;
}

export interface DemoState {
  status: DemoStatus;
  sessionId: string | null;
  requestId: string | null;
  errorMessage: string | null;
  evidence: {
    document: File | null;
    selfie: File | null;
    livenessFrames: File[];
  };
  evidenceNames: {
    document: string | null;
    selfie: string | null;
    livenessFrames: number;
  };
  timeline: DemoTimelineEntry[];
  lastOutcome: DemoOutcome | null;
}

export type DemoAction =
  | { type: "start_demo" }
  | { type: "session_created"; sessionId: string; requestId: string }
  | { type: "capture_document"; file: File }
  | { type: "capture_selfie"; file: File }
  | { type: "capture_liveness"; files: File[] }
  | { type: "document_uploaded"; name: string }
  | { type: "selfie_uploaded"; name: string }
  | { type: "liveness_uploaded"; count: number }
  | { type: "ready_to_submit" }
  | { type: "submitting" }
  | { type: "processing" }
  | { type: "timeline"; name: string; outcome: DemoTimelineEntry["outcome"]; requestId?: string; resourceId?: string }
  | { type: "completed"; outcome: DemoOutcome; requestId?: string }
  | { type: "expired" }
  | { type: "cancelled" }
  | { type: "recoverable_error"; message: string }
  | { type: "terminal_error"; message: string }
  | { type: "reset" };
