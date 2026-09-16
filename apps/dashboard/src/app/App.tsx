import { createContext, useContext, useEffect, useReducer, useRef, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { PaxliApiClient } from "../api/client";
import { demoReducer, initialState } from "../state/demoReducer";
import type { DemoAction, DemoState } from "../state/demoTypes";

const platformDomains = [
  ["01", "Document intelligence", "Turn captured identity documents into structured, inspectable evidence.", ["Capture", "OCR", "MRZ", "Barcode", "Reconciliation"]],
  ["02", "Identity", "Resolve a trusted identity reference with explicit provenance and field relationships.", ["Reference", "Binding", "Provenance", "Field matching"]],
  ["03", "Biometrics", "Assess face quality, matching, and bounded liveness signals without hiding uncertainty.", ["Face quality", "Embedding", "Matching", "Temporal Liveness Demo"]],
] as const;

const DemoContext = createContext<{ state: DemoState; dispatch: React.Dispatch<DemoAction> } | null>(null);

function useDemoContext() {
  const context = useContext(DemoContext);
  if (!context) throw new Error("Demo context is unavailable.");
  return context;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="wordmark" to="/" aria-label="PaxLI by PaxAlpha — home">
          <span className="brand-zone">
            <img className="brand-logo" src="/paxli-logo.jpg" alt="" />
          </span>
          <span className="brand-lockup">
            <span className="brand-name">PaxLI</span>
            <span className="brand-by">by PaxAlpha</span>
          </span>
        </NavLink>
        <nav aria-label="Primary navigation">
          <NavLink className="nav-link nav-link-muted" to="/">
            Capabilities
          </NavLink>
          <NavLink className="nav-link" to="/demo">
            Demo
          </NavLink>
          <NavLink className="nav-link nav-link-muted" to="/diagnostics">
            Diagnostics
          </NavLink>
        </nav>
      </header>
      {children}
      <footer className="footer">
        <span>PaxLI by PaxAlpha — demonstration environment</span>
        <span>Evidence before verdicts.</span>
      </footer>
    </div>
  );
}

function LandingPage() {
  return (
    <main className="landing page-frame">
      <section className="hero-grid">
        <div className="hero-copy">
          <p className="eyebrow">Identity, verified.</p>
          <h1>
            Identity verification that shows its reasoning.
          </h1>
          <p className="hero-description">
            Documents, identity, biometrics, and evidence resolve into one
            inspectable decision — never a black box.
          </p>
          <div className="hero-actions">
            <NavLink className="primary-action" to="/demo">
              Run a demo <span aria-hidden="true">↗</span>
            </NavLink>
            <a className="secondary-action" href="#capabilities">
              Explore the platform <span aria-hidden="true">↓</span>
            </a>
          </div>
          <p className="hero-note">Evidence before verdicts. Explicit uncertainty where certainty is not established.</p>
        </div>
        <div className="signal-panel engine-panel" role="img" aria-label="PaxLI engine showing the path from document capture through evidence and identity to decision">
          <div className="signal-header">
            <span className="status-dot" aria-hidden="true" />
            <span>PaxLI engine</span>
            <span className="signal-state">EVIDENCE → DECISION</span>
          </div>
          <div className="verification-visual" aria-hidden="true">
            <span className="visual-grid" />
            <span className="flow-line flow-line-one" />
            <span className="flow-line flow-line-two" />
            <span className="flow-line flow-line-three" />
            <div className="visual-caption visual-caption-document">capture</div>
            <div className="visual-caption visual-caption-face">biometrics</div>
            <div className="document-signal">
              <span className="document-signal-top">DOCUMENT / EVIDENCE</span>
              <span className="document-signal-line document-signal-line-long" />
              <span className="document-signal-line" />
              <span className="document-signal-line document-signal-line-short" />
              <span className="document-signal-code">•••  /  •••</span>
            </div>
            <div className="identity-signal">
              <span className="identity-ring identity-ring-outer" />
              <span className="identity-ring identity-ring-inner" />
              <span className="identity-core" />
            </div>
            <div className="face-signal">
              <span className="face-signal-head" />
              <span className="face-signal-shoulders" />
            </div>
            <div className="decision-signal">
              <span className="decision-signal-kicker">04 / POLICY</span>
              <strong>DECISION</strong>
              <small>verified / review / inconclusive</small>
            </div>
          </div>
          <div className="signal-footer">Models produce evidence. The Decision Engine makes decisions.</div>
        </div>
      </section>

      <section className="capability-section" id="capabilities" aria-labelledby="capability-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">One verification layer</p>
            <h2 id="capability-heading">Three disciplines. One accountable decision.</h2>
          </div>
          <p className="section-intro">Three domains create a coherent path from captured signals to a governed result.</p>
        </div>
        <div className="platform-grid">
          {platformDomains.map(([index, title, description, capabilities]) => (
            <article className="platform-domain" key={title}>
              <span className="platform-index">{index}</span>
              <h3>{title}</h3>
              <p>{description}</p>
              <ul>{capabilities.map((capability) => <li key={capability}>{capability}</li>)}</ul>
            </article>
          ))}
        </div>
      </section>

      <section className="process-section" aria-labelledby="process-heading">
        <div className="section-heading process-heading">
          <div>
            <p className="eyebrow">From evidence to decision</p>
            <h2 id="process-heading">Every decision traces back to the evidence that produced it.</h2>
          </div>
          <p className="section-intro">PaxLI keeps evidence, identity resolution, and final policy evaluation distinct at every step.</p>
        </div>
        <ol className="process-list">
          <li>
            <span className="process-number">01</span>
            <div><h3>Document</h3><p>Capture the identity source and its structured signals.</p></div>
          </li>
          <li>
            <span className="process-number">02</span>
            <div><h3>Evidence</h3><p>Produce quality, extraction, and biometric evidence.</p></div>
          </li>
          <li>
            <span className="process-number">03</span>
            <div><h3>Identity</h3><p>Resolve relationships with explicit provenance.</p></div>
          </li>
          <li>
            <span className="process-number">04</span>
            <div><h3>Biometrics</h3><p>Assess face quality, matching, and bounded liveness.</p></div>
          </li>
          <li>
            <span className="process-number">05</span>
            <div><h3>Decision</h3><p>Apply policy and return the authoritative outcome.</p></div>
          </li>
        </ol>
      </section>

      <section className="value-section" aria-labelledby="value-heading">
        <div className="value-intro">
          <p className="eyebrow">Built for real operations</p>
          <h2 id="value-heading">Trust is a system, not a badge.</h2>
        </div>
        <div className="value-grid">
          <article><span className="value-mark">01</span><h3>Evidence provenance</h3><p>Know where signals came from and how they were connected.</p></article>
          <article><span className="value-mark">02</span><h3>Tenant isolation</h3><p>Keep identity operations scoped to the authenticated context.</p></article>
          <article><span className="value-mark">03</span><h3>Controlled uncertainty</h3><p>VERIFIED, REJECTED, REVIEW_REQUIRED, and INCONCLUSIVE remain meaningful outcomes.</p></article>
        </div>
      </section>

      <section className="demo-note">
        <div>
          <p className="eyebrow">Integration surface</p>
          <h2>Meet PaxLI where your workflow begins.</h2>
        </div>
        <p>
          Start with verification sessions, document processing, identity, biometrics,
          and decisioning through a focused API flow. This dashboard is a demonstration
          surface, not a production assurance claim.
        </p>
      </section>

      <section className="closing-cta" aria-labelledby="closing-heading">
        <div>
          <p className="eyebrow">See the flow in action</p>
          <h2 id="closing-heading">Run a verification demo.</h2>
        </div>
        <NavLink className="primary-action" to="/demo">
          Start Demo <span aria-hidden="true">↗</span>
        </NavLink>
      </section>
    </main>
  );
}

function DemoPage() {
  const { state, dispatch } = useDemoContext();
  const [credential, setCredential] = useState("");
  const [cameraActive, setCameraActive] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // The disabled attribute on the submit button is a UI affordance, not
  // a logic guard -- it only takes effect after React re-renders, and a
  // real double-click (or two rapid clicks) can both fire before that
  // render lands, each independently invoking submitSession(). This ref
  // is checked synchronously, closing that gap regardless of render
  // timing.
  const submittingRef = useRef(false);

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraActive(false);
  };

  useEffect(() => () => stopCamera(), []);

  useEffect(() => {
    if (videoRef.current && streamRef.current) videoRef.current.srcObject = streamRef.current;
  }, [cameraActive]);

  const getClient = () => new PaxliApiClient({
    baseUrl: import.meta.env.VITE_PAXLI_API_BASE_URL ?? "http://localhost:8000",
    credential: credential.trim(),
  });

  const beginSession = async () => {
    if (!credential.trim()) {
      dispatch({ type: "recoverable_error", message: "Enter a temporary demo credential to start a session." });
      return;
    }
    dispatch({ type: "start_demo" });
    try {
      const response = await getClient().createSession();
      dispatch({ type: "session_created", sessionId: response.data.id, requestId: response.meta.request_id });
      dispatch({ type: "timeline", name: "session_created", outcome: "success", requestId: response.meta.request_id, resourceId: response.data.id });
    } catch (error) {
      dispatch({ type: "timeline", name: "session_create_failed", outcome: "failure" });
      dispatch({
        type: "recoverable_error",
        message: error instanceof Error ? error.message : "The verification session could not be created.",
      });
    }
  };

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>, kind: "document" | "selfie") => {
    const file = event.target.files?.[0];
    if (!file || !state.sessionId) return;
    try {
      if (kind === "document") {
        const response = await getClient().uploadDocument(state.sessionId, file);
        dispatch({ type: "document_uploaded", name: file.name });
        dispatch({ type: "timeline", name: "document_upload", outcome: "success", resourceId: response.id });
      } else {
        const response = await getClient().uploadSelfie(state.sessionId, file);
        dispatch({ type: "selfie_uploaded", name: file.name });
        dispatch({ type: "timeline", name: "selfie_upload", outcome: "success", resourceId: response.id });
      }
    } catch (error) {
      dispatch({ type: "timeline", name: `${kind}_upload_failed`, outcome: "failure" });
      dispatch({
        type: "recoverable_error",
        message: error instanceof Error ? error.message : "The evidence could not be uploaded.",
      });
    }
  };

  const startCamera = async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera capture is not available in this browser.");
      streamRef.current = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      setCameraActive(true);
    } catch (error) {
      dispatch({ type: "recoverable_error", message: error instanceof Error ? error.message : "Camera access was not granted." });
      stopCamera();
    }
  };

  const captureCameraSelfie = async () => {
    const video = videoRef.current;
    if (!video || !state.sessionId || video.videoWidth === 0 || video.videoHeight === 0) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    if (!blob) {
      dispatch({ type: "recoverable_error", message: "The camera frame could not be captured." });
      stopCamera();
      return;
    }
    try {
      const file = new File([blob], "camera-selfie.jpg", { type: "image/jpeg" });
      const response = await getClient().uploadSelfie(state.sessionId, file);
      dispatch({ type: "selfie_uploaded", name: file.name });
      dispatch({ type: "timeline", name: "selfie_camera_upload", outcome: "success", resourceId: response.id });
    } catch (error) {
      dispatch({ type: "timeline", name: "selfie_camera_upload_failed", outcome: "failure" });
      dispatch({ type: "recoverable_error", message: error instanceof Error ? error.message : "The camera selfie could not be uploaded." });
    } finally {
      stopCamera();
    }
  };

  const handleLiveness = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0 || !state.sessionId) return;
    const boundedFiles = files.slice(0, 5);
    try {
      const response = await getClient().uploadLiveness(state.sessionId, boundedFiles);
      dispatch({ type: "liveness_uploaded", count: boundedFiles.length });
      dispatch({ type: "timeline", name: "liveness_upload", outcome: "success", resourceId: response.id });
    } catch (error) {
      dispatch({ type: "timeline", name: "liveness_upload_failed", outcome: "failure" });
      dispatch({
        type: "recoverable_error",
        message: error instanceof Error ? error.message : "The Temporal Liveness Demo frames could not be uploaded.",
      });
    }
  };

  const submitSession = async () => {
    if (!state.sessionId || submittingRef.current) return;
    submittingRef.current = true;
    dispatch({ type: "submitting" });
    try {
      const client = getClient();
      const submitted = await client.submitSession(state.sessionId);
      dispatch({ type: "processing" });
      dispatch({ type: "timeline", name: "session_submitted", outcome: "success", requestId: submitted.meta.request_id, resourceId: submitted.data.id });
      let current = submitted.data;
      let requestId = submitted.meta.request_id;

      for (let attempt = 0; attempt < 8; attempt += 1) {
        if (current.status === "COMPLETED" && current.decision) {
          dispatch({ type: "completed", outcome: current.decision.outcome, requestId });
          dispatch({ type: "timeline", name: "session_completed", outcome: "success", requestId, resourceId: current.id });
          return;
        }
        if (current.status === "EXPIRED") {
          dispatch({ type: "expired" });
          return;
        }
        if (current.status === "CANCELLED") {
          dispatch({ type: "cancelled" });
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        const refreshed = await client.getSession(state.sessionId);
        current = refreshed.data;
        requestId = refreshed.meta.request_id;
      }
      dispatch({ type: "recoverable_error", message: "The verification result is still processing. Refresh to check again." });
      dispatch({ type: "timeline", name: "session_poll_timeout", outcome: "retryable", requestId, resourceId: state.sessionId });
    } catch (error) {
      dispatch({ type: "timeline", name: "session_submit_failed", outcome: "failure" });
      dispatch({
        type: "recoverable_error",
        message: error instanceof Error ? error.message : "The verification session could not be completed.",
      });
    } finally {
      submittingRef.current = false;
    }
  };

  const readyToSubmit = Boolean(state.evidenceNames.document && state.evidenceNames.selfie);

  return (
    <main className="page-frame demo-page">
      <section className="demo-shell" aria-labelledby="demo-heading">
        <div className="demo-header">
          <div>
            <p className="eyebrow">Verification console</p>
            <h1 id="demo-heading">Run the PaxLI capture flow.</h1>
          </div>
          <div className="status-pill">{state.status.replace(/_/g, " ")}</div>
        </div>

        <div className="demo-grid">
          <div className="demo-panel">
            {!state.sessionId ? (
              <div className="empty-state">
                <p>Start a verification session to create the active demo flow.</p>
                <label className="credential-field">
                  <span>Temporary demo credential</span>
                  <input
                    type="password"
                    value={credential}
                    onChange={(event) => setCredential(event.target.value)}
                    autoComplete="off"
                    placeholder="credential-id.secret"
                  />
                </label>
                <button className="primary-action demo-button" type="button" onClick={beginSession}>
                  Start session
                </button>
              </div>
            ) : (
              <div className="capture-stack">
                <div className="capture-row">
                  <label className="upload-box" htmlFor="document-upload">
                    <span>Document</span>
                    <strong>{state.evidenceNames.document ?? "Upload document"}</strong>
                  </label>
                  <input id="document-upload" type="file" accept="image/*,.pdf" onChange={(event) => handleFile(event, "document")} />
                </div>

                <div className="capture-row">
                  <label className="upload-box" htmlFor="selfie-upload">
                    <span>Selfie</span>
                    <strong>{state.evidenceNames.selfie ?? "Capture selfie"}</strong>
                  </label>
                  <input id="selfie-upload" type="file" accept="image/*" onChange={(event) => handleFile(event, "selfie")} />
                  <div className="capture-controls">
                    {cameraActive ? (
                      <>
                        <video ref={videoRef} className="camera-preview" autoPlay muted playsInline />
                        <button type="button" className="secondary-action demo-button" onClick={captureCameraSelfie}>Capture camera selfie</button>
                        <button type="button" className="secondary-action demo-button" onClick={stopCamera}>Cancel camera</button>
                      </>
                    ) : (
                      <button type="button" className="secondary-action demo-button" onClick={startCamera}>Use camera</button>
                    )}
                  </div>
                </div>

                <div className="capture-row capture-row-liveness">
                  <label className="upload-box" htmlFor="liveness-upload">
                    <span>Temporal Liveness Demo</span>
                    <strong>{state.evidenceNames.livenessFrames > 0 ? `${state.evidenceNames.livenessFrames} frame(s)` : "Optional frames (max 5)"}</strong>
                  </label>
                  <input id="liveness-upload" type="file" accept="image/*" multiple onChange={handleLiveness} />
                </div>

                <div className="demo-actions">
                  <button type="button" className="secondary-action demo-button" onClick={() => dispatch({ type: "reset" })}>
                    Reset
                  </button>
                  <button
                    type="button"
                    className="primary-action demo-button"
                    disabled={!readyToSubmit || state.status === "submitting" || state.status === "processing"}
                    onClick={submitSession}
                  >
                    {state.status === "submitting" || state.status === "processing" ? "Submitting…" : "Submit session"}
                  </button>
                </div>
              </div>
            )}
          </div>

          <aside className="demo-sidebar">
            <h2>Session state</h2>
            <dl className="meta-list">
              <div>
                <dt>Session ID</dt>
                <dd>{state.sessionId ?? "—"}</dd>
              </div>
              <div>
                <dt>Request ID</dt>
                <dd>{state.requestId ?? "—"}</dd>
              </div>
              <div>
                <dt>Document</dt>
                <dd>{state.evidenceNames.document ? "attached" : "pending"}</dd>
              </div>
              <div>
                <dt>Selfie</dt>
                <dd>{state.evidenceNames.selfie ? "attached" : "pending"}</dd>
              </div>
              <div>
                <dt>Temporal Liveness Demo</dt>
                <dd>{state.evidenceNames.livenessFrames > 0 ? `${state.evidenceNames.livenessFrames} frames` : "not supplied"}</dd>
              </div>
            </dl>

            {state.lastOutcome ? (
              <div className="result-box result-box-success">
                <span className="result-label">Demo outcome</span>
                <strong>{state.lastOutcome}</strong>
                <small>Local demonstration state only — not an authoritative production verdict.</small>
              </div>
            ) : null}

            {state.errorMessage ? (
              <div className="result-box result-box-warning">
                <span className="result-label">Status</span>
                <strong>{state.status}</strong>
                <small>{state.errorMessage}</small>
              </div>
            ) : null}
          </aside>
        </div>
      </section>
    </main>
  );
}

function DiagnosticsPage() {
  const { state } = useDemoContext();

  const entries = state.timeline.length > 0 ? state.timeline : [
    { id: "session-created", name: "session_created", startedAt: "not started", endedAt: null, outcome: "info" as const, requestId: state.requestId ?? undefined },
    { id: "capture-ready", name: "ready_to_submit", startedAt: "pending", endedAt: null, outcome: "pending" as const },
  ];

  return (
    <main className="page-frame diagnostics-page">
      <section className="diagnostics-shell">
        <div className="demo-header">
          <div>
            <p className="eyebrow">Developer diagnostics</p>
            <h1>Safe integration timeline</h1>
          </div>
          <div className="status-pill">local-only</div>
        </div>

        <div className="diagnostics-grid">
          <div className="diagnostics-panel">
            <h2>Lifecycle events</h2>
            <ul className="timeline-list">
              {entries.map((entry) => (
                <li key={entry.id}>
                  <span className={`timeline-marker timeline-marker-${entry.outcome}`} aria-hidden="true" />
                  <div>
                    <strong>{entry.name}</strong>
                    <small>{entry.startedAt}</small>
                    {entry.requestId ? <small>Request: {entry.requestId}</small> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <aside className="diagnostics-panel">
            <h2>Visible metadata</h2>
            <ul className="meta-list compact">
              <li>Session status: {state.status}</li>
              <li>Environment: browser demo</li>
              <li>Method: React + TypeScript + Vite</li>
              <li>Safety boundary: no secret material and no raw media retention</li>
            </ul>
          </aside>
        </div>
      </section>
    </main>
  );
}

function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <main className="placeholder page-frame">
      <p className="eyebrow">PaxLI Demo</p>
      <h1>{title}</h1>
      <p>{description}</p>
      <NavLink className="secondary-action" to="/">
        Back to overview
      </NavLink>
    </main>
  );
}

export function App() {
  const [state, dispatch] = useReducer(demoReducer, initialState);

  return (
    <Shell>
      <DemoContext.Provider value={{ state, dispatch }}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/demo" element={<DemoPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
        </Routes>
      </DemoContext.Provider>
    </Shell>
  );
}
