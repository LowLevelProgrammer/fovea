import os
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"
}


@dataclass
class DiscoveredFile:
    """Metadata for a discovered video file."""
    file_path: str
    file_size: int
    file_mtime: datetime
    title: str
    fingerprint: str


class VideoScanner:
    """Recursively scans directories for supported video files."""

    @staticmethod
    async def scan_path(watch_path: str) -> list[DiscoveredFile]:
        """
        Recursively scan a watch path for supported video files.

        Args:
            watch_path: Absolute container path to scan

        Returns:
            List of DiscoveredFile objects

        Raises:
            FileNotFoundError: If watch_path does not exist
            PermissionError: If watch_path is not readable
        """
        discovered = []
        path_obj = Path(watch_path)

        if not path_obj.exists():
            raise FileNotFoundError(f"Watch path does not exist: {watch_path}")

        if not path_obj.is_dir():
            raise NotADirectoryError(f"Watch path is not a directory: {watch_path}")

        try:
            for root, _, files in os.walk(watch_path):
                for file in files:
                    file_path = Path(root) / file

                    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue

                    try:
                        stat = file_path.stat()
                        mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()

                        fingerprint = f"{stat.st_size}:{mtime.isoformat()}"
                        title = file_path.stem

                        discovered.append(
                            DiscoveredFile(
                                file_path=str(file_path),
                                file_size=stat.st_size,
                                file_mtime=mtime,
                                title=title,
                                fingerprint=fingerprint,
                            )
                        )
                    except (OSError, ValueError):
                        # Skip files that cannot be stat'd or have invalid timestamps
                        continue
        except PermissionError as e:
            raise PermissionError(f"Permission denied reading watch path: {watch_path}") from e

        return discovered
