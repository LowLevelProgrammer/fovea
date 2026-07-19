import React from "react";
import { getHomeFeed } from "../api/feed";
import { FeedResponse } from "../types/api";

export function useFeed() {
  const [feed, setFeed] = React.useState<FeedResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void getHomeFeed()
      .then((data) => !cancelled && setFeed(data))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  const loadMore = React.useCallback(async () => {
    if (!feed || loadingMore || !feed.recommendations.has_more) return;
    setLoadingMore(true);
    try {
      const nextPage = await getHomeFeed(
        feed.recommendations.offset + feed.recommendations.items.length,
        feed.recommendations.limit
      );
      setFeed((current) => current ? {
        ...current,
        recommendations: {
          ...nextPage.recommendations,
          items: [...current.recommendations.items, ...nextPage.recommendations.items],
        },
      } : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more recommendations.");
    } finally {
      setLoadingMore(false);
    }
  }, [feed, loadingMore]);

  return { feed, loading, loadingMore, error, loadMore };
}
