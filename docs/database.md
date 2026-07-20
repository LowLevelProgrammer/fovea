# Fovea — Database Schema

**Version:** 0.2 (Draft)  
**Status:** Planning  
**Last updated:** 2026-06-07

---

## 1. Overview

PostgreSQL is the **canonical store for all application state**. Source video files are not referenced by anything other than read-only **container-canonical** path strings and derived fingerprints. Host filesystem paths are never stored. Generated assets (images, sprites) are stored on the filesystem with paths recorded in the database.

### 1.1 Design Goals

| Goal | Approach |
|------|----------|
| Video-centric model | `videos` is the core entity; no required show/season hierarchy |
| Read-only media invariant | DB never triggers writes to source paths |
| Watcher-friendly | Efficient upserts on path + fingerprint; soft-delete for missing files |
| Discovery-optimized | Indexes for feeds, FTS for search, watch history for recommendations |
| Monolith-compatible | PostgreSQL `jobs` table as the sole job queue; no Redis |
| Future AI-ready | JSONB artifacts, extensible job tables; vector columns deferred |
| Multi-user-ready | `user_id` columns present from Phase 1 with nullable/default values |

### 1.2 ORM / Migration Strategy

- **Alembic** migrations with FastAPI/SQLAlchemy 2.x (or SQLModel)
- All schema changes versioned in repo
- Seed data only for development fixtures

---

## 2. Entity Relationship Diagram

```mermaid
erDiagram
    watch_paths ||--o{ videos : scopes
    videos ||--o| video_probe : has
    videos ||--o{ video_assets : has
    videos ||--o{ video_tags : tagged
    tags ||--o{ video_tags : applied
    videos ||--o{ watch_sessions : watched
    videos ||--o{ watch_events : events
    videos ||--o{ recommendation_impressions : shown
    scan_runs ||--o{ scan_events : contains
    jobs ||--o| videos : targets

    watch_paths {
        uuid id PK
        text path UK
        boolean enabled
        timestamptz created_at
    }

    videos {
        uuid id PK
        text file_path UK
        text title
        bigint file_size
        timestamptz file_mtime
        text fingerprint
        text status
        timestamptz added_at
        timestamptz last_seen_at
        int watch_count
        timestamptz last_watched_at
        tsvector search_vector
    }

    video_probe {
        uuid video_id PK_FK
        float duration_seconds
        text video_codec
        text audio_codec
        int width
        int height
        jsonb raw_ffprobe
    }

    video_assets {
        uuid id PK
        uuid video_id FK
        text asset_type
        text storage_path
        jsonb meta
    }

    tags {
        uuid id PK
        text name UK
    }

    watch_sessions {
        uuid id PK
        uuid video_id FK
        float position_seconds
        float duration_seconds
        boolean completed
        timestamptz updated_at
    }
```

---

## 3. Core Tables

### 3.1 `watch_paths`

Configured directories the watcher monitors.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` | PK | |
| `path` | `TEXT` | NOT NULL, UNIQUE | Container-canonical absolute path |
| `enabled` | `BOOLEAN` | NOT NULL, DEFAULT true | |
| `scan_recursive` | `BOOLEAN` | NOT NULL, DEFAULT true | |
| `label` | `TEXT` | NULL | User-friendly name |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | |

**Indexes:** `UNIQUE (path)`

**Notes:**

- Paths validated at insert: must be absolute, must exist at scan time (warning if not).
- Disabling a path does not delete videos immediately — marks them `orphaned` or `unavailable` after next scan.

---

### 3.2 `videos`

Central entity. One row per file path.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | `UUID` | PK | Stable across renames if fingerprint match updates path |
| `file_path` | `TEXT` | NOT NULL, UNIQUE | Current absolute path in container |
| `title` | `TEXT` | NOT NULL | Default from filename; user-overridable |
| `title_override` | `TEXT` | NULL | If set, display this instead of auto title |
| `file_size` | `BIGINT` | NOT NULL | Bytes |
| `file_mtime` | `TIMESTAMPTZ` | NOT NULL | From filesystem |
| `fingerprint` | `TEXT` | NULL | Partial hash fingerprint by default; `size:mtime` fallback if configured |
| `status` | `TEXT` | NOT NULL | See status enum below |
| `added_at` | `TIMESTAMPTZ` | NOT NULL | First discovery |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL | Last successful scan saw file |
| `unavailable_since` | `TIMESTAMPTZ` | NULL | Set when file missing |
| `watch_count` | `INTEGER` | NOT NULL, DEFAULT 0 | Denormalized for feed performance |
| `last_watched_at` | `TIMESTAMPTZ` | NULL | Denormalized |
| `search_vector` | `TSVECTOR` | NULL | Maintained by trigger |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | |

**Status enum (`video_status`):**

| Value | Meaning |
|-------|---------|
| `discovered` | File seen; probe pending |
| `probing` | Probe in progress |
| `ready` | Probe complete; playable |
| `processing` | Assets generating |
| `unavailable` | File not found on last scan |
| `error` | Probe failed; retry scheduled |

**Indexes:**

```sql
CREATE INDEX idx_videos_status ON videos (status);
CREATE INDEX idx_videos_added_at ON videos (added_at DESC);
CREATE INDEX idx_videos_last_watched ON videos (last_watched_at DESC NULLS LAST);
CREATE INDEX idx_videos_watch_count ON videos (watch_count DESC);
CREATE INDEX idx_videos_search ON videos USING GIN (search_vector);
CREATE INDEX idx_videos_path_prefix ON videos (file_path text_pattern_ops);  -- folder browsing
```

**Tradeoff:** Denormalized `watch_count` and `last_watched_at` on `videos` speed up feed queries at the cost of update logic in watch event handlers. Acceptable for Phase 1.

---

### 3.3 `video_probe`

Technical metadata from FFprobe. Separated from `videos` to keep core row narrow and allow re-probe without touching display fields.

| Column | Type | Notes |
|--------|------|-------|
| `video_id` | `UUID` | PK, FK → videos |
| `duration_seconds` | `FLOAT` | Required for player |
| `container_format` | `TEXT` | e.g., matroska, mp4 |
| `video_codec` | `TEXT` | e.g., h264, hevc |
| `audio_codec` | `TEXT` | e.g., aac, opus |
| `width` | `INTEGER` | |
| `height` | `INTEGER` | |
| `frame_rate` | `FLOAT` | |
| `bitrate` | `INTEGER` | Optional |
| `raw_ffprobe` | `JSONB` | Full probe output for debugging |
| `probed_at` | `TIMESTAMPTZ` | |

---

### 3.4 `video_assets`

References to generated files in the asset store.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `video_id` | `UUID` | FK → videos |
| `asset_type` | `TEXT` | `thumbnail`, `preview_sprite`, `hover_sprite` |
| `storage_path` | `TEXT` | Path relative to asset root |
| `meta` | `JSONB` | Dimensions, frame count, interval, vtt offset |
| `created_at` | `TIMESTAMPTZ` | |

**Indexes:**

```sql
CREATE UNIQUE INDEX idx_video_assets_unique ON video_assets (video_id, asset_type);
```

Deleting a row and its file is safe; regeneration re-creates both.

---

### 3.5 `tags` and `video_tags`

Normalized tagging.

**`tags`:**

| Column | Type |
|--------|------|
| `id` | `UUID` PK |
| `name` | `TEXT` UNIQUE (case-insensitive via `LOWER`) |

**`video_tags`:**

| Column | Type |
|--------|------|
| `video_id` | `UUID` FK |
| `tag_id` | `UUID` FK |
| `source` | `TEXT` — `manual`, `folder_rule`, `auto` |

**PK:** `(video_id, tag_id)`

**Folder-derived tags:** On ingest, worker tokenizes parent directory names and inserts `source = 'folder_rule'` tags.

---

## 4. Watch History Tables

### 4.1 Phase 1: Single-User Model (Multi-User Ready)

Phase 1 is **explicitly single-user**. No `users` table, no authentication, no permissions.

**Forward-compatibility strategy:**

- `user_id` columns exist on `watch_sessions`, `watch_events`, and other per-user tables from day one
- Phase 1 uses a constant singleton UUID (e.g., `00000000-0000-0000-0000-000000000001`) for all rows
- When multi-user arrives (Phase 6+), add a `users` table, populate `user_id` values, and add foreign keys — no column additions required on history tables

**Phase 1 does not implement:** login, sessions, accounts, roles, or access control.

### 4.2 `watch_sessions`

Represents current progress for resume functionality.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `user_id` | `UUID` | FK → users (nullable Phase 1) |
| `video_id` | `UUID` | FK |
| `position_seconds` | `FLOAT` | Last known position |
| `duration_seconds` | `FLOAT` | Snapshot of video duration |
| `completed` | `BOOLEAN` | True if watched ≥ threshold |
| `updated_at` | `TIMESTAMPTZ` | |

**Unique:** `(user_id, video_id)` — one active session per video per user.

### 4.3 `watch_events`

Append-only log for recommendation engine and analytics.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `user_id` | `UUID` | |
| `video_id` | `UUID` | FK |
| `event_type` | `TEXT` | `start`, `progress`, `pause`, `complete` |
| `position_seconds` | `FLOAT` | |
| `created_at` | `TIMESTAMPTZ` | |

**Index:** `(user_id, created_at DESC)`, `(video_id, created_at DESC)`

**Retention:** Consider partitioning by month if volume grows. Phase 1: no partition.

**Tradeoff:** Append-only events vs updating a single row. Events enable pattern analysis; sessions enable fast resume. Both are kept.

---

## 5. Library Operations Tables

### 5.1 `scan_runs`

Audit log for scan operations.

| Column | Type |
|--------|------|
| `id` | `UUID` PK |
| `watch_path_id` | `UUID` FK nullable |
| `scan_type` | `TEXT` — `full`, `incremental`, `watch_event` |
| `started_at` | `TIMESTAMPTZ` |
| `finished_at` | `TIMESTAMPTZ` |
| `files_seen` | `INTEGER` |
| `files_added` | `INTEGER` |
| `files_removed` | `INTEGER` |
| `files_updated` | `INTEGER` |
| `status` | `TEXT` |
| `error_message` | `TEXT` |

### 5.2 `scan_events` (Optional Detail)

High-volume deployments may omit per-file events and rely on `scan_runs` aggregates only.

| Column | Type |
|--------|------|
| `id` | `UUID` |
| `scan_run_id` | `UUID` FK |
| `event_type` | `TEXT` — `add`, `remove`, `modify` |
| `file_path` | `TEXT` |
| `video_id` | `UUID` nullable |

**Proposal:** Defer `scan_events` to Phase 1.5 unless debugging demands it.

---

## 6. Job Queue Tables

### 6.1 `jobs`

PostgreSQL is the **sole job queue** in Phase 1. The monolith polls this table from an in-process background task loop. No Redis, message broker, or external queue.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `job_type` | `TEXT` | |
| `video_id` | `UUID` | FK nullable |
| `payload` | `JSONB` | |
| `priority` | `INTEGER` | Lower = higher priority |
| `status` | `TEXT` | `pending`, `running`, `completed`, `failed` |
| `attempts` | `INTEGER` | |
| `max_attempts` | `INTEGER` | |
| `run_after` | `TIMESTAMPTZ` | Scheduled delay |
| `locked_at` | `TIMESTAMPTZ` | Worker claim |
| `locked_by` | `TEXT` | Monolith instance ID |
| `last_error` | `TEXT` | |
| `created_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | |

**Indexes:**

```sql
CREATE INDEX idx_jobs_pending ON jobs (status, priority, run_after)
  WHERE status = 'pending';
```

**Tradeoff:** A PostgreSQL-polled queue is simpler to operate than Redis + worker but adds DB read load during heavy FFmpeg batches. For homelab scale this is acceptable. External queues are deferred until a demonstrated bottleneck appears.

---

## 7. Recommendation Support Tables

### 7.1 `recommendation_impressions` (Optional Phase 1.5)

Tracks what was shown to avoid immediate repetition within a session.

| Column | Type |
|--------|------|
| `id` | `UUID` |
| `user_id` | `UUID` |
| `video_id` | `UUID` |
| `feed_section` | `TEXT` |
| `reason` | `TEXT` — `similar_tags`, `same_folder`, `random`, etc. |
| `shown_at` | `TIMESTAMPTZ` |

**Phase 1 alternative:** Skip this table entirely; use in-process session state for deduplication within a browser session. Persist impressions only if cross-session deduplication becomes a demonstrated need.

### 7.2 `search_history`

Completed search requests used for deterministic personalization. Search history
never modifies source files.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `query` | TEXT | NOT NULL | Original completed search query |
| `searched_at` | TIMESTAMPTZ | NOT NULL | Recency ordering for token weights |
| `result_count` | INTEGER | NOT NULL | Number of matching videos |
| `clicked_video_id` | UUID | NULL, FK videos | Reserved for later click tracking |

---

## 8. Future Tables (Designed, Not Implemented)

### 8.1 `users` (Phase 6 — Multi-User)

| Column | Type |
|--------|------|
| `id` | `UUID` PK |
| `username` | `TEXT` UNIQUE |
| `password_hash` | `TEXT` |
| `created_at` | `TIMESTAMPTZ` |

### 8.2 `video_artifacts` (Transcripts, AI)

| Column | Type |
|--------|------|
| `id` | `UUID` |
| `video_id` | `UUID` FK |
| `artifact_type` | `TEXT` — `transcript`, `summary`, `scenes` |
| `content` | `JSONB` or `TEXT` |
| `created_at` | `TIMESTAMPTZ` |

### 8.3 `video_embeddings` (Semantic Search)

| Column | Type |
|--------|------|
| `video_id` | `UUID` PK FK |
| `model` | `TEXT` |
| `embedding` | `VECTOR(1536)` — pgvector extension |
| `created_at` | `TIMESTAMPTZ` |

**Index:** HNSW or IVFFlat on `embedding`.

### 8.4 `video_scenes`

| Column | Type |
|--------|------|
| `id` | `UUID` |
| `video_id` | `UUID` |
| `start_seconds` | `FLOAT` |
| `end_seconds` | `FLOAT` |
| `label` | `TEXT` nullable |

---

## 9. Search Vector Maintenance

Trigger to update `search_vector` on insert/update:

```sql
-- Illustrative
NEW.search_vector :=
  setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
  setweight(to_tsvector('simple', coalesce(NEW.file_path, '')), 'B');
  -- Tags merged via separate trigger or application-level update
```

Tag changes must refresh `search_vector`. Options:

1. Application updates on tag mutation
2. Trigger on `video_tags` changes

**Proposal:** Application-level for clarity in Phase 1.

---

## 10. Query Patterns

### 10.1 Homepage: Recently Added

```sql
SELECT v.*, vp.duration_seconds, va.storage_path AS thumbnail_path
FROM videos v
LEFT JOIN video_probe vp ON vp.video_id = v.id
LEFT JOIN video_assets va ON va.video_id = v.id AND va.asset_type = 'thumbnail'
WHERE v.status IN ('ready', 'processing')
ORDER BY v.added_at DESC
LIMIT 24;
```

### 10.2 Homepage: Frequently Watched

```sql
SELECT v.*, ...
FROM videos v
WHERE v.watch_count > 0 AND v.status = 'ready'
ORDER BY v.watch_count DESC, v.last_watched_at DESC
LIMIT 24;
```

### 10.3 Continue Watching

```sql
SELECT v.*, ws.position_seconds, ws.duration_seconds
FROM watch_sessions ws
JOIN videos v ON v.id = ws.video_id
WHERE ws.completed = false
  AND ws.position_seconds > 30
ORDER BY ws.updated_at DESC
LIMIT 12;
```

### 10.4 Full-Text Search

```sql
SELECT v.*, ts_rank(v.search_vector, query) AS rank
FROM videos v, plainto_tsquery('english', :q) query
WHERE v.search_vector @@ query
  AND v.status = 'ready'
ORDER BY rank DESC
LIMIT 50;
```

---

## 11. Migration and Data Lifecycle

| Event | DB behavior |
|-------|-------------|
| File discovered | INSERT `videos` status=`discovered` |
| Probe complete | UPSERT `video_probe`, status=`ready` |
| File missing | status=`unavailable`, set `unavailable_since` |
| File returns | status=`ready`, clear `unavailable_since` |
| File renamed | UPDATE `file_path`, keep `id` and history |
| User deletes asset | DELETE `video_assets` row only |
| Purge unavailable > N days | Optional admin action; DELETE `videos` row only |

**Critical:** Purging a `videos` row never touches source files.

---

## 12. Open Questions

| # | Question | Options |
|---|----------|---------|
| 1 | Store `watch_path_id` on `videos`? | Helps folder-scoped queries; path prefix may suffice |
| 2 | Content hash column? | Enables dedup and stronger rename detection; adds scan cost |
| 3 | Soft-delete `videos` vs hard-delete on long unavailable? | Soft retains history; hard keeps DB lean |
| 4 | pgvector in same DB or separate? | Same DB simpler; separate scales better |
| 5 | JSONB `metadata` column on videos for user custom fields? | Flexible vs schema discipline |

---

## 13. Related Documents

- [PRD](./prd.md)
- [Architecture](./architecture.md)
- [API Specification](./api.md)
- [Implementation Phases](./phases.md)
- [Architecture Decision Records](./decisions.md)
