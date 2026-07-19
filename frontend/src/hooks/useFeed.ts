import React from "react";
import { getHomeFeed } from "../api/feed";
import { FeedResponse } from "../types/api";

export function useFeed() {
  const [feed, setFeed] = React.useState<FeedResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void getHomeFeed()
      .then((data) => !cancelled && setFeed(data))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  return { feed, loading, error };
}
