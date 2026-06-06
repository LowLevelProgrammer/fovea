# Fovea

Fovea is a self-hosted, Docker-first video discovery platform.

This repository is currently at Phase 0, which is infrastructure scaffolding only:
application structure, Docker deployment, PostgreSQL connectivity, Alembic migrations, and
health checks. Phase 0 does not configure or scan watch paths; those are stored exclusively in
PostgreSQL and will be managed by Phase 1 APIs.

## Documentation

- [Product Requirements](docs/prd.md)
- [Architecture](docs/architecture.md)
- [Database Design](docs/database.md)
- [API Specification](docs/api.md)
- [Implementation Phases](docs/phases.md)
- [Architecture Decisions](docs/decisions.md)

## Phase 0 Quick Start

1. Copy the environment template:

   ```sh
   cp .env.example .env
   ```

2. Create a local media directory for the read-only mount placeholder:

   ```sh
   mkdir -p media
   ```

3. Start the two-container stack:

   ```sh
   docker compose up --build
   ```

4. Open the app:

   ```text
   http://localhost:8080/
   ```

Health endpoints:

- `GET http://localhost:8080/api/v1/health/live`
- `GET http://localhost:8080/api/v1/health/ready`

Phase 0 intentionally does not include folder watching, playback, recommendations, thumbnails,
FFmpeg processing, search, or watch history.
