import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";

type ReadyResponse = {
  status: string;
  application_name: string;
  application_version: string;
  database: string;
  migration_revision: string | null;
  checked_at: string;
};

function App() {
  const [health, setHealth] = React.useState<ReadyResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const response = await fetch("/api/v1/health/ready");
        const payload = (await response.json()) as ReadyResponse;
        if (!cancelled) {
          setHealth(payload);
          setError(response.ok ? null : "Backend is reachable but not ready.");
        }
      } catch {
        if (!cancelled) {
          setError("Backend is not reachable yet.");
        }
      }
    }

    void loadHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="shell">
      <section className="panel" aria-labelledby="title">
        <p className="eyebrow">Phase 0</p>
        <h1 id="title">{health?.application_name ?? "Fovea"}</h1>
        <p className="summary">
          The application shell is running. Media indexing, playback, discovery, search, and
          generated previews arrive in later phases.
        </p>

        <dl className="status">
          <div>
            <dt>API</dt>
            <dd>{error ? "Not ready" : health?.status ?? "Checking"}</dd>
          </div>
          <div>
            <dt>Database</dt>
            <dd>{health?.database ?? "Checking"}</dd>
          </div>
          <div>
            <dt>Migration</dt>
            <dd>{health?.migration_revision ?? "Pending"}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{health?.application_version ?? "Checking"}</dd>
          </div>
        </dl>

        {error ? <p className="notice">{error}</p> : null}
      </section>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
