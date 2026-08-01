import { VideoListResponse, VideoRead, ReadyResponse } from "../types/api";

export async function getVideos(): Promise<VideoListResponse> {
  const response = await fetch("/api/v1/videos?limit=100");
  if (!response.ok) {
    throw new Error("Failed to fetch videos from server.");
  }
  return response.json();
}

export async function getVideoMetadata(videoId: string): Promise<VideoRead> {
  const response = await fetch(`/api/v1/videos/${videoId}`);
  if (response.status === 404) {
    throw { status: 404, message: "Video record not found." };
  }
  if (response.status === 410) {
    throw { status: 410, message: "This video is currently unavailable." };
  }
  if (!response.ok) {
    throw new Error("Server returned an error fetching metadata.");
  }
  return response.json();
}

type ThumbnailRequestResult = {
  status: "pending" | "generating";
  queued: boolean;
};

export async function chooseThumbnail(
  videoId: string,
  timestampSeconds: number
): Promise<ThumbnailRequestResult> {
  const response = await fetch(`/api/v1/videos/${videoId}/thumbnail`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timestamp_seconds: timestampSeconds }),
  });
  if (!response.ok) {
    throw new Error("Failed to queue the thumbnail frame.");
  }
  return response.json();
}

export async function fetchHealthReady(): Promise<{ ok: boolean; data: ReadyResponse }> {
  const response = await fetch("/api/v1/health/ready");
  const data = (await response.json()) as ReadyResponse;
  return { ok: response.ok, data };
}
