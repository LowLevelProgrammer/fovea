import React from "react";
import { getTags } from "../api/tags";
import { Tag } from "../types/api";

export function useTags() {
  const [tags, setTags] = React.useState<Tag[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void getTags()
      .then((data) => !cancelled && setTags(data))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  return { tags, loading, error };
}
