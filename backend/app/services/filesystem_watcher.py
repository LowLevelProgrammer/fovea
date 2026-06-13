"""Filesystem monitoring via watchdog; triggers debounced ScanService scans."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import select
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import get_settings
from app.db.session import async_session
from app.models.watch_path import WatchPath
from app.services.scan_service import ScanService
from app.services.video_scanner import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

IGNORED_DIR_NAMES = frozenset({"@eaDir", "#recycle"})
IGNORED_SUFFIXES = (".tmp", ".part")


class WatchEventType(str, Enum):
    CREATED = "created"
    DELETED = "deleted"
    MODIFIED = "modified"
    MOVED = "moved"


@dataclass(frozen=True)
class WatchEvent:
    watch_path_id: UUID
    event_type: WatchEventType
    path: str


WatchPathEntry = tuple[UUID, str]


def should_ignore_path(path: str, *, is_directory: bool = False) -> bool:
    """Return True when a filesystem path should not trigger a scan."""
    path_obj = PurePosixPath(path)

    if any(part in IGNORED_DIR_NAMES for part in path_obj.parts):
        return True

    name = path_obj.name
    if name.startswith("."):
        return True

    if is_directory:
        return False

    if name.endswith(IGNORED_SUFFIXES):
        return True

    suffix = path_obj.suffix.lower()
    if suffix and suffix not in SUPPORTED_EXTENSIONS:
        return True

    return False


def resolve_watch_path_id(path: str, watch_paths: list[WatchPathEntry]) -> UUID | None:
    """Resolve a filesystem path to a watch path using longest-prefix matching."""
    path_obj = PurePosixPath(path)
    best_match: WatchPathEntry | None = None
    best_len = -1

    for watch_path_id, watch_root in watch_paths:
        root_obj = PurePosixPath(watch_root)
        if path_obj == root_obj or root_obj in path_obj.parents:
            if len(watch_root) > best_len:
                best_len = len(watch_root)
                best_match = (watch_path_id, watch_root)

    return best_match[0] if best_match else None


class ScanDebouncer:
    """Trailing-edge debounce with per-path scan serialization."""

    def __init__(self, debounce_seconds: float) -> None:
        self._debounce_seconds = debounce_seconds
        self._timers: dict[UUID, asyncio.Task] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._scanning: dict[UUID, bool] = {}
        self._rescan_pending: dict[UUID, bool] = {}
        self._shutdown = False

    def schedule(self, event: WatchEvent) -> None:
        """Reset the debounce timer for the event's watch path."""
        if self._shutdown:
            return

        watch_path_id = event.watch_path_id
        existing = self._timers.pop(watch_path_id, None)
        if existing is not None:
            existing.cancel()

        self._timers[watch_path_id] = asyncio.create_task(
            self._debounce_timer(watch_path_id),
            name=f"scan-debounce-{watch_path_id}",
        )

    async def shutdown(self) -> None:
        """Cancel pending timers and wait for in-flight scans."""
        self._shutdown = True

        timers = list(self._timers.values())
        self._timers.clear()
        for timer in timers:
            timer.cancel()

        if timers:
            await asyncio.gather(*timers, return_exceptions=True)

        in_flight = [wp_id for wp_id, active in self._scanning.items() if active]
        while any(self._scanning.get(wp_id, False) for wp_id in in_flight):
            await asyncio.sleep(0.05)

    def _get_lock(self, watch_path_id: UUID) -> asyncio.Lock:
        if watch_path_id not in self._locks:
            self._locks[watch_path_id] = asyncio.Lock()
        return self._locks[watch_path_id]

    async def _debounce_timer(self, watch_path_id: UUID) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
            await self._trigger_scan(watch_path_id)
        except asyncio.CancelledError:
            raise
        finally:
            current = self._timers.get(watch_path_id)
            if current is asyncio.current_task():
                self._timers.pop(watch_path_id, None)

    async def _trigger_scan(self, watch_path_id: UUID) -> None:
        if self._scanning.get(watch_path_id, False):
            self._rescan_pending[watch_path_id] = True
            return

        self._scanning[watch_path_id] = True
        try:
            async with self._get_lock(watch_path_id):
                while True:
                    self._rescan_pending[watch_path_id] = False
                    logger.info(
                        "Triggering debounced scan for watch_path_id=%s",
                        watch_path_id,
                    )
                    try:
                        result = await ScanService.scan(watch_path_id)
                        logger.info(
                            "Watcher scan completed for watch_path_id=%s "
                            "(discovered=%s, unavailable=%s, duration=%.2fs)",
                            watch_path_id,
                            result.videos_discovered,
                            result.videos_unavailable,
                            result.duration_seconds,
                        )
                    except Exception:
                        logger.exception(
                            "Watcher scan failed for watch_path_id=%s",
                            watch_path_id,
                        )
                        break

                    if not self._rescan_pending.get(watch_path_id, False):
                        break
        finally:
            self._scanning[watch_path_id] = False


class FoveaEventHandler(FileSystemEventHandler):
    """Watchdog callback that enqueues lightweight events for the asyncio consumer."""

    def __init__(
        self,
        watch_paths: list[WatchPathEntry],
        event_queue: asyncio.Queue[WatchEvent],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._watch_paths = watch_paths
        self._event_queue = event_queue
        self._loop = loop

    def on_created(self, event) -> None:
        self._handle_path(event.src_path, WatchEventType.CREATED, event.is_directory)

    def on_deleted(self, event) -> None:
        self._handle_path(event.src_path, WatchEventType.DELETED, event.is_directory)

    def on_modified(self, event) -> None:
        self._handle_path(event.src_path, WatchEventType.MODIFIED, event.is_directory)

    def on_moved(self, event) -> None:
        src_path = event.src_path
        dest_path = event.dest_path
        is_directory = event.is_directory

        src_ignored = should_ignore_path(src_path, is_directory=is_directory)
        dest_ignored = should_ignore_path(dest_path, is_directory=is_directory)

        src_id = None if src_ignored else resolve_watch_path_id(src_path, self._watch_paths)
        dest_id = None if dest_ignored else resolve_watch_path_id(dest_path, self._watch_paths)

        if src_id is None and dest_id is None:
            return

        if src_id is not None and dest_id is not None:
            if src_id == dest_id:
                self._enqueue(src_id, WatchEventType.MOVED, dest_path)
            else:
                self._enqueue(src_id, WatchEventType.MOVED, src_path)
                self._enqueue(dest_id, WatchEventType.MOVED, dest_path)
            return

        if src_id is not None:
            self._enqueue(src_id, WatchEventType.MOVED, src_path)
        if dest_id is not None:
            self._enqueue(dest_id, WatchEventType.MOVED, dest_path)

    def _handle_path(self, path: str, event_type: WatchEventType, is_directory: bool) -> None:
        if should_ignore_path(path, is_directory=is_directory):
            return

        watch_path_id = resolve_watch_path_id(path, self._watch_paths)
        if watch_path_id is None:
            return

        self._enqueue(watch_path_id, event_type, path)

    def _enqueue(self, watch_path_id: UUID, event_type: WatchEventType, path: str) -> None:
        watch_event = WatchEvent(
            watch_path_id=watch_path_id,
            event_type=event_type,
            path=path,
        )
        self._loop.call_soon_threadsafe(self._event_queue.put_nowait, watch_event)


class FileSystemWatcher:
    """Monitors enabled watch paths and triggers debounced ScanService scans."""

    OBSERVER_JOIN_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        settings = get_settings()
        self._debounce_seconds = settings.watch_debounce_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_queue: asyncio.Queue[WatchEvent] | None = None
        self._debouncer: ScanDebouncer | None = None
        self._consumer_task: asyncio.Task | None = None
        self._observer: Observer | None = None
        self._watch_path_entries: list[WatchPathEntry] = []

    async def start(self) -> None:
        """Load watch paths, start the observer, and begin consuming events."""
        self._loop = asyncio.get_running_loop()
        self._event_queue = asyncio.Queue()
        self._debouncer = ScanDebouncer(self._debounce_seconds)

        watch_paths = await self._load_enabled_watch_paths()
        self._watch_path_entries = [(wp.id, wp.path) for wp in watch_paths]

        if not watch_paths:
            logger.warning("FileSystemWatcher started with no enabled watch paths")
        else:
            self._start_observer(watch_paths)

        self._consumer_task = asyncio.create_task(
            self._consume_events(),
            name="filesystem-watcher-consumer",
        )
        logger.info(
            "FileSystemWatcher started (%s enabled watch path(s), debounce=%.1fs)",
            len(watch_paths),
            self._debounce_seconds,
        )

    async def stop(self) -> None:
        """Stop the observer, cancel debounce timers, and drain in-flight scans."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=self.OBSERVER_JOIN_TIMEOUT_SECONDS)
            self._observer = None

        if self._debouncer is not None:
            await self._debouncer.shutdown()
            self._debouncer = None

        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        logger.info("FileSystemWatcher stopped")

    async def _load_enabled_watch_paths(self) -> list[WatchPath]:
        async with async_session() as session:
            result = await session.execute(
                select(WatchPath).where(WatchPath.enabled.is_(True))
            )
            return list(result.scalars().all())

    def _start_observer(self, watch_paths: list[WatchPath]) -> None:
        assert self._loop is not None
        assert self._event_queue is not None

        handler = FoveaEventHandler(self._watch_path_entries, self._event_queue, self._loop)
        observer = Observer()
        scheduled = 0

        for wp in watch_paths:
            path = wp.path
            if not PurePosixPath(path).is_absolute():
                logger.warning("Skipping non-absolute watch path: %s", path)
                continue

            try:
                if not Path(path).exists():
                    logger.warning("Watch path does not exist: %s", path)
                    continue
                observer.schedule(handler, path, recursive=wp.scan_recursive)
                scheduled += 1
                logger.info(
                    "Watching %s (recursive=%s, watch_path_id=%s)",
                    path,
                    wp.scan_recursive,
                    wp.id,
                )
            except OSError:
                logger.exception("Failed to schedule watch for path: %s", path)

        if scheduled == 0:
            logger.warning("No watch paths could be scheduled with watchdog")
            return

        observer.start()
        self._observer = observer

    async def _consume_events(self) -> None:
        assert self._event_queue is not None
        assert self._debouncer is not None

        try:
            while True:
                event = await self._event_queue.get()
                logger.debug(
                    "Filesystem event queued: type=%s watch_path_id=%s path=%s",
                    event.event_type.value,
                    event.watch_path_id,
                    event.path,
                )
                self._debouncer.schedule(event)
        except asyncio.CancelledError:
            raise
