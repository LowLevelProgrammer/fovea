from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.watch_paths import router as watch_paths_router
from app.api.routes.videos import router as videos_router
from app.api.routes.watch import router as watch_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(
    watch_paths_router,
    prefix="/library/watch-paths",
    tags=["library"],
)
api_router.include_router(videos_router)
api_router.include_router(watch_router, prefix="/watch")

