from urllib.parse import quote

from fastapi.responses import Response


def attachment(data: bytes, filename: str, media_type: str) -> Response:
    """A download response; the filename is RFC 6266/5987-encoded for non-ASCII names."""
    fallback = filename.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
