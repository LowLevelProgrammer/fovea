import React from "react";
import { VideoListItem } from "../types/api";
import { getVideos } from "../api/videos";
import { VideoCard } from "../components/VideoCard";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";

type VideoLibraryPageProps = {
  onSelectVideo: (id: string) => void;
};

export function VideoLibraryPage({ onSelectVideo }: VideoLibraryPageProps) {
  const [videos, setVideos] = React.useState<VideoListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function fetchVideos() {
      try {
        const data = await getVideos();
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
    return <LoadingState message="Loading library..." />;
  }

  if (error) {
    return <ErrorState title="Library Error" message={error} />;
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
            <VideoCard
              key={video.id}
              video={video}
              onClick={() => onSelectVideo(video.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
