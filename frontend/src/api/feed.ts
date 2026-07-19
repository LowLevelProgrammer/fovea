import { FeedResponse } from "../types/api";

export async function getHomeFeed(offset = 0, limit = 24): Promise<FeedResponse> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  const response = await fetch(`/api/v1/feed/home?${params}`);
  if (!response.ok) {
    throw new Error("Failed to load the homepage feed.");
  }
  return response.json();
}
