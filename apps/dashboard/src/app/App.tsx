import { NavLink, Route, Routes } from "react-router-dom";

const capabilities = [
  ["Document Verification", "Quality, classification, and structured extraction."],
  ["OCR", "Extract relevant information from a document capture."],
  ["MRZ & Barcode", "Read machine-readable document data where present."],
  ["Field Reconciliation", "Compare fields across document-derived sources."],
  ["Face Verification", "Compare a resolved reference face with a submitted selfie."],
  ["Face Quality Assessment", "Assess whether a captured face is usable for processing."],
  ["Temporal Liveness Demo", "Explore a bounded multi-frame heuristic path."],
  ["Verification Decisioning", "Evaluate evidence through the governed workflow."],
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
        <div className="signal-panel" aria-label="Verification pipeline overview">
          <div className="signal-orbit signal-orbit-one" aria-hidden="true" />
          <div className="signal-orbit signal-orbit-two" aria-hidden="true" />
          <div className="signal-header">
            <span className="status-dot" aria-hidden="true" />
            <span>Verification path</span>
            <span className="signal-state">DEMO</span>
          </div>
          <div className="pipeline-list">
            <div><span>01</span><strong>DOCUMENT</strong><small>quality + extraction</small></div>
            <div><span>02</span><strong>BIOMETRIC</strong><small>reference + selfie</small></div>
            <div><span>03</span><strong>DECISION</strong><small>policy evaluation</small></div>
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
          {capabilities.map(([title, description], index) => (
            <article className="capability-item" key={title}>
              <span className="capability-index">0{index + 1}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
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
