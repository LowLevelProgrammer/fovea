import React from "react";
import { getSimilarVideos } from "../api/similarity";
import { SimilarVideoItem } from "../types/api";

export function useSimilarVideos(videoId: string) {
  const [videos, setVideos] = React.useState<SimilarVideoItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getSimilarVideos(videoId)
      .then((data) => !cancelled && setVideos(data.items))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [videoId]);

  return { videos, loading, error };
}
