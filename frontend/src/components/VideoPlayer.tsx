import React from "react";

type VideoPlayerProps = {
  src: string;
  onLoadedMetadata: (e: React.SyntheticEvent<HTMLVideoElement>) => void;
  onPlay: () => void;
  onPause: () => void;
  onEnded: () => void;
  onError: (e: React.SyntheticEvent<HTMLVideoElement>) => void;
};

export const VideoPlayer = React.forwardRef<HTMLVideoElement, VideoPlayerProps>(
  ({ src, onLoadedMetadata, onPlay, onPause, onEnded, onError }, ref) => {
    return (
      <div className="video-player-container">
        <video
          ref={ref}
          className="video-player"
          controls
          src={src}
          onLoadedMetadata={onLoadedMetadata}
          onPlay={onPlay}
          onPause={onPause}
          onEnded={onEnded}
          onError={onError}
        />
      </div>
    );
  }
);

VideoPlayer.displayName = "VideoPlayer";
