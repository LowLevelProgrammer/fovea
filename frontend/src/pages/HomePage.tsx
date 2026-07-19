import { ErrorState } from "../components/ErrorState";
import { FeedSection } from "../components/FeedSection";
import { LoadingState } from "../components/LoadingState";
import { useFeed } from "../hooks/useFeed";

type HomePageProps = { onSelectVideo: (id: string) => void };

export function HomePage({ onSelectVideo }: HomePageProps) {
  const { feed, loading, error } = useFeed();
  if (loading) return <LoadingState message="Loading your homepage..." />;
  if (error) return <ErrorState title="Homepage Error" message={error} />;
  if (!feed || feed.sections.length === 0) {
    return <div className="no-videos"><h3>Nothing to discover yet</h3><p>Videos will appear here after your library is scanned.</p></div>;
  }
  return <div className="feed-page">{feed.sections.map((section) => <FeedSection key={section.id} section={section} onSelectVideo={onSelectVideo} />)}</div>;
}
