import React from "react";
import ReactDOM from "react-dom/client";

import "./styles.css";

// --- Types ---

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

type VideoListItem = {
  id: string;
  file_path: string;
  title: string;
  file_size: number;
  status: string;
  added_at: string;
  last_seen_at: string;
};

type VideoListResponse = {
  items: VideoListItem[];
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
};

type VideoRead = {
  id: string;
  file_path: string;
  title: string;
  title_override: string | null;
  file_size: number;
  file_mtime: string;
  fingerprint: string | null;
  status: string;
  added_at: string;
  last_seen_at: string;
  unavailable_since: string | null;
  watch_count: number;
  last_watched_at: string | null;
  created_at: string;
  updated_at: string;
  resume_position_seconds: number | null;
};

// --- Helper Utilities ---

function formatBytes(bytes: number, decimals = 2) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
}

// --- Components ---

function VideoLibraryPage({ onSelectVideo }: { onSelectVideo: (id: string) => void }) {
  const [videos, setVideos] = React.useState<VideoListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function fetchVideos() {
      try {
        const response = await fetch("/api/v1/videos?limit=100");
        if (!response.ok) {
          throw new Error("Failed to fetch videos from server.");
        }
        const data = (await response.json()) as VideoListResponse;
        if (!cancelled) {
          setVideos(data.items);
          setLoading(false);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err.message || "Failed to load library.");
          setLoading(false);
        }
      }
    }

    void fetchVideos();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="loading-spinner">
        <div className="spinner"></div>
        <span>Loading library...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-card">
        <div className="error-title">Library Error</div>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Media Library</h2>
      </div>

      {videos.length === 0 ? (
        <div className="no-videos">
          <h3>No videos indexed yet</h3>
          <p style={{ marginTop: "8px", fontSize: "0.875rem" }}>
            Add paths to the watch directory and wait for the scanner to populate.
          </p>
        </div>
      ) : (
        <div className="video-grid">
          {videos.map((video) => (
            <button
              key={video.id}
              className="video-card"
              onClick={() => onSelectVideo(video.id)}
            >
              <div className="card-thumbnail">
                <span className="play-icon">▶</span>
              </div>
              <div className="card-content">
                <h3 className="card-title" title={video.title}>
                  {video.title}
                </h3>
                <div className="card-meta">
                  {video.status !== "ready" && (
                    <span className={`badge ${video.status}`}>{video.status}</span>
                  )}
                  <span>{formatBytes(video.file_size)}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function VideoDetailPage({ videoId, onBack }: { videoId: string; onBack: () => void }) {
  const [video, setVideo] = React.useState<VideoRead | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<{ status: number; message: string } | null>(null);
  const [hasSeeked, setHasSeeked] = React.useState(false);

  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const intervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSavedPositionRef = React.useRef<number | null>(null);

  // Memoized progress saving function
  const saveProgress = React.useCallback(
    async (currentTime: number, duration: number, useKeepAlive = false) => {
      let dur = isNaN(duration) || !isFinite(duration) ? null : duration;
      let pos = isNaN(currentTime) || !isFinite(currentTime) ? 0 : currentTime;
      if (pos < 0) pos = 0;
      if (dur !== null && pos > dur) pos = dur;

      // Deduplicate: skip if this position was already saved recently (tolerance 10ms)
      if (
        lastSavedPositionRef.current !== null &&
        Math.abs(lastSavedPositionRef.current - pos) < 0.01
      ) {
        return;
      }

      // Optimistically update the last saved position to prevent concurrent duplicates
      const previousSavedPosition = lastSavedPositionRef.current;
      lastSavedPositionRef.current = pos;

      try {
        const response = await fetch(`/api/v1/watch/sessions/${videoId}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            position_seconds: pos,
            duration_seconds: dur,
          }),
          keepalive: useKeepAlive,
        });

        if (!response.ok) {
          // Revert to the previous saved position if the server rejected the save
          lastSavedPositionRef.current = previousSavedPosition;
        }
      } catch (err) {
        console.error("Failed to save watch progress:", err);
        // Revert to the previous saved position on network/fetch failure
        lastSavedPositionRef.current = previousSavedPosition;
      }
    },
    [videoId]
  );

  React.useEffect(() => {
    let cancelled = false;

    async function fetchVideoMetadata() {
      try {
        const response = await fetch(`/api/v1/videos/${videoId}`);
        if (response.status === 404) {
          if (!cancelled) setError({ status: 404, message: "Video record not found." });
          return;
        }
        if (response.status === 410) {
          if (!cancelled) setError({ status: 410, message: "This video is currently unavailable." });
          return;
        }
        if (!response.ok) {
          throw new Error("Server returned an error fetching metadata.");
        }

        const data = (await response.json()) as VideoRead;
        if (!cancelled) {
          // Double check if backend marked it as unavailable
          if (data.status === "unavailable") {
            setError({ status: 410, message: "This video is marked as unavailable." });
          } else {
            setVideo(data);
          }
          setLoading(false);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError({ status: 500, message: err.message || "Failed to load metadata." });
          setLoading(false);
        }
      }
    }

    void fetchVideoMetadata();
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  // Clean up and save final progress on page unmount
  React.useEffect(() => {
    const currentVideo = videoRef.current;
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      if (currentVideo) {
        void saveProgress(currentVideo.currentTime, currentVideo.duration);
      }
    };
  }, [videoId, saveProgress]);

  // Save progress on page unload/tab close using pagehide & keepalive fetch
  React.useEffect(() => {
    const handlePageHide = () => {
      if (videoRef.current) {
        void saveProgress(videoRef.current.currentTime, videoRef.current.duration, true);
      }
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [saveProgress]);


  const handleLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const player = e.currentTarget;
    if (
      video?.resume_position_seconds &&
      video.resume_position_seconds > 0 &&
      !hasSeeked
    ) {
      player.currentTime = video.resume_position_seconds;
      setHasSeeked(true);
    }
  };

  const handlePlay = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    intervalRef.current = setInterval(() => {
      if (videoRef.current) {
        void saveProgress(videoRef.current.currentTime, videoRef.current.duration);
      }
    }, 10000);
  };

  const handlePauseOrEnded = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (videoRef.current) {
      void saveProgress(videoRef.current.currentTime, videoRef.current.duration);
    }
  };

  const handleVideoError = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const videoElement = e.currentTarget;
    const mediaError = videoElement.error;
    let message = "An unknown error occurred during video playback.";
    if (mediaError) {
      switch (mediaError.code) {
        case 1:
          message = "Playback aborted by user or browser.";
          break;
        case 2:
          message = "A network error caused the video download to fail.";
          break;
        case 3:
          message = "The video playback was aborted due to a corruption problem or because the video used features your browser did not support.";
          break;
        case 4:
          message = "The video could not be loaded, either because the server or network failed or because the format is not supported.";
          break;
      }
      if (mediaError.message) {
        message += ` (Details: ${mediaError.message})`;
      }
    }
    setError({ status: 500, message });
  };

  if (loading && !error) {
    return (
      <div className="loading-spinner">
        <div className="spinner"></div>
        <span>Loading metadata...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="detail-container">
        <button className="back-button" onClick={onBack}>
          ← Back to Library
        </button>
        <div className="error-card">
          <div className="error-title">
            {error.status === 404
              ? "404 Not Found"
              : error.status === 410
                ? "410 Unavailable"
                : "Error Loading Video"}
          </div>
          <p className="error-message">{error.message}</p>
        </div>
      </div>
    );
  }

  if (!video) return null;

  return (
    <div className="detail-container">
      <button className="back-button" onClick={onBack}>
        ← Back to Library
      </button>

      <div className="video-player-container">
        <video
          ref={videoRef}
          className="video-player"
          controls
          src={`/api/v1/videos/${video.id}/stream`}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={handlePlay}
          onPause={handlePauseOrEnded}
          onEnded={handlePauseOrEnded}
          onError={handleVideoError}
        />
      </div>

      <div className="video-info-card">
        <div className="video-detail-header">
          <h2 className="video-detail-title">{video.title}</h2>
          <span className={`badge ${video.status}`}>{video.status}</span>
        </div>

        <div className="video-detail-metadata">
          <span>
            <strong>File Path</strong>
            {video.file_path}
          </span>
          <span>
            <strong>File Size</strong>
            {formatBytes(video.file_size)}
          </span>
          <span>
            <strong>Date Added</strong>
            {new Date(video.added_at).toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}

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
        const response = await fetch("/api/v1/health/ready");
        const payload = (await response.json()) as ReadyResponse;
        setHealth(payload);
        setHealthError(!response.ok);
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
