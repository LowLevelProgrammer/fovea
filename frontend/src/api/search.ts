import { VideoListItem } from "../types/api";

export async function searchVideos(query: string): Promise<VideoListItem[]> {
  const response = await fetch(`/api/v1/search?q=${encodeURIComponent(query)}`);
  if (!response.ok) {
    throw new Error("Failed to search the library.");
  }
  return response.json();
}
