# Fovea — API Specification

**Version:** 0.2 (Draft)  
**Status:** Planning  
**Last updated:** 2026-06-07

---

## 1. Overview

Fovea exposes a **RESTful HTTP API** implemented in FastAPI. The API prioritizes **discovery and playback** over library administration. All endpoints return JSON unless noted (streaming, static assets).

### 1.1 Base URL

```
http://localhost:8080/api/v1
```

The monolith serves both the API and frontend on a single port. Production typically sits behind a reverse proxy (`https://fovea.example.com/api/v1`).

### 1.2 Conventions

| Convention | Value |
|------------|-------|
| Version prefix | `/api/v1` |
| IDs | UUID v4 |
| Timestamps | ISO 8601 UTC (`2026-06-07T12:00:00Z`) |
| Pagination | `?page=1&limit=24` (default limit: 24) |
| Errors | RFC 7807 Problem Details (`application/problem+json`) |
| Auth (Phase 1) | **None** — no login, sessions, accounts, or permissions |
| Auth (Phase 6+) | Bearer token / session cookie (multi-user) |

### 1.3 Common Response Envelope

List endpoints return:

```json
{
  "items": [],
  "page": 1,
  "limit": 24,
  "total": 142,
  "has_more": true
}
```

### 1.4 Error Format

```json
{
  "type": "https://fovea.dev/errors/not-found",
  "title": "Video not found",
  "status": 404,
  "detail": "No video with id '...' exists.",
  "instance": "/api/v1/videos/..."
}
```

---

## 2. Resource Model (API Types)

### 2.1 `VideoSummary`

Used in feeds, search results, and sidebars.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Introduction to Homelab Networking",
  "duration_seconds": 1842.5,
  "thumbnail_url": "/api/v1/assets/thumbnails/550e8400...jpg",
  "hover_preview_url": "/api/v1/assets/hover/550e8400.../sprite.webp",
  "watch_count": 12,
  "added_at": "2026-06-01T08:00:00Z",
  "last_watched_at": "2026-06-06T21:30:00Z",
  "tags": ["tutorials", "networking"],
  "status": "ready"
}
```

### 2.2 `VideoDetail`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Introduction to Homelab Networking",
  "title_source": "auto",
  "file_path": "/media/videos/tutorials/intro-homelab-networking.mkv",
  "duration_seconds": 1842.5,
  "resolution": { "width": 1920, "height": 1080 },
  "codecs": { "video": "hevc", "audio": "aac" },
  "thumbnail_url": "/api/v1/assets/thumbnails/550e8400...jpg",
  "preview_sprite_url": "/api/v1/assets/previews/550e8400.../sprite.jpg",
  "preview_vtt_url": "/api/v1/assets/previews/550e8400.../sprite.vtt",
  "tags": ["tutorials", "networking"],
  "watch_count": 12,
  "added_at": "2026-06-01T08:00:00Z",
  "last_watched_at": "2026-06-06T21:30:00Z",
  "status": "ready",
  "stream_url": "/api/v1/videos/550e8400.../stream"
}
```

**Tradeoff:** Exposing `file_path` aids debugging but leaks filesystem layout.  
**Proposal:** Include in detail view only; omit from summaries. Settings-gated in production.

### 2.3 `FeedSection`

```json
{
  "section": "recommended",
  "title": "Recommended for you",
  "items": [ /* VideoSummary[] */ ],
  "meta": {
    "random_ratio_applied": 0.2,
    "generated_at": "2026-06-07T12:00:00Z"
  }
}
```

### 2.4 `WatchSession`

```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "position_seconds": 320.5,
  "duration_seconds": 1842.5,
  "completed": false,
  "updated_at": "2026-06-07T11:45:00Z"
}
```

---

## 3. Endpoints

### 3.1 Health

#### `GET /health/live`

Liveness probe. Returns 200 if process is running.

```json
{ "status": "ok" }
```

#### `GET /health/ready`

Readiness probe. Checks database connectivity and migration state.

```json
{
  "status": "ok",
  "database": "connected",
  "background_last_seen": "2026-06-07T11:59:00Z"
}
```

---

### 3.2 Homepage Feed

#### `GET /feed/home`

Returns all homepage sections in one request.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 24 | Items per section |
| `exclude` | string | — | Comma-separated video IDs to exclude (dedup across sections) |

**Response:**

```json
{
  "sections": [
    {
      "section": "continue_watching",
      "title": "Continue watching",
      "items": []
    },
    {
      "section": "recently_added",
      "title": "Recently added",
      "items": []
    },
    {
      "section": "frequently_watched",
      "title": "Frequently watched",
      "items": []
    },
    {
      "section": "recommended",
      "title": "Recommended for you",
      "items": []
    },
    {
      "section": "random",
      "title": "Discover something new",
      "items": []
    }
  ],
  "generated_at": "2026-06-07T12:00:00Z"
}
```

**Notes:**

- `continue_watching` is a proposed addition (see PRD).
- `recommended` section internally applies ~20% random injection.
- `random` section is explicitly 100% random for exploration.

#### `GET /feed/{section}`

Fetch a single section (`recently_added`, `frequently_watched`, `recommended`, `random`, `continue_watching`).

**Query:** `page`, `limit`

---

### 3.3 Videos

#### `GET /videos/{id}`

Returns `VideoDetail`.

**Errors:** 404 if not found.

#### `GET /videos/{id}/stream`

Streams video bytes from source file.

**Headers:**

- Request: `Range: bytes=0-` (optional)
- Response: `Accept-Ranges: bytes`, `Content-Type: video/mp4` (or detected MIME)
- Response: `206 Partial Content` when range requested

**Security:**

- Resolved path must fall under configured `watch_paths`
- Returns 404 if video `status = unavailable`

**Open question:** `Content-Disposition: inline` vs `attachment`?  
**Default:** `inline` for browser playback.

#### `GET /videos/{id}/recommendations`

Sidebar recommendations for video page.

**Query:**

| Param | Type | Default |
|-------|------|---------|
| `limit` | int | 12 |
| `random_ratio` | float | 0.2 |

**Response:**

```json
{
  "items": [
    {
      "video": { /* VideoSummary */ },
      "reason": "similar_tags",
      "reason_detail": "Shared tags: tutorials, networking"
    }
  ]
}
```

**Reason codes:** `similar_tags`, `same_folder`, `co_watched`, `random`, `unwatched`

#### `PATCH /videos/{id}`

Update user-editable metadata (DB only).

**Request body:**

```json
{
  "title_override": "My Custom Title",
  "tags": ["tutorials", "homelab"]
}
```

**Response:** Updated `VideoDetail`.

**Invariant:** Never writes to source file or filesystem metadata.

---

### 3.4 Watch History

#### `GET /watch/sessions`

List in-progress watch sessions (continue watching source).

**Query:** `page`, `limit`, `completed=false`

#### `GET /watch/sessions/{video_id}`

Get session for a specific video.

#### `PUT /watch/sessions/{video_id}`

Upsert watch progress.

**Request:**

```json
{
  "position_seconds": 320.5,
  "duration_seconds": 1842.5,
  "event": "progress"
}
```

**Behavior:**

- Updates `watch_sessions`
- Appends `watch_events` (if `event` provided)
- Increments `watch_count` on first `start` or crossing completion threshold
- Sets `completed = true` when `position / duration >= 0.9`

**Response:** `WatchSession`

#### `DELETE /watch/sessions/{video_id}`

Clear progress for a video (remove from continue watching).

#### `GET /watch/history`

Paginated watch history ordered by recency.

---

### 3.5 Search

#### `GET /search`

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search query (required) |
| `tags` | string | Comma-separated tag filter |
| `page` | int | Page number |
| `limit` | int | Results per page |

**Response:**

```json
{
  "items": [ /* VideoSummary[] */ ],
  "page": 1,
  "limit": 24,
  "total": 8,
  "has_more": false,
  "query": "homelab networking"
}
```

**Future parameter:** `mode=keyword|semantic|hybrid` (reserved, not implemented Phase 1).

---

### 3.6 Tags

#### `GET /tags`

List all tags with usage count.

```json
{
  "items": [
    { "name": "tutorials", "count": 142 },
    { "name": "anime", "count": 89 }
  ]
}
```

#### `GET /tags/{name}/videos`

Videos with a specific tag. Paginated `VideoSummary` list.

---

### 3.7 Assets

Generated assets are served through the API (or optionally via nginx direct alias in production).

#### `GET /assets/thumbnails/{video_id}.jpg`

#### `GET /assets/previews/{video_id}/sprite.jpg`

#### `GET /assets/previews/{video_id}/sprite.vtt`

WebVTT mapping timestamps to sprite positions.

#### `GET /assets/hover/{video_id}/sprite.webp`

**Caching headers:** `Cache-Control: public, max-age=86400, immutable` (assets regenerated on re-probe invalidate via URL version query or ETag).

**Proposal:** Include `asset_version` hash in URLs to bust cache after regeneration.

---

### 3.8 Library Administration

Low-priority admin endpoints for configuration. Not part of primary user journeys.

#### `GET /library/watch-paths`

```json
{
  "items": [
    {
      "id": "...",
      "path": "/media/videos",
      "label": "Main Videos",
      "enabled": true,
      "scan_recursive": true,
      "video_count": 1240,
      "last_scan_at": "2026-06-07T11:00:00Z"
    }
  ]
}
```

#### `POST /library/watch-paths`

**Request:**

```json
{
  "path": "/media/archive",
  "label": "Archive",
  "scan_recursive": true
}
```

Triggers initial scan job.

#### `PATCH /library/watch-paths/{id}`

Enable/disable, update label.

#### `DELETE /library/watch-paths/{id}`

Remove watch path. Does not delete source files. Marks associated videos `orphaned` after rescan.

#### `GET /library/status`

```json
{
  "total_videos": 5420,
  "ready_videos": 5200,
  "processing_videos": 45,
  "unavailable_videos": 12,
  "last_full_scan_at": "2026-06-07T06:00:00Z",
  "active_scan": false,
  "pending_jobs": 23
}
```

#### `POST /library/scan`

Trigger manual rescan.

**Request (optional):**

```json
{
  "watch_path_id": "...",
  "scan_type": "full"
}
```

**Response:** `202 Accepted`

```json
{
  "scan_run_id": "...",
  "message": "Scan enqueued"
}
```

---

## 4. WebSocket / SSE (Optional Phase 1.5)

Not required for Phase 1. Polling `/library/status` is sufficient.

**Future:** `GET /events/stream` (SSE) for scan progress and new video notifications.

---

## 5. Authentication (Not in Phase 1)

Phase 1 has **no authentication layer**. All endpoints are open within the deployment's network boundary.

| Concern | Phase 1 approach |
|---------|------------------|
| Access control | Operator's responsibility (LAN, VPN, reverse-proxy auth) |
| Accounts / login | Not implemented |
| Permissions / roles | Not implemented |
| Per-user data | Single implicit user; `user_id` in schema for future use |

**Phase 6+ placeholder:**

| Endpoint | Auth |
|----------|------|
| All read endpoints | Authenticated user |
| `PATCH /videos/{id}` | Authenticated user |
| `/library/*` | Admin role |

---

## 6. Rate Limiting

| Endpoint | Limit (proposal) |
|----------|------------------|
| `/search` | 30 req/min |
| `/library/scan` | 1 req/min |
| `/videos/{id}/stream` | Unlimited (LAN) |

Phase 1: simple in-process rate limiting for `/library/scan` (prevent accidental scan storms). Broader rate limiting via reverse proxy if the operator exposes the instance publicly.

---

## 7. CORS

Development:

```
Access-Control-Allow-Origin: http://localhost:5173
```

Production: restrict to configured `WEB_ORIGIN`.

---

## 8. OpenAPI

FastAPI auto-generates OpenAPI 3.1 at:

```
GET /api/v1/openapi.json
GET /api/v1/docs        # Swagger UI (disable in production or protect)
```

---

## 9. API Design Tradeoffs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| REST vs GraphQL | REST | GraphQL | Simpler for feed + resource model; fewer clients |
| Combined home feed | `GET /feed/home` | Separate calls per section | Fewer round trips for homepage |
| Stream through API | Yes | nginx X-Accel-Redirect | API can enforce path validation; slight CPU overhead |
| Expose file_path | Detail only | Never | Debugging value for self-hosters |
| PATCH vs PUT for metadata | PATCH | PUT | Partial updates for title/tags |

---

## 10. Future API Extensions

| Feature | Endpoint (proposed) |
|---------|---------------------|
| Semantic search | `GET /search?q=...&mode=semantic` |
| Transcripts | `GET /videos/{id}/transcript` |
| Scenes | `GET /videos/{id}/scenes` |
| User auth | `POST /auth/login`, `POST /auth/logout` |
| Playlists | `POST /playlists`, `GET /playlists/{id}` |
| Embeddings rebuild | `POST /admin/embeddings/reindex` |

Extension principle: **add endpoints and optional query params**; avoid breaking existing response shapes.

---

## 11. Open Questions

| # | Question | Proposal |
|---|----------|----------|
| 1 | Should `GET /feed/home` be one call or parallel section calls? | One call default; individual section endpoints for infinite scroll |
| 2 | ETag support on stream endpoint? | Yes for unchanged files; weak ETag from mtime+size |
| 3 | Batch watch events? | `POST /watch/events/batch` if player emits high-frequency progress |
| 4 | API versioning strategy on breaking changes? | New `/api/v2` prefix; v1 maintained for one major cycle |
| 5 | Include codec compatibility in `VideoDetail`? | `browser_playable: true/false` heuristic field |

---

## 12. Related Documents

- [PRD](./prd.md)
- [Architecture](./architecture.md)
- [Database Schema](./database.md)
- [Implementation Phases](./phases.md)
- [Architecture Decision Records](./decisions.md)
