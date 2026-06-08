from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.watch_paths import router as watch_paths_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(
    watch_paths_router,
    prefix="/library/watch-paths",
    tags=["library"],
)

