# Fovea — Architecture Decision Records

**Version:** 0.2 (Draft)  
**Status:** Planning  
**Last updated:** 2026-06-07

This document records significant architectural and product decisions for Fovea. Each entry follows a lightweight ADR format: **Context**, **Decision**, **Consequences**, **Alternatives considered**, and **Status**.

---

## ADR-001: Source Media Is Read-Only

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Users store large video collections on local disks. Many media applications modify, reorganize, or transcode source files, causing data loss risk and storage duplication. Fovea's primary audience (homelab self-hosters) expects their files to remain untouched.

### Decision

The application will **never** modify, rename, move, delete, overwrite, or re-encode source video files. All application writes are confined to the database and a separate asset store.

### Consequences

- **Positive:** Zero risk of data corruption; users trust the platform with irreplaceable collections.
- **Positive:** Simpler mental model — disk layout is authoritative for file location.
- **Negative:** Cannot fix incompatible codecs via transcoding in Phase 1.
- **Negative:** Cannot normalize filenames or embed metadata into files.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Optional "organize my files" mode | Violates core product promise; high risk |
| Transcode-on-ingest to app storage | Violates no-duplication requirement |
| In-place metadata embedding (MP4 tags) | Modifies source files |

---

## ADR-002: Index In Place — No Media Import

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Traditional media servers often copy or import media into a managed library directory. This duplicates storage and creates sync drift between "what's on disk" and "what the app knows."

### Decision

Fovea indexes videos **in their original locations**. The database stores metadata only. Playback reads directly from source paths. No import or copy workflow exists.

### Consequences

- **Positive:** No storage duplication; library size scales with disk, not app storage.
- **Positive:** Users can manage files with any external tool; Fovea adapts via watching.
- **Negative:** Folder structure on disk directly affects discovery (tags from paths).
- **Negative:** Broken mounts or permission changes surface as unavailable videos.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Managed library directory | Storage duplication |
| Hard links into app storage | Filesystem complexity; still couples storage |
| Cloud import/sync | Out of scope for self-hosted local collections |

---

## ADR-003: Video as the Fundamental Content Unit

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Media servers typically require classifying content as Movies, TV Shows, Seasons, or Episodes. Fovea targets heterogeneous collections where such hierarchy is often absent or inconsistent.

### Decision

Every library item is primarily an **individual video**. Hierarchical content types (series, seasons) may be added later as optional metadata layers, not as required structural containers.

### Consequences

- **Positive:** Any file works immediately without manual classification.
- **Positive:** Schema and API remain simple in Phase 1.
- **Negative:** TV series browsing (season/episode views) deferred.
- **Negative:** Franchise-level recommendations require future metadata enrichment.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Required content type on ingest | Friction; violates auto-discovery goal |
| Folder-based "series" inference | Useful as heuristic, not as schema requirement |
| TMDB/TVDB metadata matching | External dependency; not all content is catalogued |

---

## ADR-004: Folder Watching Is the Primary Ingestion Mechanism

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Manual import workflows do not scale for homelab users who continuously add files to existing directories. Automatic detection is the highest-priority feature.

### Decision

Users configure one or more watch paths. The system scans, watches, and reconciles automatically. No manual import is required for normal operation. A manual rescan endpoint exists as an escape hatch.

### Consequences

- **Positive:** Zero-maintenance library for typical usage.
- **Positive:** Aligns with "drop files on disk" homelab workflows.
- **Negative:** Watcher complexity (inotify, polling, NFS edge cases).
- **Negative:** Large initial scans can be I/O intensive.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Manual import only | Explicitly rejected in requirements |
| Scheduled scan only (no inotify) | Too slow for local filesystems |
| User-triggered scan only | Too much friction |

---

## ADR-005: Docker-First Deployment

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Target users are self-hosters who commonly deploy services via Docker Compose. Linux is the primary platform.

### Decision

Docker and Docker Compose are first-class from day one. Configuration is environment-variable driven. Persistent volumes separate database, assets, and read-only media mounts.

### Consequences

- **Positive:** Predictable deployment; aligns with homelab norms.
- **Positive:** Read-only media mounts enforced at container level.
- **Negative:** Non-Docker installs not supported initially.
- **Negative:** Path mapping complexity (host vs container paths).

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Bare-metal install script | Harder to guarantee read-only mounts |
| Kubernetes-first | Overkill for target audience Phase 1 |
| Snap/AppImage | Less common in homelab segment |

---

## ADR-006: Store Container-Canonical Paths in Database

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Media paths differ between host and container filesystems. The database must store a consistent reference for playback and scanning.

### Decision

The database stores **container-canonical absolute paths** (e.g., `/media/videos/...`). Users must maintain consistent volume mount mappings across redeployments. `WATCH_PATHS` configures container paths.

### Consequences

- **Positive:** API and worker logic use one path namespace.
- **Positive:** No runtime path translation layer needed.
- **Negative:** Changing mount points without migration breaks references.
- **Negative:** Debugging requires understanding Docker volume mapping.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Store host paths + mapping table | Extra translation on every stream |
| Store relative paths + root ID | More complex queries; marginal benefit |
| Content-addressed storage keys | Over-engineered for Phase 1 |

**Open question:** Should a `path_migrations` tool be provided? Deferred to Phase 5.

---

## ADR-007: FastAPI Backend with PostgreSQL

**Status:** Accepted  
**Date:** 2026-06-07

### Context

The suggested stack lists FastAPI, PostgreSQL, React, and FFmpeg. A backend choice must balance async I/O, media tooling, and query capabilities for search and feeds.

### Decision

- **Backend:** FastAPI (Python 3.12+)
- **Database:** PostgreSQL 16+
- **Migrations:** Alembic
- **ORM:** SQLAlchemy 2.x or SQLModel

### Consequences

- **Positive:** Native FFmpeg/FFprobe integration in Python ecosystem.
- **Positive:** PostgreSQL FTS, JSONB, and future pgvector support.
- **Positive:** FastAPI auto-generates OpenAPI for frontend development.
- **Negative:** Python GIL considerations for CPU-bound FFmpeg (mitigated by subprocess workers).
- **Negative:** Heavier container image than Go.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Go + Gin/Fiber | Weaker FFmpeg scripting ergonomics |
| Node + Express | Less mature long-running worker patterns for media |
| SQLite | Concurrent write and FTS limitations at scale |
| Django | Heavier than needed for API-first service |

---

## ADR-008: No Transcoding in Phase 1

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Browser playback requires compatible codecs (typically H.264 + AAC in MP4). Many collections contain HEVC, AV1, or exotic audio in MKV containers. Transcoding solves compatibility but conflicts with "no re-encode" unless output is isolated.

### Decision

Phase 1 serves **original files through the API** via byte-range streaming. No transcoding pipeline. Document codec compatibility expectations for users.

### Consequences

- **Positive:** Zero CPU overhead for playback; honors read-only invariant simply.
- **Positive:** Faster time to first playable version.
- **Negative:** Some videos will not play in all browsers.
- **Negative:** User support burden for codec issues.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| On-the-fly transcode to temp | CPU heavy; temp storage management |
| Pre-transcode to asset store | Out of Phase 1 scope; revisit after v1 |
| Client-side WASM decode | Immature for all formats; high client CPU |

**Future path:** ADR-018 / ADR-023 document the boundary for optional post-v1 proxy transcodes.

---

## ADR-009: Metadata-Based Recommendations (No AI) for Phase 1

**Status:** Accepted  
**Date:** 2026-06-07

### Context

The PRD requires recommendations in Phase 1 using filename, folder, tags, and watch history — without AI dependency.

### Decision

Implement a pluggable `RecommendationProvider` interface. Phase 1 uses a `MetadataProvider` scoring tags, folders, filename tokens, and watch patterns. Reserve ~20% of slots for uniform random selection.

### Consequences

- **Positive:** No ML infrastructure; predictable behavior.
- **Positive:** Interface allows future `EmbeddingProvider` without API changes.
- **Negative:** Cannot surface semantically similar but metadata-dissimilar content.
- **Negative:** Cold-start users get folder/random-heavy recommendations.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| External recommendation API | Dependency; privacy concerns |
| Collaborative filtering | Requires multi-user data |
| LLM ranking | Scope and cost exceed Phase 1 |

---

## ADR-010: 20% Random Discovery Injection

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Pure similarity-based recommendations create filter bubbles and hide forgotten content. The PRD explicitly requires ~20% random selection.

### Decision

Recommendation feeds inject approximately **20% random** videos from the eligible library pool. A dedicated "Discover something new" homepage section uses 100% random selection. Recommendation items include `reason: random` for transparency.

### Consequences

- **Positive:** Surfaces unwatched and old content.
- **Positive:** Reduces repetitive feeds for power users.
- **Negative:** Occasionally irrelevant suggestions.
- **Negative:** Harder to A/B test "quality" of recommendations.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Separate random-only section (no injection) | Does not meet 20% in-feed requirement |
| Weighted random by low watch count | Biased, not truly random; use as additional boost instead |
| User-configurable ratio | Good future option; default 0.2 for now |

---

## ADR-011: Generated Assets in Separate Writable Store

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Thumbnails, seekbar sprites, and hover previews require generated files. These must not be written alongside source media.

### Decision

All generated assets live under a configurable **asset store** (default `/data/fovea/assets`), mounted as a Docker named volume. Database records asset paths. Assets are safe to delete and regenerate.

### Consequences

- **Positive:** Clear separation from read-only media.
- **Positive:** Asset store backup is small and independent.
- **Negative:** Additional volume to manage.
- **Negative:** Initial scan generates significant asset I/O.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Store thumbnails in PostgreSQL BYTEA | DB bloat; poor CDN/nginx serving |
| Store alongside source files | Violates read-only media invariant |
| Object storage (S3/MinIO) | Overkill for typical homelab Phase 1 |

---

## ADR-012: Sprite-Based Hover Previews for v1

**Status:** Accepted  
**Date:** 2026-06-07

### Context

YouTube-style card hover can use muted video clips or animated sprite sheets. Both require FFmpeg processing.

### Decision

v1 implements **sprite sheet / WebP** hover previews. Muted short video clips are deferred until after v1.

### Consequences

- **Positive:** Lower storage and generation cost.
- **Positive:** Faster to generate for large libraries.
- **Negative:** Slightly less polished than true video preview.
- **Negative:** Sprite generation adds FFmpeg complexity.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Muted MP4 clips first | Higher storage; slower batch generation |
| No hover preview | Significant UX gap vs stated vision |
| GIF previews | Larger files; worse quality |

---

## ADR-013: Hybrid Filesystem Watching (inotify + Polling + Reconciliation)

**Status:** Accepted  
**Date:** 2026-06-07

### Context

`inotify` works well on local ext4/btrfs but is unreliable on NFS, CIFS, and some FUSE mounts common in homelabs.

### Decision

Use a **three-layer** approach:

1. `watchdog` inotify for real-time events on local FS
2. Polling fallback for paths flagged as network mounts (or auto-detected)
3. Scheduled full reconciliation scan (default: every 6 hours, configurable)

### Consequences

- **Positive:** Reliable library state across mount types.
- **Positive:** Self-healing after missed events.
- **Negative:** Reconciliation scans are I/O expensive.
- **Negative:** Detection of network mounts is imperfect.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| inotify only | Unreliable on NFS |
| Polling only | High latency on local FS |
| User must manually rescan | Violates auto-discovery spirit |

---

## ADR-014: Rename Detection via Partial Hash by Default

**Status:** Accepted  
**Date:** 2026-06-07

### Context

When a user renames a file, the system should preserve video ID and watch history rather than treating it as delete + add.

### Decision

Within a scan window, match removed + added file pairs by:

1. Exact file size (required)
2. Duration from existing probe (required if available)
3. Partial content hash of the first/last N MB (enabled by default)

On match, update `file_path` on existing `videos` row.

Operators may configure a cheaper `size_duration` mode if their storage is especially I/O constrained.

### Consequences

- **Positive:** Watch history survives renames.
- **Positive:** Lower false-positive risk than size/duration alone.
- **Negative:** Partial hash reads source files (read-only, but I/O cost).
- **Negative:** Very large reorganizations can add noticeable scan latency.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Full file hash on ingest | Too expensive for large libraries |
| Never detect renames | Poor UX for reorganizing collections |
| inode tracking | Unreliable across rename on different FS boundaries |

---

## ADR-015: Single-User Model in Phase 1

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Multi-user auth adds complexity (sessions, per-user history, permissions). Phase 1 targets single-household self-hosting, often protected by network-level access.

### Decision

Phase 1 is **explicitly single-user**:

- One implicit user per Fovea instance
- **No authentication, accounts, permissions, or user management**
- Schema includes `user_id` columns (defaulted to a singleton UUID) on watch history tables for forward compatibility
- Multi-user auth deferred to Phase 6+

### Consequences

- **Positive:** Faster delivery of core discovery features.
- **Positive:** Simpler recommendation logic (one watch history).
- **Positive:** Multi-user migration requires populating `users` and FK constraints, not restructuring history tables.
- **Negative:** Not suitable for internet-exposed multi-user without proxy.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Multi-user from day one | Scope expansion |
| API key auth only | Doesn't solve per-user history; still adds auth complexity |
| No user_id in schema | Painful migration later |

---

## ADR-016: PostgreSQL Full-Text Search for Phase 1

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Search must support title, filename, tags, and metadata. Semantic search is explicitly future scope.

### Decision

Use PostgreSQL `tsvector` + GIN index on `videos.search_vector`. Tags merged into search vector on tag mutation. API exposes `GET /search?q=...` only.

### Consequences

- **Positive:** No additional search infrastructure.
- **Positive:** Good enough for exact and stemmed keyword search.
- **Negative:** No semantic "find videos about cooking" without embeddings.
- **Negative:** Large libraries may need query tuning.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Meilisearch/Typesense sidecar | Extra service to operate |
| Elasticsearch | Heavy for homelab |
| SQLite FTS5 | Scale concerns |

---

## ADR-017: No Auxiliary Infrastructure in Phase 1 (Supersedes Optional Redis)

**Status:** Accepted  
**Date:** 2026-06-07  
**Supersedes:** Prior "optional Redis" proposal

### Context

Earlier planning considered optional Redis for job queues and feed caching. The project philosophy was revised to **monolith-first, homelab-simple**: avoid additional infrastructure unless a demonstrated requirement exists.

### Decision

Phase 1 will **not** include:

- Redis
- Message brokers (RabbitMQ, NATS, etc.)
- Dedicated search engines (Meilisearch, Elasticsearch)
- Vector databases (Qdrant, dedicated pgvector service)
- Separate worker containers

Job processing uses a PostgreSQL `jobs` table polled by the monolith. Search uses PostgreSQL FTS. Feed recommendations query PostgreSQL directly.

### Consequences

- **Positive:** Two-container deployment (`fovea` + `postgres`).
- **Positive:** Minimal operational burden for homelab users.
- **Positive:** Single code path for job processing.
- **Negative:** DB polling adds load during heavy FFmpeg batches (acceptable at homelab scale).
- **Negative:** If scale demands it, adding Redis or splitting the monolith is a future ADR — not a Phase 1 concern.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Optional Redis Compose profile | Still introduces code paths and tempts premature optimization |
| Redis required from day one | Unnecessary infrastructure for target scale |
| RabbitMQ / Celery | Heavier than needed; adds broker dependency |

---

## ADR-018: Future Optional Transcoding to Asset Store (Not Phase 1)

**Status:** Proposed  
**Date:** 2026-06-07

### Context

ADR-008 and ADR-023 exclude transcoding from Phase 1, but long-term browser compatibility may require proxy files.

### Decision (proposed)

If transcoding is added post-1.0, output files are written **only** to the asset store as `proxy` asset type. Source files remain untouched. Playback API serves proxy when browser compatibility check fails and proxy exists.

### Consequences

- **Positive:** Preserves read-only invariant.
- **Positive:** Opt-in per video or global policy.
- **Negative:** Significant storage increase for proxy files.
- **Negative:** FFmpeg CPU load.

### Status

Proposed — not approved for implementation. Documented to guide future design.

---

## ADR-019: Recommendation Provider Plugin Interface

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Phase 1 uses metadata scoring; future phases may use embeddings or AI. Hard-coding recommendation logic in API handlers creates rewrite risk.

### Decision

Define a `RecommendationProvider` protocol. Feed endpoints call the configured provider. Phase 1 registers `MetadataProvider` only.

### Consequences

- **Positive:** AI recommendations become additive.
- **Positive:** Testable scoring logic in isolation.
- **Negative:** Small abstraction overhead for simple Phase 1 scorer.

---

## ADR-021: Monolith-First Architecture

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Initial planning described separate API, web, and worker containers with optional Redis. Homelab users benefit from minimal operational complexity. Phase 1 does not have scale requirements that justify distributed architecture.

### Decision

Phase 1 is a **monolith**:

- One `fovea` container runs FastAPI, background tasks (watcher + job processor), and serves the built React frontend
- One `postgres` container for all persistent state
- Background modules (`watcher`, `jobs`) are Python packages within the monolith, not separate processes or containers

### Consequences

- **Positive:** Simplest possible deployment and debugging.
- **Positive:** No inter-service networking or orchestration beyond Compose.
- **Negative:** FFmpeg CPU load shares the API process; mitigated by concurrency limits.
- **Negative:** Monolith split requires a deliberate future ADR if scale demands it.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Separate worker container | Extra ops burden without demonstrated need |
| Microservices per domain | Over-engineering for homelab Phase 1 |
| Sidecar nginx container | Monolith can serve static files directly |

---

## ADR-022: Two-Container Homelab Deployment

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Self-hosters want `docker compose up` to work with minimal configuration. Each additional service (Redis, nginx, worker) increases failure modes and documentation burden.

### Decision

Production Docker Compose for Phase 1 contains exactly **two services**:

1. `fovea` — application monolith (port 8080)
2. `postgres` — database (internal network only)

Volumes: `fovea-db`, `fovea-assets`, plus user-supplied read-only media mounts.

### Consequences

- **Positive:** Trivial to reason about, backup, and restore.
- **Positive:** Aligns with homelab norms (similar complexity to *arr apps, Immich early versions).
- **Negative:** Operators who prefer separate frontend CDN must configure externally — not a Fovea concern.

---

## ADR-020: Stream Through API (Not Direct nginx File Serve)

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Video streaming can be served by nginx `sendfile` directly or proxied through FastAPI. Path validation is critical for security.

### Decision

Phase 1 streams through **FastAPI** with byte-range support. API validates video ID → DB path → watch path prefix before opening file. nginx `X-Accel-Redirect` may be reconsidered after v1 if performance requires it.

### Consequences

- **Positive:** Centralized path traversal protection.
- **Positive:** Consistent auth hook point for Phase 2.
- **Negative:** API process handles I/O; potential bottleneck at high concurrency.
- **Negative:** Slightly higher latency than direct nginx.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| Signed URL to nginx internal location | More moving parts for Phase 1 |
| Direct file path in frontend | Severe security risk |

---

## ADR-023: Phase 1 Codec Limitations Are Acceptable

**Status:** Accepted  
**Date:** 2026-06-07

### Context

Fovea streams user-owned files in place and does not import or duplicate source media. Browser playback support varies by container, video codec, audio codec, operating system, and browser. Solving every compatibility case requires transcoding, proxy files, or a separate playback service.

### Decision

Phase 1 does **not** transcode media in any form:

- No on-the-fly transcoding
- No pre-generated browser compatibility proxies
- No temporary transcode cache
- No sidecar media service

Unsupported browser codecs are an acceptable Phase 1 limitation. The API streams original files through FastAPI; the UI should show clear unsupported-codec or playback-failed states where possible.

### Consequences

- **Positive:** Preserves read-only and no-duplication guarantees.
- **Positive:** Avoids large CPU, storage, and operational costs in v1.
- **Positive:** Keeps the two-container deployment intact.
- **Negative:** Some indexed videos will not play in some browsers.
- **Negative:** Documentation and UI must set expectations clearly.

### Alternatives Considered

| Alternative | Rejected because |
|-------------|------------------|
| On-the-fly transcoding | CPU intensive; complex cancellation and temp storage lifecycle |
| Pre-generated proxy files | Storage duplication and heavy initial processing |
| Bundled media sidecar service | Adds infrastructure beyond the Phase 1 deployment contract |
| Client-side WASM decode | Browser performance and compatibility are not reliable enough |

---

## Decision Log Summary

| ADR | Decision | Status |
|-----|----------|--------|
| 001 | Read-only source media | Accepted |
| 002 | Index in place | Accepted |
| 003 | Video-centric model | Accepted |
| 004 | Folder watching primary | Accepted |
| 005 | Docker-first | Accepted |
| 006 | Container-canonical paths only | Accepted |
| 007 | FastAPI + PostgreSQL | Accepted |
| 008 | No transcoding Phase 1 | Accepted |
| 009 | Metadata recommendations | Accepted |
| 010 | 20% random injection | Accepted |
| 011 | Separate asset store | Accepted |
| 012 | Sprite hover previews for v1 | Accepted |
| 013 | Hybrid watcher | Accepted |
| 014 | Partial hash rename detection by default | Accepted |
| 015 | Single-user Phase 1 (no auth) | Accepted |
| 016 | PostgreSQL FTS | Accepted |
| 017 | No auxiliary infra Phase 1 | Accepted |
| 018 | Future proxy transcode | Proposed |
| 019 | Recommendation provider interface | Accepted |
| 020 | Stream through API | Accepted |
| 021 | Monolith-first architecture | Accepted |
| 022 | Two-container deployment | Accepted |
| 023 | Phase 1 codec limitations acceptable | Accepted |

---

## Decisions Requiring User Input

None at this time.

---

## Related Documents

- [PRD](./prd.md)
- [Architecture](./architecture.md)
- [Database Schema](./database.md)
- [API Specification](./api.md)
- [Implementation Phases](./phases.md)
