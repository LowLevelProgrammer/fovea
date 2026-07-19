import React from "react";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { SearchBar } from "../components/SearchBar";
import { VideoCard } from "../components/VideoCard";
import { useSearch } from "../hooks/useSearch";

type SearchPageProps = { onSelectVideo: (id: string) => void; initialQuery?: string };

export function SearchPage({ onSelectVideo, initialQuery = "" }: SearchPageProps) {
  const [query, setQuery] = React.useState(initialQuery);
  React.useEffect(() => { setQuery(initialQuery); }, [initialQuery]);
  const { results, loading, error } = useSearch(query);
  const trimmedQuery = query.trim();
  return (
    <div>
      <div className="page-header"><h2 className="page-title">Search</h2></div>
      <SearchBar value={query} onChange={setQuery} autoFocus />
      {!trimmedQuery && <div className="no-videos search-empty"><h3>Find something to watch</h3><p>Search titles, file names, and tags.</p></div>}
      {loading && <LoadingState message="Searching library..." />}
      {error && <ErrorState title="Search Error" message={error} />}
      {trimmedQuery && !loading && !error && results.length === 0 && <div className="no-videos search-empty"><h3>No matches found</h3><p>Try a different title, filename, or tag.</p></div>}
      {results.length > 0 && !loading && <div className="video-grid search-results">{results.map((video) => <VideoCard key={video.id} video={video} onClick={() => onSelectVideo(video.id)} />)}</div>}
    </div>
  );
}
