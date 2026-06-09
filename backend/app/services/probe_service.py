import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProbeResult:
    """Typed result from FFprobe execution."""

    duration_seconds: Optional[float]
    container_format: Optional[str]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    width: Optional[int]
    height: Optional[int]
    frame_rate: Optional[float]
    bitrate: Optional[int]
    raw_ffprobe: dict


class ProbeError(Exception):
    """Base exception for probe failures."""

    pass


class FFprobeNotFoundError(ProbeError):
    """FFprobe binary not found in PATH."""

    pass


class ProbeFileNotFoundError(ProbeError):
    """Video file not found or not readable."""

    pass


class InvalidFormatError(ProbeError):
    """Video file format invalid or not supported."""

    pass


class ProbeTimeoutError(ProbeError):
    """FFprobe execution timed out."""

    pass


class ProbeJSONError(ProbeError):
    """Failed to parse FFprobe JSON output."""

    pass


class ProbeService:
    """Minimal FFprobe wrapper for video metadata extraction."""

    FFPROBE_TIMEOUT_SECONDS = 30
    FFPROBE_COMMAND = "ffprobe"

    @staticmethod
    async def probe(file_path: str) -> ProbeResult:
        """
        Execute ffprobe on video file and extract metadata.

        Args:
            file_path: Absolute path to video file

        Returns:
            ProbeResult with extracted metadata

        Raises:
            ProbeError: On any probe failure (see subclasses)
        """
        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            raise ProbeFileNotFoundError(f"Video file not found: {file_path}")
        if not path.is_file():
            raise ProbeFileNotFoundError(f"Path is not a file: {file_path}")

        # Build ffprobe command
        cmd = [
            ProbeService.FFPROBE_COMMAND,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        try:
            # Execute ffprobe as subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=ProbeService.FFPROBE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise ProbeTimeoutError(
                    f"FFprobe timed out after {ProbeService.FFPROBE_TIMEOUT_SECONDS}s"
                )

            # Check exit code
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                if "No such file or directory" in error_msg or process.returncode == 127:
                    raise FFprobeNotFoundError(
                        f"FFprobe binary not found. Install ffmpeg package. Error: {error_msg}"
                    )
                raise InvalidFormatError(
                    f"FFprobe failed with exit code {process.returncode}: {error_msg}"
                )

            # Parse JSON output
            try:
                output = json.loads(stdout.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise ProbeJSONError(f"Failed to parse FFprobe JSON output: {e}")

            # Extract format and stream information
            format_info = output.get("format", {})
            streams = output.get("streams", [])

            # Find video and audio streams
            video_stream = None
            audio_stream = None
            for stream in streams:
                if stream.get("codec_type") == "video" and video_stream is None:
                    video_stream = stream
                elif stream.get("codec_type") == "audio" and audio_stream is None:
                    audio_stream = stream

            # Extract and parse fields
            duration_seconds = None
            if "duration" in format_info:
                try:
                    duration_seconds = float(format_info["duration"])
                except (ValueError, TypeError):
                    pass

            container_format = format_info.get("format_name")

            video_codec = None
            width = None
            height = None
            frame_rate = None
            if video_stream:
                video_codec = video_stream.get("codec_name")
                width = video_stream.get("width")
                height = video_stream.get("height")

                # Parse frame rate (numerator/denominator format)
                frame_rate_str = video_stream.get("r_frame_rate")
                if frame_rate_str and "/" in frame_rate_str:
                    try:
                        num_str, denom_str = frame_rate_str.split("/")
                        num = float(num_str)
                        denom = float(denom_str)
                        if denom > 0:
                            frame_rate = num / denom
                    except (ValueError, ZeroDivisionError):
                        pass

            audio_codec = None
            if audio_stream:
                audio_codec = audio_stream.get("codec_name")

            bitrate = None
            if "bit_rate" in format_info:
                try:
                    bitrate = int(format_info["bit_rate"])
                except (ValueError, TypeError):
                    pass

            return ProbeResult(
                duration_seconds=duration_seconds,
                container_format=container_format,
                video_codec=video_codec,
                audio_codec=audio_codec,
                width=width,
                height=height,
                frame_rate=frame_rate,
                bitrate=bitrate,
                raw_ffprobe=output,
            )

        except asyncio.CancelledError:
            raise
        except ProbeError:
            raise
        except Exception as e:
            raise ProbeError(
                f"Unexpected error during probe: {e}"
            ) from e
