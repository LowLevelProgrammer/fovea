import React from "react";
import { updateWatchProgress } from "../api/watch";

export function useWatchProgress(videoId: string, resumePositionSeconds: number | null) {
  const [hasSeeked, setHasSeeked] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const intervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSavedPositionRef = React.useRef<number | null>(null);

  // Memoized progress saving function
  const saveProgress = React.useCallback(
    async (currentTime: number, duration: number, useKeepAlive = false) => {
      let dur = isNaN(duration) || !isFinite(duration) ? null : duration;
      let pos = isNaN(currentTime) || !isFinite(currentTime) ? 0 : currentTime;
      if (pos < 0) pos = 0;
      if (dur !== null && pos > dur) pos = dur;

      // Deduplicate: skip if this position was already saved recently (tolerance 10ms)
      if (
        lastSavedPositionRef.current !== null &&
        Math.abs(lastSavedPositionRef.current - pos) < 0.01
      ) {
        return;
      }

      // Optimistically update the last saved position to prevent concurrent duplicates
      const previousSavedPosition = lastSavedPositionRef.current;
      lastSavedPositionRef.current = pos;

      try {
        const ok = await updateWatchProgress(videoId, pos, dur, useKeepAlive);
        if (!ok) {
          // Revert to the previous saved position if the server rejected the save
          lastSavedPositionRef.current = previousSavedPosition;
        }
      } catch (err) {
        console.error("Failed to save watch progress:", err);
        // Revert to the previous saved position on network/fetch failure
        lastSavedPositionRef.current = previousSavedPosition;
      }
    },
    [videoId]
  );

  // Clean up and save final progress on page unmount
  React.useEffect(() => {
    const currentVideo = videoRef.current;
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      if (currentVideo) {
        void saveProgress(currentVideo.currentTime, currentVideo.duration);
      }
    };
  }, [videoId, saveProgress]);

  // Save progress on page unload/tab close using pagehide & keepalive fetch
  React.useEffect(() => {
    const handlePageHide = () => {
      if (videoRef.current) {
        void saveProgress(videoRef.current.currentTime, videoRef.current.duration, true);
      }
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [saveProgress]);

  const handleLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const player = e.currentTarget;
    if (
      resumePositionSeconds &&
      resumePositionSeconds > 0 &&
      !hasSeeked
    ) {
      player.currentTime = resumePositionSeconds;
      setHasSeeked(true);
    }
  };

  const handlePlay = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    intervalRef.current = setInterval(() => {
      if (videoRef.current) {
        void saveProgress(videoRef.current.currentTime, videoRef.current.duration);
      }
    }, 10000);
  };

  const handlePauseOrEnded = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (videoRef.current) {
      void saveProgress(videoRef.current.currentTime, videoRef.current.duration);
    }
  };

  return {
    videoRef,
    handleLoadedMetadata,
    handlePlay,
    handlePauseOrEnded,
  };
}
