import React from "react";
import { VideoListItem } from "../types/api";
import { formatBytes, formatDuration } from "../utils/format";

type VideoCardProps = {
  video: VideoListItem;
  onClick: () => void;
};

export function VideoCard({ video, onClick }: VideoCardProps) {
  const [thumbnailFailed, setThumbnailFailed] = React.useState(false);
  const [thumbnailAttempt, setThumbnailAttempt] = React.useState(0);
  const thumbnailUrl = video.thumbnail_url || `/api/v1/assets/thumbnails/${video.id}`;

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
    <button className="video-card" onClick={onClick}>
      <div className="card-thumbnail">
        {!thumbnailFailed && (
          <img
            src={`${thumbnailUrl}?attempt=${thumbnailAttempt}`}
            alt=""
            onError={() => setThumbnailFailed(true)}
          />
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
