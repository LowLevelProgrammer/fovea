import React from "react";

type VideoPlayerProps = {
  src: string;
  previewSrc?: string | null;
  onLoadedMetadata: (e: React.SyntheticEvent<HTMLVideoElement>) => void;
  onPlay: () => void;
  onPause: () => void;
  onEnded: () => void;
  onError: (e: React.SyntheticEvent<HTMLVideoElement>) => void;
};

type SpriteCue = { start: number; end: number; image: string; x: number; y: number; width: number; height: number };

export function parseSpriteCue(cue: VTTCue, metadataUrl: string): SpriteCue | null {
  const match = cue.text.trim().match(/^(.*?)#xywh=(\d+),(\d+),(\d+),(\d+)$/);
  if (!match || cue.endTime <= cue.startTime) return null;
  try {
    // previewSrc is normally a root-relative API path. Resolve that first,
    // then resolve the cue payload relative to the actual VTT URL.
    const vttUrl = new URL(metadataUrl, document.baseURI);
    const image = new URL(match[1], vttUrl).toString();
    const [, , x, y, width, height] = match;
    return { start: cue.startTime, end: cue.endTime, image, x: Number(x), y: Number(y), width: Number(width), height: Number(height) };
  } catch {
    return null;
  }
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export const VideoPlayer = React.forwardRef<HTMLVideoElement, VideoPlayerProps>(
  ({ src, previewSrc, onLoadedMetadata, onPlay, onPause, onEnded, onError }, ref) => {
    const localVideoRef = React.useRef<HTMLVideoElement | null>(null);
    const trackRef = React.useRef<HTMLTrackElement | null>(null);
    const containerRef = React.useRef<HTMLDivElement | null>(null);
    const [playing, setPlaying] = React.useState(false);
    const [currentTime, setCurrentTime] = React.useState(0);
    const [duration, setDuration] = React.useState(0);
    const [volume, setVolume] = React.useState(1);
    const [muted, setMuted] = React.useState(false);
    const [isFullscreen, setIsFullscreen] = React.useState(false);
    const [cues, setCues] = React.useState<SpriteCue[]>([]);
    const [hoveredCue, setHoveredCue] = React.useState<SpriteCue | null>(null);
    const [previewLeft, setPreviewLeft] = React.useState(0);
    const [loadedSpriteUrl, setLoadedSpriteUrl] = React.useState<string | null>(null);
    const spriteLoadCache = React.useRef(new Map<string, boolean>());

    const setVideoRef = React.useCallback((element: HTMLVideoElement | null) => {
      localVideoRef.current = element;
      if (typeof ref === "function") ref(element);
      else if (ref) ref.current = element;
    }, [ref]);

    React.useEffect(() => {
      setCues([]);
      setHoveredCue(null);
      if (!previewSrc || !trackRef.current) return;
      const trackElement = trackRef.current;
      const textTrack = trackElement.track;
      textTrack.mode = "hidden";
      const loadCues = () => {
        const parsed: SpriteCue[] = [];
        const cueList = textTrack.cues;
        if (cueList) {
          for (let i = 0; i < cueList.length; i += 1) {
            const cue = cueList[i];
            if (cue instanceof VTTCue) {
              const spriteCue = parseSpriteCue(cue, previewSrc);
              if (spriteCue) parsed.push(spriteCue);
            }
          }
        }
        setCues(parsed);
      };
      const clearCues = () => {
        setCues([]);
        setHoveredCue(null);
      };
      trackElement.addEventListener("load", loadCues);
      trackElement.addEventListener("error", clearCues, { once: true });
      if (trackElement.readyState === 2) loadCues();
      return () => {
        trackElement.removeEventListener("load", loadCues);
        trackElement.removeEventListener("error", clearCues);
      };
    }, [previewSrc]);

    React.useEffect(() => {
      if (!localVideoRef.current) return;
      localVideoRef.current.muted = muted;
      localVideoRef.current.volume = volume;
    }, [muted, volume]);

    React.useEffect(() => {
      const spriteUrl = hoveredCue?.image;
      if (!spriteUrl) {
        setLoadedSpriteUrl(null);
        return;
      }

      const cachedResult = spriteLoadCache.current.get(spriteUrl);
      if (cachedResult !== undefined) {
        setLoadedSpriteUrl(cachedResult ? spriteUrl : null);
        return;
      }

      setLoadedSpriteUrl(null);
      let active = true;
      const image = new Image();
      image.onload = () => {
        spriteLoadCache.current.set(spriteUrl, true);
        if (active) setLoadedSpriteUrl(spriteUrl);
      };
      image.onerror = () => {
        spriteLoadCache.current.set(spriteUrl, false);
        if (active) setLoadedSpriteUrl(null);
      };
      image.src = spriteUrl;
      return () => {
        active = false;
        image.onload = null;
        image.onerror = null;
      };
    }, [hoveredCue?.image]);

    React.useEffect(() => {
      const updateFullscreen = () => setIsFullscreen(document.fullscreenElement === containerRef.current);
      document.addEventListener("fullscreenchange", updateFullscreen);
      return () => document.removeEventListener("fullscreenchange", updateFullscreen);
    }, []);

    const handleTimeUpdate = () => {
      const video = localVideoRef.current;
      if (video) setCurrentTime(video.currentTime);
    };
    const handleMetadata = (event: React.SyntheticEvent<HTMLVideoElement>) => {
      setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0);
      onLoadedMetadata(event);
    };
    const togglePlayback = () => {
      const video = localVideoRef.current;
      if (!video) return;
      if (video.paused) void video.play().catch(() => undefined);
      else video.pause();
    };
    const seekTo = (value: number) => {
      const video = localVideoRef.current;
      if (video && Number.isFinite(value)) video.currentTime = value;
      setCurrentTime(value);
    };
    const handlePointerMove = (event: React.PointerEvent<HTMLInputElement>) => {
      if (event.pointerType === "touch" || duration <= 0 || cues.length === 0) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (rect.width <= 0) return;
      const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const time = fraction * duration;
      const cue = cues.find((candidate) => candidate.start <= time && time < candidate.end) ?? null;
      setHoveredCue(cue);
      if (cue) setPreviewLeft(Math.max(cue.width / 2, Math.min(rect.width - cue.width / 2, event.clientX - rect.left)));
    };

    return (
      <div className="video-player-container" ref={containerRef}>
        <video
          ref={setVideoRef}
          className="video-player"
          src={src}
          onLoadedMetadata={handleMetadata}
          onTimeUpdate={handleTimeUpdate}
          onPlay={() => { setPlaying(true); onPlay(); }}
          onPause={() => { setPlaying(false); onPause(); }}
          onEnded={() => { setPlaying(false); onEnded(); }}
          onError={onError}
          onClick={togglePlayback}
          playsInline
        >
          {previewSrc && <track ref={trackRef} kind="metadata" src={previewSrc} />}
        </video>
        <div className="player-controls" role="group" aria-label="Video controls">
          <div className="player-seek-wrap">
            {hoveredCue && loadedSpriteUrl === hoveredCue.image && (
              <div className="seek-preview" style={{ left: `${previewLeft}px`, width: hoveredCue.width, height: hoveredCue.height, backgroundImage: `url("${hoveredCue.image}")`, backgroundPosition: `-${hoveredCue.x}px -${hoveredCue.y}px` }} aria-hidden="true" />
            )}
            <input
              className="player-seekbar"
              type="range"
              min={0}
              max={duration || 0}
              step="any"
              value={Math.min(currentTime, duration || 0)}
              aria-label="Seek video"
              aria-valuetext={`${formatTime(currentTime)} of ${formatTime(duration)}`}
              onChange={(event) => seekTo(Number(event.currentTarget.value))}
              onPointerMove={handlePointerMove}
              onPointerLeave={() => setHoveredCue(null)}
              onPointerDown={() => setHoveredCue(null)}
            />
          </div>
          <div className="player-control-row">
            <button type="button" className="player-control-button" onClick={togglePlayback} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
            <span className="player-time" aria-live="off">{formatTime(currentTime)} / {formatTime(duration)}</span>
            <button type="button" className="player-control-button" onClick={() => setMuted((value) => !value)} aria-label={muted ? "Unmute" : "Mute"}>{muted || volume === 0 ? "🔇" : "🔊"}</button>
            <input className="player-volume" type="range" min={0} max={1} step={0.05} value={muted ? 0 : volume} aria-label="Volume" onChange={(event) => { const next = Number(event.currentTarget.value); setVolume(next); setMuted(next === 0); if (localVideoRef.current) localVideoRef.current.volume = next; }} />
            <button type="button" className="player-control-button player-fullscreen" onClick={() => { const container = containerRef.current; if (isFullscreen) void document.exitFullscreen(); else if (container?.requestFullscreen) void container.requestFullscreen(); }} aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}>⛶</button>
          </div>
        </div>
      </div>
    );
  }
);

VideoPlayer.displayName = "VideoPlayer";
