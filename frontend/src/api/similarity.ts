import { SimilarVideosResponse } from "../types/api";

export async function getSimilarVideos(videoId: string): Promise<SimilarVideosResponse> {
  const response = await fetch(`/api/v1/videos/${videoId}/similar`);
  if (!response.ok) {
    throw new Error("Failed to load similar videos.");
  }
  return response.json();
}
