import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";

type ReadyResponse = {
  status: "ready" | "degraded";
  application_name: string;
  application_version: string;
  api: {
    status: string;
  };
  database: {
    status: string;
    detail: string | null;
  };
  migrations: {
    status: string;
    revision: string | null;
    detail: string | null;
  };
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
          setError(response.ok ? null : "Backend returned an unexpected health response.");
        }
      } catch {
        if (!cancelled) {
          setError("API is not reachable yet.");
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
            <dd>{health?.api.status ?? (error ? "unreachable" : "checking")}</dd>
          </div>
          <div>
            <dt>Database</dt>
            <dd>{health?.database.status ?? "checking"}</dd>
          </div>
          <div>
            <dt>Migration</dt>
            <dd>{health?.migrations.revision ?? health?.migrations.status ?? "checking"}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{health?.application_version ?? "Checking"}</dd>
          </div>
        </dl>

        {health?.status === "degraded" ? (
          <p className="notice">
            API is running, but readiness is degraded. {health.database.detail ?? health.migrations.detail}
          </p>
        ) : null}
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
