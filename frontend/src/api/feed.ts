import { FeedResponse } from "../types/api";

export async function getHomeFeed(): Promise<FeedResponse> {
  const response = await fetch("/api/v1/feed/home");
  if (!response.ok) {
    throw new Error("Failed to load the homepage feed.");
  }
  return response.json();
}
