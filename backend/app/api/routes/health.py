from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import async_session

router = APIRouter()
settings = get_settings()


@router.get("/live")
async def live() -> dict[str, str]:
    return {
        "status": "ok",
        "application_name": settings.app_name,
        "application_version": settings.app_version,
    }


@router.get("/ready")
async def ready() -> dict[str, object]:
    database_status: dict[str, str | None] = {"status": "unknown", "detail": None}
    migration_status: dict[str, str | None] = {
        "status": "unknown",
        "revision": None,
        "detail": None,
    }

    try:
        async with async_session() as session:
            try:
                await session.execute(text("SELECT 1"))
                database_status = {"status": "connected", "detail": None}
            except Exception as exc:
                database_status = {"status": "unavailable", "detail": str(exc)}
                migration_status = {
                    "status": "unavailable",
                    "revision": None,
                    "detail": "Database is unavailable.",
                }
            else:
                try:
                    revision_result = await session.execute(
                        text(
                            """
                            SELECT version_num
                            FROM alembic_version
                            LIMIT 1
                            """
                        )
                    )
                    migration_revision = revision_result.scalar_one_or_none()
                    migration_status = {
                        "status": "available" if migration_revision else "unavailable",
                        "revision": migration_revision,
                        "detail": None if migration_revision else "No Alembic revision row found.",
                    }
                except Exception as exc:
                    migration_status = {
                        "status": "unavailable",
                        "revision": None,
                        "detail": str(exc),
                    }
    except Exception as exc:
        database_status = {"status": "unavailable", "detail": str(exc)}
        migration_status = {
            "status": "unavailable",
            "revision": None,
            "detail": "Database is unavailable.",
        }

    ready_status = (
        "ready"
        if database_status["status"] == "connected" and migration_status["status"] == "available"
        else "degraded"
    )

    return {
        "status": ready_status,
        "application_name": settings.app_name,
        "application_version": settings.app_version,
        "api": {"status": "running"},
        "database": database_status,
        "migrations": migration_status,
        "checked_at": datetime.now(timezone.utc),
    }
