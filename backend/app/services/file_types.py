"""File type detection from content and safe ZIP expansion (spec §5.1)."""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class FileKind:
    label: str
    mime_type: str
    extension: str


PDF = FileKind("PDF", "application/pdf", ".pdf")
DOCX = FileKind(
    "DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
)
XLSX = FileKind(
    "XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
)
PNG = FileKind("PNG", "image/png", ".png")
JPEG = FileKind("JPEG", "image/jpeg", ".jpg")
ZIP = FileKind("ZIP", "application/zip", ".zip")

SUPPORTED_LABELS = "PDF, DOCX, XLSX, PNG, JPG or ZIP"


def detect_kind(data: bytes) -> FileKind | None:
    """Identify a file by its content, ignoring the name and the client-declared type."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            return None
        if "[Content_Types].xml" in names:
            if "word/document.xml" in names:
                return DOCX
            if "xl/workbook.xml" in names:
                return XLSX
            return None  # other Office formats (e.g. PPTX) are not supported
        return ZIP
    return None


def safe_filename(name: str | None) -> str:
    base = PurePosixPath((name or "").replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return cleaned[:255] or "unnamed"


class ArchiveError(ValueError):
    """The archive as a whole is unusable or exceeds limits."""


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    data: bytes


@dataclass(frozen=True)
class RejectedMember:
    path: str
    reason: str


def _is_unsafe_path(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return path.is_absolute() or ".." in path.parts or (len(name) > 1 and name[1] == ":")


def _is_ignored(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(part == "__MACOSX" for part in parts) or (bool(parts) and parts[-1].startswith("."))


def expand_archive(
    data: bytes, *, max_members: int, max_member_bytes: int, max_total_bytes: int
) -> tuple[list[ArchiveMember], list[RejectedMember]]:
    """Read archive members into memory with size and count limits.

    Members are never written to disk under their archive paths, so traversal is not
    exploitable, but such entries are still rejected as suspicious. Sizes are enforced on the
    actual decompressed bytes, not the headers, to defeat zip bombs.
    """
    members: list[ArchiveMember] = []
    rejected: list[RejectedMember] = []
    total = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("the ZIP archive is corrupt") from exc

    with zf:
        entries = [i for i in zf.infolist() if not i.is_dir() and not _is_ignored(i.filename)]
        if len(entries) > max_members:
            raise ArchiveError(f"the archive has more than {max_members} files")
        for info in entries:
            name = info.filename
            if _is_unsafe_path(name):
                rejected.append(RejectedMember(name, "unsafe path inside archive"))
                continue
            if info.flag_bits & 0x1:
                rejected.append(RejectedMember(name, "encrypted archive entries are not supported"))
                continue
            if info.file_size > max_member_bytes:
                rejected.append(RejectedMember(name, "file is larger than the size limit"))
                continue
            try:
                with zf.open(info) as fh:
                    content = fh.read(max_member_bytes + 1)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError):
                rejected.append(RejectedMember(name, "entry could not be read"))
                continue
            if len(content) > max_member_bytes:
                rejected.append(RejectedMember(name, "file is larger than the size limit"))
                continue
            total += len(content)
            if total > max_total_bytes:
                raise ArchiveError("the archive's uncompressed contents exceed the size limit")
            members.append(ArchiveMember(name, content))
    return members, rejected
