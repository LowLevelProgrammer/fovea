import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";
import { ReadyResponse } from "./types/api";
import { fetchHealthReady } from "./api/videos";
import { VideoLibraryPage } from "./pages/VideoLibraryPage";
import { VideoDetailPage } from "./pages/VideoDetailPage";

function App() {
  const [health, setHealth] = React.useState<ReadyResponse | null>(null);
  const [healthError, setHealthError] = React.useState(false);
  const [currentVideoId, setCurrentVideoId] = React.useState<string | null>(null);

  // Hash-based client router synchronization
  React.useEffect(() => {
    const parseHash = () => {
      const hash = window.location.hash;
      const match = hash.match(/^#\/videos\/([a-f0-9\-]{36})$/);
      if (match) {
        setCurrentVideoId(match[1]);
      } else {
        setCurrentVideoId(null);
      }
    };

    window.addEventListener("hashchange", parseHash);
    parseHash(); // Check initial route
    return () => window.removeEventListener("hashchange", parseHash);
  }, []);

  React.useEffect(() => {
    async function loadHealth() {
      try {
        const { ok, data } = await fetchHealthReady();
        setHealth(data);
        setHealthError(!ok);
      } catch {
        setHealthError(true);
      }
    }
    void loadHealth();
  }, []);

  const handleSelectVideo = (id: string) => {
    window.location.hash = `#/videos/${id}`;
  };

  const handleBack = () => {
    window.location.hash = "#/";
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <button className="logo-container" onClick={handleBack}>
          <span className="logo-icon">▲</span>
          <span className="logo-text">Fovea</span>
        </button>

        <div className="health-status">
          <span
            className={`status-dot ${
              healthError
                ? "unreachable"
                : health?.status === "degraded"
                  ? "degraded"
                  : "healthy"
            }`}
          />
          <span>
            {healthError
              ? "Backend Offline"
              : health?.status === "degraded"
                ? "API Degraded"
                : "Backend Online"}
          </span>
        </div>
      </header>

      <main className="app-main">
        {currentVideoId ? (
          <VideoDetailPage key={currentVideoId} videoId={currentVideoId} onBack={handleBack} />
        ) : (
          <VideoLibraryPage onSelectVideo={handleSelectVideo} />
        )}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
