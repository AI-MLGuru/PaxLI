import { NavLink, Route, Routes } from "react-router-dom";

const capabilities = [
  ["Document Verification", "Quality, classification, and structured extraction.", "document"],
  ["OCR", "Extract relevant information from a document capture.", "ocr"],
  ["MRZ & Barcode", "Read machine-readable document data where present.", "scan"],
  ["Field Reconciliation", "Compare fields across document-derived sources.", "reconcile"],
  ["Face Verification", "Compare a resolved reference face with a submitted selfie.", "face"],
  ["Face Quality Assessment", "Assess whether a captured face is usable for processing.", "quality"],
  ["Temporal Liveness Demo", "Explore a bounded multi-frame heuristic path.", "temporal"],
  ["Verification Decisioning", "Evaluate evidence through the governed workflow.", "decision"],
] as const;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="wordmark" to="/">
          <span className="wordmark-mark">P</span>
          <span>PaxLI</span>
        </NavLink>
        <nav aria-label="Primary navigation">
          <NavLink className="nav-link" to="/demo">
            Start Demo
          </NavLink>
          <NavLink className="nav-link nav-link-muted" to="/diagnostics">
            Diagnostics
          </NavLink>
        </nav>
      </header>
      {children}
      <footer className="footer">
        <span>PaxLI Demo</span>
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
          <p className="eyebrow">PaxLI by PaxAlpha</p>
          <h1>Identity verification, designed for confidence.</h1>
          <p className="hero-description">
            Explore a working demonstration of document intelligence, biometric
            evidence, and policy-governed verification decisioning.
          </p>
          <div className="hero-actions">
            <NavLink className="primary-action" to="/demo">
              Start Demo <span aria-hidden="true">↗</span>
            </NavLink>
            <a className="secondary-action" href="#capabilities">
              Explore capabilities <span aria-hidden="true">↓</span>
            </a>
          </div>
          <p className="privacy-note">
            Media is sent to the verification API for the active session. This
            browser does not retain captured media after the flow ends.
          </p>
        </div>
        <div className="signal-panel" role="img" aria-label="Abstract verification flow from document and face signals to a policy decision">
          <div className="signal-header">
            <span className="status-dot" aria-hidden="true" />
            <span>Verification path</span>
            <span className="signal-state">DEMO</span>
          </div>
          <div className="verification-visual" aria-hidden="true">
            <span className="visual-grid" />
            <span className="flow-line flow-line-one" />
            <span className="flow-line flow-line-two" />
            <span className="flow-line flow-line-three" />
            <span className="scan-line" />
            <div className="visual-caption visual-caption-document">document</div>
            <div className="visual-caption visual-caption-face">face signal</div>
            <div className="document-signal">
              <span className="document-signal-top">PAXLI / ID</span>
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
              <span className="decision-signal-kicker">03 / POLICY</span>
              <strong>DECISION</strong>
              <small>evidence projection</small>
            </div>
          </div>
          <div className="signal-footer">Models produce evidence. The Decision Engine makes decisions.</div>
        </div>
      </section>

      <section className="capability-section" id="capabilities" aria-labelledby="capability-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Capability catalogue</p>
            <h2 id="capability-heading">A verification path you can inspect.</h2>
          </div>
          <p className="section-intro">Evidence stays distinct from the final outcome, so each part of the flow remains explainable.</p>
        </div>
        <div className="capability-grid">
          {capabilities.map(([title, description, icon], index) => (
            <article className="capability-item" key={title}>
              <div className="capability-meta">
                <span className={`capability-icon capability-icon-${icon}`} aria-hidden="true" />
                <span className="capability-index">0{index + 1}</span>
              </div>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="process-section" aria-labelledby="process-heading">
        <div className="section-heading process-heading">
          <div>
            <p className="eyebrow">How it works</p>
            <h2 id="process-heading">From capture to a decision you can inspect.</h2>
          </div>
          <p className="section-intro">The flow keeps evidence, processing, and final decisioning distinct at every step.</p>
        </div>
        <ol className="process-list">
          <li>
            <span className="process-number">01</span>
            <div><h3>Capture</h3><p>Collect a document, selfie, and optional Temporal Liveness Demo frames.</p></div>
          </li>
          <li>
            <span className="process-number">02</span>
            <div><h3>Process</h3><p>Run the configured document and biometric evidence pipeline.</p></div>
          </li>
          <li>
            <span className="process-number">03</span>
            <div><h3>Reconcile</h3><p>Compare fields and connect evidence through explicit provenance.</p></div>
          </li>
          <li>
            <span className="process-number">04</span>
            <div><h3>Evaluate</h3><p>Apply the relevant immutable policy to the available evidence.</p></div>
          </li>
          <li>
            <span className="process-number">05</span>
            <div><h3>Decision</h3><p>Retrieve the authoritative outcome from the completed session.</p></div>
          </li>
        </ol>
      </section>

      <section className="value-section" aria-labelledby="value-heading">
        <div className="value-intro">
          <p className="eyebrow">Why PaxLI</p>
          <h2 id="value-heading">Useful clarity for the people building and reviewing verification.</h2>
        </div>
        <div className="value-grid">
          <article><span className="value-mark">01</span><h3>Fast integration</h3><p>A focused API flow keeps the path from session creation to result retrieval easy to follow.</p></article>
          <article><span className="value-mark">02</span><h3>Clear evidence</h3><p>Document and biometric signals remain evidence, not accidental final verdicts.</p></article>
          <article><span className="value-mark">03</span><h3>Traceable decisions</h3><p>Decisioning is returned as a durable session result with policy context and reason codes.</p></article>
        </div>
      </section>

      <section className="demo-note">
        <div>
          <p className="eyebrow">Privacy and scope</p>
          <h2>Built for careful evaluation.</h2>
        </div>
        <p>
          This is a demonstration surface, not a production assurance claim. The
          optional Temporal Liveness Demo uses a bounded heuristic path and is not
          production presentation-attack detection. Captured media is used for the
          active session and is not stored in browser storage, URLs, or diagnostics.
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
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route
          path="/demo"
          element={<PlaceholderPage title="Verification Demo" description="The capture workflow is coming next." />}
        />
        <Route
          path="/diagnostics"
          element={<PlaceholderPage title="Developer Diagnostics" description="The safe integration timeline will appear here." />}
        />
      </Routes>
    </Shell>
  );
}
