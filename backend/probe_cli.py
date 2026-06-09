#!/usr/bin/env python3
"""CLI tool to test ProbeService against a video file."""

import asyncio
import sys
import json
from pathlib import Path
from app.services.probe_service import ProbeService, ProbeError


async def main():
    if len(sys.argv) != 2:
        print("Usage: python -m app.services.probe_cli <video_path>")
        sys.exit(1)

    video_path = sys.argv[1]

    if not Path(video_path).exists():
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)

    try:
        print(f"\n🔍 Probing: {video_path}\n")
        result = await ProbeService.probe(video_path)

        print("✅ Probe successful!\n")
        print("📊 Metadata extracted:")
        print(f"  Duration:     {result.duration_seconds}s" if result.duration_seconds else "  Duration:     (unknown)")
        print(f"  Format:       {result.container_format}" if result.container_format else "  Format:       (unknown)")
        print(f"  Video Codec:  {result.video_codec}" if result.video_codec else "  Video Codec:  (unknown)")
        print(f"  Audio Codec:  {result.audio_codec}" if result.audio_codec else "  Audio Codec:  (unknown)")
        print(f"  Resolution:   {result.width}x{result.height}" if (result.width and result.height) else "  Resolution:   (unknown)")
        print(f"  Frame Rate:   {result.frame_rate:.2f} fps" if result.frame_rate else "  Frame Rate:   (unknown)")
        print(f"  Bitrate:      {result.bitrate} bps" if result.bitrate else "  Bitrate:      (unknown)")

        print("\n📋 Raw FFprobe output:")
        print(json.dumps(result.raw_ffprobe, indent=2)[:500] + "...")

    except ProbeError as e:
        print(f"❌ Probe failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
