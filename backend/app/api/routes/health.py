from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
async def ready(response: Response) -> dict[str, str | None]:
    async with async_session() as session:
        try:
            await session.execute(text("SELECT 1"))
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
        except SQLAlchemyError as exc:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "error",
                "application_name": settings.app_name,
                "application_version": settings.app_version,
                "database": "unavailable",
                "migration_revision": None,
                "checked_at": datetime.now(UTC).isoformat(),
                "detail": str(exc),
            }

    return {
        "status": "ok",
        "application_name": settings.app_name,
        "application_version": settings.app_version,
        "database": "connected",
        "migration_revision": migration_revision,
        "background_last_seen": None,
        "checked_at": datetime.now(UTC).isoformat(),
    }
