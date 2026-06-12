import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.services.filesystem_watcher import FileSystemWatcher
from app.services.probe_worker import ProbeWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    watcher: FileSystemWatcher | None = None

    if settings.filesystem_watcher_enabled:
        watcher = FileSystemWatcher()
        await watcher.start()

    worker = ProbeWorker()
    worker_task = asyncio.create_task(worker.run())

    yield

    if watcher is not None:
        await watcher.stop()

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    frontend_dist = Path(settings.frontend_dist_path)
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()

