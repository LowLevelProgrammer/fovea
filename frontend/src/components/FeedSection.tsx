import { FeedSection as FeedSectionType } from "../types/api";
import { VideoCard } from "./VideoCard";

type FeedSectionProps = {
  section: FeedSectionType;
  onSelectVideo: (id: string) => void;
};

export function FeedSection({ section, onSelectVideo }: FeedSectionProps) {
  return (
    <section className="feed-section" aria-labelledby={`feed-${section.id}`}>
      <h2 id={`feed-${section.id}`} className="feed-section-title">{section.title}</h2>
      <div className="feed-row">
        {section.items.map((video) => (
          <VideoCard key={video.id} video={video} onClick={() => onSelectVideo(video.id)} />
        ))}
      </div>
    </section>
  );
}
