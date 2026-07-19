import React from "react";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { VideoCard } from "../components/VideoCard";
import { useFeed } from "../hooks/useFeed";

type HomePageProps = { onSelectVideo: (id: string) => void };

export function HomePage({ onSelectVideo }: HomePageProps) {
  const { feed, loading, loadingMore, error, loadMore } = useFeed();
  const sentinelRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !feed?.recommendations.has_more || loadingMore) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void loadMore();
    }, { rootMargin: "320px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [feed?.recommendations.has_more, loadMore, loadingMore]);
  if (loading) return <LoadingState message="Loading your homepage..." />;
  if (error) return <ErrorState title="Homepage Error" message={error} />;
  if (!feed || (feed.continue_watching.length === 0 && feed.recommendations.items.length === 0)) {
    return <div className="no-videos"><h3>Nothing to discover yet</h3><p>Videos will appear here after your library is scanned.</p></div>;
  }
  return (
    <div className="discovery-page">
      {feed.continue_watching.length > 0 && (
        <section className="continue-watching" aria-labelledby="continue-watching-title">
          <h2 id="continue-watching-title" className="feed-section-title">Continue Watching</h2>
          <div className="feed-row">
            {feed.continue_watching.map((video) => <VideoCard key={video.id} video={video} onClick={() => onSelectVideo(video.id)} />)}
          </div>
        </section>
      )}
      <section aria-label="Recommended videos">
        <div className="discovery-grid">
          {feed.recommendations.items.map((video) => <VideoCard key={video.id} video={video} onClick={() => onSelectVideo(video.id)} />)}
        </div>
        {feed.recommendations.has_more && <div className="feed-sentinel" ref={sentinelRef}>{loadingMore && <LoadingState message="Loading more videos..." />}</div>}
      </section>
    </div>
  );
}
