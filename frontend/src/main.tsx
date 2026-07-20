import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";
import { ReadyResponse } from "./types/api";
import { fetchHealthReady } from "./api/videos";
import { VideoLibraryPage } from "./pages/VideoLibraryPage";
import { VideoDetailPage } from "./pages/VideoDetailPage";
import { HomePage } from "./pages/HomePage";
import { SearchPage } from "./pages/SearchPage";
import { TagsPage } from "./pages/TagsPage";

type Route =
  | { page: "home" }
  | { page: "library" }
  | { page: "search"; query?: string }
  | { page: "tags" }
  | { page: "video"; id: string };

function App() {
  const [health, setHealth] = React.useState<ReadyResponse | null>(null);
  const [healthError, setHealthError] = React.useState(false);
  const [route, setRoute] = React.useState<Route>({ page: "home" });

  // Hash-based client router synchronization
  React.useEffect(() => {
    const parseHash = () => {
      const hash = window.location.hash || "#/";
      const match = hash.match(/^#\/videos\/([a-f0-9\-]{36})$/);
      if (match) {
        setRoute({ page: "video", id: match[1] });
      } else if (hash.startsWith("#/library")) {
        setRoute({ page: "library" });
      } else if (hash.startsWith("#/search")) {
        const query = hash.split("?")[1];
        setRoute({ page: "search", query: query ? new URLSearchParams(query).get("q") ?? "" : "" });
      } else if (hash.startsWith("#/tags")) {
        setRoute({ page: "tags" });
      } else {
        setRoute({ page: "home" });
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

  const navigate = (path: string) => { window.location.hash = path; };

  return (
    <div className="app-container">
      <header className="app-header">
        <button className="logo-container" onClick={handleBack}>
          <span className="logo-icon">▲</span>
          <span className="logo-text">Fovea</span>
        </button>

        <nav className="app-nav" aria-label="Primary navigation">
          <button className={route.page === "home" ? "active" : ""} onClick={() => navigate("#/")}>Home</button>
          <button className={route.page === "library" ? "active" : ""} onClick={() => navigate("#/library")}>Library</button>
          <button className={route.page === "search" ? "active" : ""} onClick={() => navigate("#/search")}>Search</button>
          <button className={route.page === "tags" ? "active" : ""} onClick={() => navigate("#/tags")}>Tags</button>
        </nav>

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
        {route.page === "video" && <VideoDetailPage key={route.id} videoId={route.id} onBack={handleBack} onSelectVideo={handleSelectVideo} />}
        {route.page === "home" && <HomePage onSelectVideo={handleSelectVideo} />}
        {route.page === "library" && <VideoLibraryPage onSelectVideo={handleSelectVideo} />}
        {route.page === "search" && <SearchPage onSelectVideo={handleSelectVideo} initialQuery={route.query} />}
        {route.page === "tags" && <TagsPage onSelectTag={(tagName) => navigate(`#/search?q=${encodeURIComponent(tagName)}`)} />}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
