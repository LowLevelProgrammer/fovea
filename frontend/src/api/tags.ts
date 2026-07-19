import { Tag } from "../types/api";

export async function getTags(): Promise<Tag[]> {
  const response = await fetch("/api/v1/tags");
  if (!response.ok) {
    throw new Error("Failed to load tags.");
  }
  return response.json();
}
