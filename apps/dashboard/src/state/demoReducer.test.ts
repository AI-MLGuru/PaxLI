import { describe, expect, it } from "vitest";

import { demoReducer } from "./demoReducer";
import type { DemoState } from "./demoTypes";

describe("demoReducer", () => {
  it("transitions from landing to a capture flow and records the session", () => {
    const initial: DemoState = {
      status: "landing",
      sessionId: null,
      requestId: null,
      errorMessage: null,
      evidence: { document: null, selfie: null, livenessFrames: [] },
      evidenceNames: { document: null, selfie: null, livenessFrames: 0 },
      timeline: [],
      lastOutcome: null,
    };

    const created = demoReducer(initial, {
      type: "start_demo",
    });
    const session = demoReducer(created, {
      type: "session_created",
      sessionId: "sess_123",
      requestId: "req_123",
    });
    const document = demoReducer(session, {
      type: "capture_document",
      file: new File(["doc"], "passport.pdf", { type: "application/pdf" }),
    });

    expect(created.status).toBe("session_created");
    expect(session.status).toBe("document_capture");
    expect(session.sessionId).toBe("sess_123");
    expect(document.evidence.document?.name).toBe("passport.pdf");
  });

  it("maps completed server outcomes to the documented UI states", () => {
    const state = demoReducer(undefined, {
      type: "completed",
      outcome: "VERIFIED",
      requestId: "req_result",
    });

    expect(state.status).toBe("completed_verified");
    expect(state.lastOutcome).toBe("VERIFIED");
    expect(state.requestId).toBe("req_result");
    expect(state.errorMessage).toBeNull();
  });

  it("keeps error states safe and non-decisional", () => {
    const reduced = demoReducer(undefined, {
      type: "recoverable_error",
      message: "The verification service is temporarily unavailable.",
    });

    expect(reduced.status).toBe("recoverable_error");
    expect(reduced.errorMessage).toContain("temporarily unavailable");
    expect(reduced.lastOutcome).toBeNull();
  });
});
