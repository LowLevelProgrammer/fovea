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
    """Scans watch paths for supported video files."""

    @staticmethod
    async def scan_path(watch_path: str, scan_recursive: bool = True) -> list[DiscoveredFile]:
        """
        Scan a watch path for supported video files.

        Args:
            watch_path: Absolute container path to scan
            scan_recursive: When True, walk subdirectories; when False, only immediate children

        Returns:
            List of DiscoveredFile objects

        Raises:
            FileNotFoundError: If watch_path does not exist
            PermissionError: If watch_path is not readable
        """
        discovered: list[DiscoveredFile] = []
        path_obj = Path(watch_path)

        if not path_obj.exists():
            raise FileNotFoundError(f"Watch path does not exist: {watch_path}")

        if not path_obj.is_dir():
            raise NotADirectoryError(f"Watch path is not a directory: {watch_path}")

        def _collect_file(file_path: Path) -> None:
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            try:
                stat = file_path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()

                discovered.append(
                    DiscoveredFile(
                        file_path=str(file_path),
                        file_size=stat.st_size,
                        file_mtime=mtime,
                        title=file_path.stem,
                        fingerprint=f"{stat.st_size}:{mtime.isoformat()}",
                    )
                )
            except (OSError, ValueError):
                # Skip files that cannot be stat'd or have invalid timestamps
                return

        try:
            if scan_recursive:
                for root, _, files in os.walk(watch_path):
                    for file in files:
                        _collect_file(Path(root) / file)
            else:
                for entry in os.listdir(watch_path):
                    file_path = path_obj / entry
                    if file_path.is_file():
                        _collect_file(file_path)
        except PermissionError as e:
            raise PermissionError(f"Permission denied reading watch path: {watch_path}") from e

        return discovered
