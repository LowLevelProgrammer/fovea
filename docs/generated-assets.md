# Generated Assets

Fovea stores generated media separately from source libraries. The default asset root is `/data/fovea/assets`, configured with `ASSETS_PATH`; source video files are always read-only.

## Layout

```
assets/
  thumbnails/<video-id>.jpg
  previews/<video-id>.vtt
  previews/<video-id>-0000.jpg
  previews/<video-id>-0001.jpg   # additional sheets for long videos
  hover/          # reserved
```

`video_assets` records the asset type, safe relative path, status, generation mode, generation time, source mtime and size, optional metadata, and failure details. The `(video_id, asset_type)` constraint ensures one current asset per type.

## Thumbnail lifecycle

After FFprobe finishes, Fovea queues automatic thumbnail generation instead of blocking the scan or probe. The default queue runs at most two FFmpeg jobs concurrently (`ASSET_WORKER_COUNT`). Thumbnails extract a JPEG at 10% of known duration, or at zero seconds when duration is unavailable, scaled to 480 pixels wide by default.

The queue records `pending`, `generating`, `ready`, or `failed`. Duplicate jobs are prevented both by persisted state and by the in-process queue key. A failed job is logged and does not stop the next queued job.

## Manual selection and regeneration

`POST /api/v1/videos/{video_id}/thumbnail` accepts a non-negative frame timestamp and queues a manual FFmpeg extraction. When FFprobe knows the duration, timestamps beyond it are rejected with `422`; when duration is unknown, the request retains the existing frame-based behavior. The selected frame replaces the current thumbnail and its `generation_mode` remains `manual` across restarts. Automatic work skips a valid manual thumbnail unless the source mtime or size changes; `POST /api/v1/videos/{video_id}/thumbnail/regenerate` explicitly restores an automatic frame.

On startup, Fovea scans ready videos and queues thumbnails that are missing, stale, or whose files were deleted. Source changes during scanning re-enter probe processing, which queues a replacement thumbnail after metadata is refreshed.

## Serving

`GET /api/v1/assets/thumbnails/{video_id}` serves only a tracked ready thumbnail. It uses `Cache-Control: public, max-age=0, must-revalidate`, so browsers revalidate the stable URL after manual or automatic replacement. It never accepts a filesystem path from the client.

The queue dispatches by asset type, so future preview sprites and hover assets can add an asset generator without redesigning the store or worker lifecycle.

## Seekbar previews

After thumbnail work, ready videos are queued for seekbar preview generation. The priority queue selects pending thumbnails before seekbar previews, and reserves a lower priority for future card-hover previews; both use at most two in-process FFmpeg workers. Preview frames are extracted every 10 seconds. Tiles use a configured 160×90 default size; FFmpeg scales each frame to fit and pads the tile without distorting the source aspect ratio. Sheets use 10 columns and hold at most 100 frames to bound image dimensions. Longer videos use numbered sheets.

The `seekbar_preview` row stores the WebVTT relative path plus the deterministic list of sprite paths and tile metadata in `metadata_json`. WebVTT cues contain intervals and `#xywh=x,y,width,height` fragments pointing to `/api/v1/assets/previews/{video_id}/sprites/{sheet_index}`. The player loads the VTT as a hidden metadata track, reads browser-parsed cue times and text, then parses the fragment and performs the sprite crop itself; browsers do not crop the image from `#xywh` automatically.

Preview files are written to temporary storage first. Generation captures source size and modification time before FFmpeg work, checks both again before promoting files, and only marks the row ready when database metadata still matches. A changed or unavailable source, missing/invalid duration, missing video stream, or FFmpeg failure marks only that video's preview failed. Startup and completed probes queue missing or stale assets; a valid asset is not regenerated on every restart. Sprite retrieval validates the requested non-negative sheet index against the tracked sheet list and resolves only that stored path.
