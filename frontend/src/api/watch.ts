export async function updateWatchProgress(
  videoId: string,
  positionSeconds: number,
  durationSeconds: number | null,
  useKeepAlive = false
): Promise<boolean> {
  const response = await fetch(`/api/v1/watch/sessions/${videoId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      position_seconds: positionSeconds,
      duration_seconds: durationSeconds,
    }),
    keepalive: useKeepAlive,
  });
  return response.ok;
}
