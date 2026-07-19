import React from "react";
import { searchVideos } from "../api/search";
import { VideoListItem } from "../types/api";

const SEARCH_DELAY_MS = 300;

export function useSearch(query: string) {
  const [results, setResults] = React.useState<VideoListItem[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    const timeout = window.setTimeout(() => {
      void searchVideos(trimmedQuery)
        .then((data) => !cancelled && setResults(data))
        .catch((err: Error) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false));
    }, SEARCH_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [query]);

  return { results, loading, error };
}
