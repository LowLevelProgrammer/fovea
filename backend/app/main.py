import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.services.filesystem_watcher import FileSystemWatcher
from app.services.probe_worker import ProbeWorker
from app.services.reconciliation_worker import ReconciliationWorker
from app.services.scan_service import ScanService


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    watcher: FileSystemWatcher | None = None

    # 1. Start ProbeWorker
    worker = ProbeWorker()
    worker_task = asyncio.create_task(worker.run())

    # 2. Start FileSystemWatcher (starts queuing FS events)
    if settings.filesystem_watcher_enabled:
        watcher = FileSystemWatcher()
        await watcher.start()

    # 3. Run ScanService.scan() synchronously if enabled
    # Critical infrastructure/database failures bubble up to fail startup and exit the process.
    if settings.startup_scan_enabled:
        logger.info("Starting startup library scan...")
        result = await ScanService.scan()
        logger.info(
            "Startup scan completed (scanned=%d, discovered=%d, unavailable=%d, duration=%.2fs)",
            result.watch_paths_scanned,
            result.videos_discovered,
            result.videos_unavailable,
            result.duration_seconds,
        )

    # 4. Start ReconciliationWorker
    reconciler = ReconciliationWorker()
    reconciler_task = asyncio.create_task(reconciler.run())

    yield

    # 1. Cancel and await ReconciliationWorker task
    reconciler_task.cancel()
    try:
        await reconciler_task
    except asyncio.CancelledError:
        pass

    # 2. Stop FileSystemWatcher
    if watcher is not None:
        await watcher.stop()

    # 3. Cancel and await ProbeWorker task
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

