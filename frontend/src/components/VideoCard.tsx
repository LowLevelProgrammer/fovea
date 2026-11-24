import React from "react";
import { VideoListItem } from "../types/api";
import { formatBytes, formatDuration } from "../utils/format";

type VideoCardProps = {
  video: VideoListItem;
  onClick: () => void;
  enableHoverPreview?: boolean;
};

const HOVER_PREVIEW_FRAMES = 30;
const HOVER_PREVIEW_COLUMNS = 10;
const HOVER_PREVIEW_ROWS = 3;
const HOVER_PREVIEW_FPS = 6;

export function VideoCard({ video, onClick, enableHoverPreview = false }: VideoCardProps) {
  const [thumbnailFailed, setThumbnailFailed] = React.useState(false);
  const [thumbnailAttempt, setThumbnailAttempt] = React.useState(0);
  const [pointerHover, setPointerHover] = React.useState(false);
  const [focusHover, setFocusHover] = React.useState(false);
  const [previewRequested, setPreviewRequested] = React.useState(false);
  const [previewLoaded, setPreviewLoaded] = React.useState(false);
  const [previewFailed, setPreviewFailed] = React.useState(false);
  const [previewFrame, setPreviewFrame] = React.useState(0);
  const [reducedMotion, setReducedMotion] = React.useState(false);
  const thumbnailUrl = video.thumbnail_url || `/api/v1/assets/thumbnails/${video.id}`;
  const hoverPreviewUrl = `/api/v1/assets/hover-previews/${video.id}`;
  const previewActive = pointerHover || focusHover;

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  React.useEffect(() => {
    if (!previewActive || !previewLoaded || reducedMotion) {
      setPreviewFrame(0);
      return;
    }
    const timer = window.setInterval(() => {
      setPreviewFrame((frame) => (frame + 1) % HOVER_PREVIEW_FRAMES);
    }, 1000 / HOVER_PREVIEW_FPS);
    return () => window.clearInterval(timer);
  }, [previewActive, previewLoaded, reducedMotion]);

  const handlePointerEnter = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!enableHoverPreview || event.pointerType === "touch") return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    setPreviewFrame(0);
    setPointerHover(true);
    if (!previewFailed) setPreviewRequested(true);
  };

  const handleFocus = (event: React.FocusEvent<HTMLButtonElement>) => {
    if (!enableHoverPreview || !event.currentTarget.matches(":focus-visible")) return;
    setPreviewFrame(0);
    setFocusHover(true);
    if (!previewFailed) setPreviewRequested(true);
  };

  React.useEffect(() => {
    if (!thumbnailFailed || thumbnailAttempt >= 12) return;

    const timeout = window.setTimeout(() => {
      setThumbnailFailed(false);
      setThumbnailAttempt((attempt) => attempt + 1);
    }, 5000);
    return () => window.clearTimeout(timeout);
  }, [thumbnailAttempt, thumbnailFailed]);
  const progress =
    video.resume_position_seconds != null &&
    video.duration_seconds != null &&
    video.duration_seconds > 0
      ? Math.min(100, (video.resume_position_seconds / video.duration_seconds) * 100)
      : null;

  return (
    <button
      className="video-card"
      onClick={onClick}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={() => setPointerHover(false)}
      onFocus={handleFocus}
      onBlur={() => setFocusHover(false)}
    >
      <div className="card-thumbnail">
        {!thumbnailFailed && (
          <img
            src={`${thumbnailUrl}?attempt=${thumbnailAttempt}`}
            alt=""
            onError={() => setThumbnailFailed(true)}
          />
        )}
        {enableHoverPreview && (
          <div className={`card-hover-preview${previewActive && previewLoaded && !previewFailed ? " is-visible" : ""}`} aria-hidden="true">
            {previewRequested && !previewFailed && (
              <img
                className="card-hover-sheet"
                src={hoverPreviewUrl}
                alt=""
                draggable={false}
                onLoad={() => setPreviewLoaded(true)}
                onError={() => { setPreviewFailed(true); setPreviewLoaded(false); }}
                style={{
                  width: `${HOVER_PREVIEW_COLUMNS * 100}%`,
                  height: `${HOVER_PREVIEW_ROWS * 100}%`,
                  left: `${-(previewFrame % HOVER_PREVIEW_COLUMNS) * 100}%`,
                  top: `${-Math.floor(previewFrame / HOVER_PREVIEW_COLUMNS) * 100}%`,
                }}
              />
            )}
          </div>
        )}
        <span className="play-icon">▶</span>
        {progress !== null && (
          <div className="watch-progress" aria-label={`${Math.round(progress)}% watched`}>
            <span style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
      <div className="card-content">
        <h3 className="card-title" title={video.title}>
          {video.title}
        </h3>
        <div className="card-meta">
          {video.completed && <span className="completion-state">Completed</span>}
          {video.status !== "ready" && (
            <span className={`badge ${video.status}`}>{video.status}</span>
          )}
          <span>{video.duration_seconds != null ? formatDuration(video.duration_seconds) : formatBytes(video.file_size)}</span>
        </div>
        {video.recommendation_reason && (
          <p className="recommendation-reason">{video.recommendation_reason}</p>
        )}
      </div>
    </button>
  );
}
