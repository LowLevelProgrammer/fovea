import asyncio
import logging
from app.core.config import get_settings
from app.services.scan_service import ScanService

logger = logging.getLogger(__name__)


class ReconciliationWorker:
    """Periodically triggers a full ScanService.scan() to reconcile database state with filesystem state."""

    async def run(self) -> None:
        settings = get_settings()
        if not settings.reconciliation_enabled:
            logger.info("Reconciliation worker is disabled.")
            return

        interval = settings.reconciliation_interval_seconds
        logger.info(
            "Reconciliation worker started (interval=%.1fs / %.1f hours)",
            interval,
            interval / 3600.0,
        )

        while True:
            try:
                await asyncio.sleep(interval)
                logger.info("Starting scheduled reconciliation scan...")
                result = await ScanService.scan()
                logger.info(
                    "Reconciliation scan completed (scanned=%d, discovered=%d, unavailable=%d, duration=%.2fs)",
                    result.watch_paths_scanned,
                    result.videos_discovered,
                    result.videos_unavailable,
                    result.duration_seconds,
                )
            except asyncio.CancelledError:
                logger.info("Reconciliation worker task cancelled.")
                raise
            except Exception:
                logger.exception("Reconciliation worker encountered an error")
