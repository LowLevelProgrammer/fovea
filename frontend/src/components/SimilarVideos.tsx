import { SimilarVideoItem } from "../types/api";
import { VideoCard } from "./VideoCard";

type SimilarVideosProps = {
  videos: SimilarVideoItem[];
  onSelectVideo: (id: string) => void;
};

export function SimilarVideos({ videos, onSelectVideo }: SimilarVideosProps) {
  if (videos.length === 0) return null;
  return (
    <section className="similar-videos" aria-labelledby="similar-videos-title">
      <h2 id="similar-videos-title" className="feed-section-title">Similar Videos</h2>
      <div className="similar-videos-grid">
        {videos.map((video) => (
          <VideoCard
            key={video.id}
            video={{ ...video, recommendation_reason: video.similarity_reason }}
            onClick={() => onSelectVideo(video.id)}
          />
        ))}
      </div>
    </section>
  );
}
