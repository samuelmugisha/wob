"""Malware scanning of stored originals before any parsing (spec §5.1)."""

import socket
import struct
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    scanner: str
    signature: str | None = None


class ScannerError(Exception):
    """The scan could not be completed; the document should be retried, not trusted."""


class Scanner(Protocol):
    def scan(self, data: bytes) -> ScanResult: ...


class ClamdScanner:
    """Streams bytes to a clamd daemon with the INSTREAM command."""

    CHUNK = 64 * 1024

    def __init__(self, host: str, port: int, timeout: float = 120) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.sendall(b"zINSTREAM\0")
                for start in range(0, len(data), self.CHUNK):
                    piece = data[start : start + self.CHUNK]
                    conn.sendall(struct.pack("!L", len(piece)) + piece)
                conn.sendall(struct.pack("!L", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = conn.recv(4096)
                    if not part:
                        break
                    reply += part
        except OSError as exc:
            raise ScannerError(
                f"virus scanner unavailable at {self.host}:{self.port}: {exc}"
            ) from exc

        message = reply.rstrip(b"\0").decode(errors="replace").strip()
        # Replies: "stream: OK", "stream: <signature> FOUND", "<details> ERROR".
        if message.endswith("OK"):
            return ScanResult(clean=True, scanner="clamav")
        if message.endswith("FOUND"):
            signature = message.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanResult(clean=False, scanner="clamav", signature=signature)
        raise ScannerError(f"virus scan failed: {message or 'no reply'}")


class DisabledScanner:
    """Development only. Documents are marked as not scanned in their quality record."""

    def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=True, scanner="disabled")


def get_scanner(settings: Settings) -> Scanner:
    if settings.scanner == "clamav":
        return ClamdScanner(settings.clamd_host, settings.clamd_port)
    if settings.scanner == "disabled":
        if settings.environment == "production":
            raise ValueError("malware scanning cannot be disabled in production")
        return DisabledScanner()
    raise ValueError(f"unknown scanner {settings.scanner!r}")
