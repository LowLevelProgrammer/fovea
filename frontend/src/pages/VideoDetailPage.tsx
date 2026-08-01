import React from "react";
import { VideoRead } from "../types/api";
import { chooseThumbnail, getVideoMetadata } from "../api/videos";
import { VideoPlayer } from "../components/VideoPlayer";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { useWatchProgress } from "../hooks/useWatchProgress";
import { formatBytes } from "../utils/format";
import { SimilarVideos } from "../components/SimilarVideos";
import { useSimilarVideos } from "../hooks/useSimilarVideos";

type VideoDetailPageProps = {
  videoId: string;
  onBack: () => void;
  onSelectVideo: (id: string) => void;
};

export function VideoDetailPage({ videoId, onBack, onSelectVideo }: VideoDetailPageProps) {
  const [video, setVideo] = React.useState<VideoRead | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<{ status: number; message: string } | null>(null);
  const [thumbnailMessage, setThumbnailMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function fetchVideoMetadata() {
      try {
        const data = await getVideoMetadata(videoId);
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
          if (err && typeof err.status === "number") {
            setError({ status: err.status, message: err.message });
          } else {
            setError({ status: 500, message: err.message || "Failed to load metadata." });
          }
          setLoading(false);
        }
      }
    }

    void fetchVideoMetadata();
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  const resumePosition = video ? video.resume_position_seconds : null;
  const { videoRef, handleLoadedMetadata, handlePlay, handlePauseOrEnded } =
    useWatchProgress(videoId, resumePosition);
  const similarVideos = useSimilarVideos(videoId);

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

  const handleChooseThumbnail = async () => {
    const timestamp = videoRef.current?.currentTime;
    if (timestamp == null || !Number.isFinite(timestamp)) return;
    try {
      const result = await chooseThumbnail(videoId, timestamp);
      setThumbnailMessage(
        result.queued
          ? "Thumbnail generation queued for the current frame."
          : result.status === "generating"
            ? "A thumbnail is already being generated. Try again in a moment."
            : "A thumbnail request is already pending."
      );
    } catch (err) {
      setThumbnailMessage(err instanceof Error ? err.message : "Failed to queue the thumbnail frame.");
    }
  };

  if (loading && !error) {
    return <LoadingState message="Loading metadata..." />;
  }

  if (error) {
    return (
      <div className="detail-container">
        <button className="back-button" onClick={onBack}>
          ← Back to Library
        </button>
        <ErrorState
          title={
            error.status === 404
              ? "404 Not Found"
              : error.status === 410
                ? "410 Unavailable"
                : "Error Loading Video"
          }
          message={error.message}
        />
      </div>
    );
  }

  if (!video) return null;

  return (
    <div className="detail-container">
      <button className="back-button" onClick={onBack}>
        ← Back to Library
      </button>

      <VideoPlayer
        ref={videoRef}
        src={`/api/v1/videos/${video.id}/stream`}
        onLoadedMetadata={handleLoadedMetadata}
        onPlay={handlePlay}
        onPause={handlePauseOrEnded}
        onEnded={handlePauseOrEnded}
        onError={handleVideoError}
      />

      <div className="video-info-card">
        <div className="video-detail-header">
          <div>
            <h2 className="video-detail-title">{video.title}</h2>
            {thumbnailMessage && <p className="thumbnail-message">{thumbnailMessage}</p>}
          </div>
          <div className="video-detail-actions">
            <button className="back-button" onClick={() => void handleChooseThumbnail()}>
              Use current frame
            </button>
            <span className={`badge ${video.status}`}>{video.status}</span>
          </div>
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

      {!similarVideos.loading && !similarVideos.error && (
        <SimilarVideos videos={similarVideos.videos} onSelectVideo={onSelectVideo} />
      )}
    </div>
  );
}
