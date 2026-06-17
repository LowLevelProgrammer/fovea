import React from "react";
import { VideoListItem } from "../types/api";
import { formatBytes } from "../utils/format";

type VideoCardProps = {
  video: VideoListItem;
  onClick: () => void;
};

export function VideoCard({ video, onClick }: VideoCardProps) {
  return (
    <button className="video-card" onClick={onClick}>
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
  );
}
