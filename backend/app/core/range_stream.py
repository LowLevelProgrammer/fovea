import os
import mimetypes
from typing import AsyncGenerator
import anyio
from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """
    Parse a range header string like 'bytes=500-999', 'bytes=500-', or 'bytes=-500'
    and return (start, end) byte indices.

    Supports standard single byte range request formats:
    - 'bytes=start-end': specific range of bytes (both inclusive)
    - 'bytes=start-': from start index to the end of the file
    - 'bytes=-suffix': last suffix bytes of the file

    For multi-range requests (e.g. 'bytes=0-0,5-10'), this implementation parses and
    services only the first range. This is standard for media streaming applications and
    compliant with RFC 7233 (which allows falling back to single range or full responses).

    If the requested 'end' index is greater than or equal to the file size, it is coerced
    to 'file_size - 1' per RFC 7233.

    Raises ValueError if:
    - The range header format is invalid.
    - The range is unsatisfiable (e.g., start >= file_size).
    - The start index is greater than the end index.
    """
    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range header format")
    
    range_str = range_header[6:].strip()
    if not range_str:
        raise ValueError("Empty range specification")
        
    first_range = range_str.split(",")[0].strip()
    
    if "-" not in first_range:
        raise ValueError("Invalid range format (missing hyphen)")
        
    start_str, end_str = first_range.split("-", 1)
    start_str = start_str.strip()
    end_str = end_str.strip()
    
    if not start_str and not end_str:
        raise ValueError("Both start and end are empty")
        
    if start_str and not start_str.isdigit():
        raise ValueError("Start is not a valid integer")
    if end_str and not end_str.isdigit():
        raise ValueError("End is not a valid integer")
        
    if start_str and end_str:
        start = int(start_str)
        end = int(end_str)
    elif start_str:
        start = int(start_str)
        end = file_size - 1
    else:  # end_str only (e.g. -500)
        suffix_len = int(end_str)
        if suffix_len == 0:
            raise ValueError("Suffix length cannot be zero")
        start = max(0, file_size - suffix_len)
        end = file_size - 1
        
    if start < 0 or start >= file_size:
        raise ValueError("Range is unsatisfiable")
        
    # Coerce end if it goes beyond the file size
    if end >= file_size:
        end = file_size - 1
        
    if start > end:
        raise ValueError("Start is greater than end")
        
    return start, end


async def file_sender(file_path: str, start: int, end: int, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
    """Async generator to stream a file chunk by chunk within a specified byte range."""
    async with await anyio.open_file(file_path, mode="rb") as f:
        await f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            to_read = min(remaining, chunk_size)
            data = await f.read(to_read)
            if not data:
                break
            remaining -= len(data)
            yield data


def range_stream_response(file_path: str, range_header: str | None) -> StreamingResponse:
    """
    Build a StreamingResponse supporting byte range requests.
    Raises HTTPException 416 if the range is unsatisfiable.
    Raises HTTPException 410 if the file does not exist on disk (representing an unavailable file).
    """
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Video file not found on disk.",
        )
        
    try:
        file_size = os.path.getsize(file_path)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file size: {str(e)}",
        )

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "video/mp4"

    if not range_header:
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        }
        return StreamingResponse(
            file_sender(file_path, 0, file_size - 1),
            status_code=status.HTTP_200_OK,
            headers=headers,
            media_type=mime_type,
        )

    try:
        start, end = parse_range_header(range_header, file_size)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
            detail="Requested range not satisfiable.",
        )

    content_length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(
        file_sender(file_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
        media_type=mime_type,
    )
