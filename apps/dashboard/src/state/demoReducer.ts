import type { DemoAction, DemoState, DemoStatus } from "./demoTypes";

const initialState: DemoState = {
  status: "landing",
  sessionId: null,
  requestId: null,
  errorMessage: null,
  evidence: {
    document: null,
    selfie: null,
    livenessFrames: [],
  },
  evidenceNames: {
    document: null,
    selfie: null,
    livenessFrames: 0,
  },
  timeline: [],
  lastOutcome: null,
};

function mapOutcome(status: DemoStatus): DemoState["lastOutcome"] {
  switch (status) {
    case "completed_verified":
      return "VERIFIED";
    case "completed_rejected":
      return "REJECTED";
    case "completed_review_required":
      return "REVIEW_REQUIRED";
    case "completed_inconclusive":
      return "INCONCLUSIVE";
    default:
      return null;
  }
}

export function demoReducer(state: DemoState = initialState, action: DemoAction): DemoState {
  switch (action.type) {
    case "start_demo":
      return {
        ...initialState,
        status: "session_created",
      };
    case "session_created":
      return {
        ...state,
        status: "document_capture",
        sessionId: action.sessionId,
        requestId: action.requestId,
        errorMessage: null,
      };
    case "capture_document":
      return {
        ...state,
        status: "document_capture",
        evidence: { ...state.evidence, document: action.file },
      };
    case "capture_selfie":
      return {
        ...state,
        status: state.evidence.document ? "selfie_capture" : "document_capture",
        evidence: { ...state.evidence, selfie: action.file },
      };
    case "capture_liveness":
      return {
        ...state,
        status: "liveness_demo_optional",
        evidence: {
          ...state.evidence,
          livenessFrames: action.files,
        },
      };
    case "document_uploaded":
      return {
        ...state,
        evidence: { ...state.evidence, document: null },
        evidenceNames: { ...state.evidenceNames, document: action.name },
      };
    case "selfie_uploaded":
      return {
        ...state,
        evidence: { ...state.evidence, selfie: null },
        evidenceNames: { ...state.evidenceNames, selfie: action.name },
      };
    case "liveness_uploaded":
      return {
        ...state,
        evidence: { ...state.evidence, livenessFrames: [] },
        evidenceNames: { ...state.evidenceNames, livenessFrames: action.count },
      };
    case "ready_to_submit":
      return {
        ...state,
        status: "ready_to_submit",
      };
    case "submitting":
      return {
        ...state,
        status: "submitting",
        errorMessage: null,
      };
    case "processing":
      return {
        ...state,
        status: "processing",
      };
    case "timeline":
      return {
        ...state,
        timeline: [
          ...state.timeline,
          {
            id: `${action.name}-${state.timeline.length + 1}`,
            name: action.name,
            startedAt: new Date().toISOString(),
            endedAt: new Date().toISOString(),
            outcome: action.outcome,
            requestId: action.requestId,
            resourceId: action.resourceId,
          },
        ],
      };
    case "completed":
      return {
        ...state,
        status: `completed_${action.outcome.toLowerCase()}` as DemoStatus,
        lastOutcome: action.outcome,
        requestId: action.requestId ?? state.requestId,
        errorMessage: null,
      };
    case "expired":
      return {
        ...state,
        status: "expired",
        errorMessage: "The verification session expired before completion.",
      };
    case "cancelled":
      return {
        ...state,
        status: "cancelled",
        errorMessage: "The session was cancelled before a final result was reached.",
      };
    case "recoverable_error":
      return {
        ...state,
        status: "recoverable_error",
        errorMessage: action.message,
      };
    case "terminal_error":
      return {
        ...state,
        status: "terminal_error",
        errorMessage: action.message,
      };
    case "reset":
      return initialState;
    default:
      return state;
  }
}

export { initialState, mapOutcome };
