# Fovea — Product Requirements Document

**Version:** 0.2 (Draft)  
**Status:** Planning  
**Last updated:** 2026-06-07

---

## 1. Overview

**Fovea** is a self-hosted, Docker-first video discovery platform for homelab users and self-hosters who already maintain large video collections on local disks. The product is inspired by **YouTube's discovery and browsing experience**, not by traditional media-library applications such as Jellyfin, Plex, or Netflix.

### 1.1 What Fovea Is

- A **read-only indexer** over existing video files on disk
- A **discovery-first** browsing experience (recommendations, exploration, watch history)
- A **Docker-first** deployment for Linux self-hosters

### 1.2 What Fovea Is Not

| Not this | Why |
|----------|-----|
| Jellyfin / Plex clone | No library management, transcoding pipelines, or "import media" workflows |
| Netflix clone | No streaming catalog, subscriptions, or DRM |
| Traditional media library | No required Movies/TV/Season/Episode hierarchy |
| File manager | Never modifies, moves, renames, or deletes source files |

### 1.3 Target Audience

- Self-hosters running homelab setups
- Users with large, heterogeneous video collections (tutorials, lectures, clips, movies, anime episodes, recordings)
- Users who want **zero storage duplication** and **automatic library updates** from folder watching

### 1.4 Success Criteria (Phase 1)

1. User mounts one or more host directories; new videos appear in the library without manual import.
2. User can browse a YouTube-like homepage and watch videos streamed directly from source paths.
3. Source files on disk are never modified, moved, or duplicated.
4. Deployment via Docker Compose completes in under 10 minutes for a technically competent user.

### 1.5 Architecture Philosophy (Phase 1)

Phase 1 follows a **monolith-first, homelab-simple** approach:

- **One application process** handles the API, background tasks (watcher, job processor), and static frontend delivery.
- **Minimize infrastructure** — no Redis, message brokers, dedicated search engines, vector databases, or other auxiliary services unless a demonstrated requirement emerges.
- **Two-container deployment** — `fovea` (application) + `postgres` (database). Nothing else required to run.
- **Solve problems when they appear** — do not pre-optimize for scale that homelab users are unlikely to hit in Phase 1.

### 1.6 Phase 1 Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React + TypeScript + Vite (built and served by the monolith) |
| Backend | FastAPI |
| Database | PostgreSQL |
| Media tooling | FFmpeg / FFprobe |
| Deployment | Docker Compose |

No other runtime dependencies are required for Phase 1.

### 1.7 Single-User Scope (Phase 1)

Phase 1 is **explicitly single-user**:

- No authentication, accounts, permissions, or user management
- One implicit user; watch history and recommendations are global to the instance
- Database schema includes `user_id` columns (nullable or defaulted) so multi-user can be added later with minimal migration
- Network-level or reverse-proxy access control is the operator's responsibility

---

## 2. Critical Non-Negotiable Requirements

These constraints are architectural invariants. Any feature proposal that violates them must be rejected or redesigned.

### 2.1 Source Videos Must Never Be Modified

The application **must never**:

- Modify, rename, move, delete, overwrite, or re-encode source video files

Source media is **read-only** and remains the single source of truth for playback.

**Implication:** All derived data (thumbnails, preview frames, metadata records) lives in application storage, never alongside or inside source directories.

### 2.2 No Media Importing or Duplication

The application **must never** copy or import videos into application storage.

| Behavior | Required |
|----------|----------|
| Videos remain in original locations | Yes |
| Application stores metadata only | Yes |
| Indexing happens in place | Yes |
| Playback reads directly from source files | Yes |

**Tradeoff:** Users cannot "organize" their library inside Fovea. Folder structure on disk is the organizational truth. Fovea reflects it; it does not reshape it.

### 2.3 Folder Watching (Highest Priority)

Folder monitoring is the **most important feature** in Phase 1.

Users configure one or more host directories, for example:

```
/mnt/media/videos
/media/archive
/home/user/videos
```

The system must:

- Scan configured directories (initial and periodic)
- Detect newly added videos
- Detect removed videos
- Detect renamed videos where possible
- Refresh metadata automatically
- Update the library without manual import

**No manual import workflow** should be required for normal operation.

**Open question:** Should users be able to trigger an on-demand rescan, or is automatic watching sufficient?  
**Proposal:** Support both — automatic watching as default, manual "rescan now" as an escape hatch for edge cases (network mounts, permission changes).

### 2.4 Docker-First Architecture

- Docker support from day one
- Docker Compose for multi-service orchestration
- Persistent database volumes
- Configurable read-only media mounts
- Simple deployment process
- Linux-first design (Windows/macOS Docker possible but not primary)

### 2.5 Read-Only Media Access

- Media directories mounted read-only whenever possible
- Architecture assumes media paths are read-only
- Generated assets stored separately from source media
- Application never requires write permissions on media directories

---

## 3. Core Product Vision

Fovea should feel like opening YouTube, not opening a DVD shelf manager.

### 3.1 Primary User Journeys

1. **Discover** — Open homepage, see recently added, frequently watched, recommendations, and random picks.
2. **Watch** — Click a video, play from source, resume from watch history.
3. **Explore** — Follow recommendation sidebar, use search, stumble on forgotten content via random discovery.
4. **Forget about maintenance** — Add videos to disk; Fovea picks them up automatically.

### 3.2 Experience Priorities

| Priority | Feature area |
|----------|--------------|
| High | Discovery, browsing, recommendations |
| High | Watch history and resume |
| High | Automatic folder watching |
| Medium | Search (title, filename, tags) |
| Medium | Hover previews and seekbar previews |
| Low (Phase 1) | Structured TV/movie metadata |
| Future | AI, transcripts, semantic search |

### 3.3 Anti-Patterns to Avoid

- Forcing users to classify content as Movie vs TV Show vs Episode
- Requiring metadata entry before a video is watchable
- Blocking playback on "incomplete" library entries
- Presenting a folder tree as the primary navigation paradigm

---

## 4. Content Model

### 4.1 Fundamental Unit: Video

Every item in the library is primarily an **individual video**. The system does not assume hierarchical content types.

| Content type | Treatment |
|--------------|-----------|
| YouTube-style clips | Single video |
| Tutorials / lectures | Single video |
| Movies | Single video (optional metadata later) |
| Anime episodes | Single video (optional series metadata later) |
| Screen recordings | Single video |

**Future extensibility:** Movies, TV Shows, Seasons, and Episodes may exist as **optional metadata layers** attached to videos, not as required structural containers.

### 4.2 Video Identity

A video is identified by:

- Stable internal ID (UUID, assigned by Fovea)
- Canonical file path (as seen inside the container)
- File fingerprint signals (size, mtime, optional content hash) for rename/move detection

**Open question:** How should duplicate files (same content, different paths) be handled?  
**Proposal (Phase 1):** Treat each path as a distinct video. Deduplication is a future feature requiring content hashing policy decisions.

### 4.3 Metadata Fields (Phase 1)

| Field | Source | Notes |
|-------|--------|-------|
| Title | Derived from filename or user override | Default: humanized filename |
| File path | Filesystem | Canonical container path |
| Duration | FFprobe | Required for player and previews |
| Tags | User-assigned, folder-derived, or rules-based | See tagging strategy below |
| Thumbnail | Generated | Stored in asset store |
| Watch count | Application | Incremented on meaningful watch events |
| Last watched | Application | Timestamp per user (single-user Phase 1) |
| Added date | First seen by watcher | Library discovery signal |

**Tagging strategy (proposal):**

- Auto-tag from parent folder name (e.g., `/videos/anime/` → tag `anime`)
- Allow manual tag editing in UI (stored in DB only, never written to source)
- Optional configurable tag rules (glob/path patterns) in a later sub-phase

---

## 5. Feature Requirements

### 5.1 Homepage

YouTube-like home feed with sections:

| Section | Data source | Behavior |
|---------|-------------|----------|
| Recently Added | `added_date` descending | Surface new content from folder watcher |
| Frequently Watched | `watch_count` / recency-weighted | Personal usage patterns |
| Recommended For You | Metadata + watch history engine | See §5.4 |
| Random Discovery | Uniform random sample | ~20% of recommendation slots globally |

Sections should be scrollable card grids. Empty states should guide users to configure watch paths.

### 5.2 Video Page

- HTML5 video player (direct file serve or byte-range streaming)
- Title and metadata display
- Editable tags (DB-only)
- Watch history integration (resume position, mark watched)
- Recommendations sidebar (same engine as homepage, scoped to current video)

### 5.3 Search

Support:

- Title search (full-text)
- Filename search
- Tag search
- General metadata search (duration ranges, date added — stretch)

**Open question:** Fuzzy matching vs exact?  
**Proposal:** PostgreSQL `tsvector` with prefix matching for Phase 1; fuzzy/trigram in Phase 2 if needed.

### 5.4 Recommendation System (Phase 1)

Metadata-based only — **no AI required**.

**Inputs:**

- Filename tokens
- Folder path / parent directory
- Tags and categories
- Watch history (videos watched, skipped, completed)
- Watch duration and completion percentage
- Viewing patterns (time of day, session clustering — optional Phase 1.5)

**Algorithm sketch (Phase 1):**

1. Score candidate videos by tag overlap, folder similarity, and co-watch patterns.
2. Boost unseen and infrequently watched items slightly.
3. Reserve ~20% of slots for uniform random selection from the full library.
4. Exclude recently shown items within a session to reduce immediate repetition.

**Tradeoff:** Simple metadata matching will not capture semantic similarity ("two cooking tutorials that never share tags"). Architecture must allow plugging in embeddings later without rewriting the feed API.

### 5.5 Random Discovery (~20%)

Explicit product requirement to prevent filter bubbles.

- Applied within recommendation feeds and potentially as a dedicated homepage section
- Random selection is from the **available library**, not global internet content
- Should surface long-unwatched and low-watch-count items with slight bias

### 5.6 Video Preview Features

#### Seekbar Preview

On timeline hover, show preview frames (filmstrip or single frame), similar to YouTube.

**Requirements:**

- Preview frames generated by FFmpeg during indexing or on-demand
- Stored in asset store, keyed by video ID + timestamp
- Configurable density (e.g., 1 frame per N seconds)

#### Video Card Hover Preview

On card hover in grids/sidebars:

- **Option A:** Muted autoplay of a short WebM/MP4 preview clip
- **Option B:** Animated sprite sheet / WebP sequence

**Tradeoff:**

| Approach | Pros | Cons |
|----------|------|------|
| Muted short clip | High fidelity, familiar UX | Larger assets, more FFmpeg work |
| Sprite sheet | Efficient for many cards | Less smooth, harder to generate |

**Proposal:** Phase 1 implements sprite-based hover previews (lower storage/CPU); muted clip previews as Phase 2 enhancement.

### 5.7 Generated Assets

May generate:

- Thumbnails (poster frame)
- Preview frames (seekbar)
- Hover preview sprites/clips
- Metadata indexes

**Rules:**

- Stored separately from source videos (configurable path, e.g., `/data/fovea/assets`)
- Persist across container restarts via Docker volume
- Deleting generated assets never affects source videos
- Regeneration is always possible from source (read-only FFmpeg read)

---

## 6. Non-Functional Requirements

### 6.1 Performance

| Area | Target (Phase 1) |
|------|------------------|
| Homepage load | < 2s on LAN for libraries up to ~10k videos |
| Initial scan | Background job; UI remains usable |
| Video start | < 3s to first frame on LAN |
| Preview frame | < 200ms after hover (cached assets) |

**Open question:** Maximum expected library size?  
**Assumption for planning:** 50k videos is a reasonable upper bound for Phase 1 schema; beyond that may need partitioning and stronger indexing.

### 6.2 Reliability

- Watcher must recover from container restarts without full rescan where possible
- Database is source of truth for library state; filesystem scan reconciles drift
- Graceful handling of temporarily unavailable media mounts (mark unavailable, don't delete)

### 6.3 Security

- No write access to media mounts
- **No application-level authentication in Phase 1** — no login, sessions, accounts, or permissions
- Operators who expose Fovea beyond a trusted LAN should use reverse-proxy auth (Traefik, Authelia, etc.)
- Path traversal protection on any file-serving endpoint
- Sanitize and validate configured watch paths

### 6.4 Observability

- Structured logs for scan events, watcher activity, FFmpeg jobs
- Health endpoint for Docker orchestration
- Basic metrics: library size, scan queue depth, failed probes

---

## 7. Deployment Requirements

### 7.1 Docker Compose Services

Phase 1 uses **two containers only**:

| Service | Purpose |
|---------|---------|
| `fovea` | Monolith: FastAPI API, background tasks (watcher + job processor), built React frontend |
| `postgres` | Primary database |

**Explicitly excluded from Phase 1:** Redis, message brokers, separate worker containers, dedicated search engines, vector databases, and sidecar media services.

**Homelab deployment goal:** A user with Docker installed can `docker compose up` and have a working instance with minimal configuration.

### 7.2 Volume Layout

```
fovea-db volume         → PostgreSQL data (managed by postgres service)
fovea-assets volume     → Generated thumbnails, previews (mounted in fovea)
/mnt/media/videos:ro    → User media (read-only mount into fovea)
```

### 7.3 Path Storage

- The database stores **container-canonical paths only** (e.g., `/media/videos/...`)
- The application never stores or resolves host filesystem paths
- Users map host directories to container paths via Docker volume mounts
- `WATCH_PATHS` lists container paths, not host paths

### 7.4 Configuration

Environment-driven configuration:

- `WATCH_PATHS` — comma-separated container directory paths
- `ASSETS_PATH` — generated asset root inside container
- `DATABASE_URL`
- `SCAN_INTERVAL_SECONDS`
- `RANDOM_DISCOVERY_RATIO` (default 0.2)
- `FFMPEG_CONCURRENCY` (default 2)

---

## 8. Future Features (Out of Scope for Phase 1)

Design architecture to support these later **without implementing now**:

| Feature | Architectural hook |
|---------|-------------------|
| Transcript generation | `video_text_artifacts` table, async job pipeline |
| AI video understanding | Pluggable analyzer workers, artifact storage |
| Semantic search | Vector column or dedicated search service |
| Embeddings | Embedding store keyed by video ID |
| Natural language search | Query layer above embeddings |
| Scene detection | Timestamped scene artifacts |
| AI-powered recommendations | Scoring provider interface |

---

## 9. Open Questions and Unclear Requirements

| # | Question | Impact | Status |
|---|----------|--------|--------|
| 1 | Single-user vs multi-user in Phase 1? | Auth model, watch history schema | **Decided:** Single-user; schema forward-compatible; auth deferred |
| 2 | Supported video formats? | FFprobe failures, playback compatibility | Common containers: mp4, mkv, webm, avi, mov |
| 3 | Recursive scanning depth? | Performance, unexpected content | Recursive, with optional ignore globs |
| 4 | Symlinks and network mounts? | Watcher reliability | Follow symlinks; tolerate stale NFS with rescan |
| 5 | Transcoding for browser compatibility? | Conflicts with "no re-encode" | **No transcoding Phase 1**; direct serve + browser-native codecs only |
| 6 | How to detect renames vs delete+add? | User-facing continuity | Heuristic match on size + duration + partial hash |
| 7 | Watch "completed" threshold? | Recommendation inputs | 90% duration or explicit mark |
| 8 | Mobile / TV clients? | API design | Responsive web only Phase 1 |
| 9 | Subtitle support? | Sidecar files vs embedded | Detect sidecar `.srt`/`.vtt` read-only; no modification |

---

## 10. Proposed Improvements

1. **Configurable ignore rules** — `.foveaignore` file or glob patterns to skip sample/trailer directories without excluding parent watch paths.
2. **Library health dashboard** — Surface unwatched count, failed probes, offline paths, and last scan time.
3. **"Continue watching" row** — Distinct from Frequently Watched; prioritizes incomplete sessions.
4. **Soft unavailable state** — When a mount disappears, grey out videos instead of purging metadata immediately.
5. **Explicit codec compatibility badge** — Show browser-playable vs needs-download without transcoding.
6. **Recommendation explainability** — "Because you watched X" / "From folder Y" / "Random pick" labels for transparency.

---

## 11. Out of Scope (Explicit)

- Authentication, accounts, permissions, and user management (Phase 1)
- Redis, message brokers, and auxiliary infrastructure services (Phase 1)
- User management and sharing (Phase 1)
- Remote access / tunnel setup (user's infra responsibility)
- Mobile native apps
- Live TV / DVR
- Plugin ecosystem
- Writing any data to source media directories

---

## 12. Document References

- [Architecture](./architecture.md)
- [Database Schema](./database.md)
- [API Specification](./api.md)
- [Implementation Phases](./phases.md)
- [Architecture Decision Records](./decisions.md)
