"""Text, table and structure extraction from stored originals (spec §5.1, FR-02).

Every extractor returns an ordered list of blocks (headings, paragraphs, tables) with page
references where the format has pages, plus quality indicators for reviewers.
"""

from app.services.extraction.base import (
    Block,
    ExtractionError,
    ExtractionResult,
    OcrUnavailableError,
    UnreadableDocumentError,
)
from app.services.extraction.ocr import Ocr

EXTRACTION_VERSION = "extract-v1"


def extract(data: bytes, mime_type: str, ocr: Ocr) -> ExtractionResult:
    from app.services.extraction import docx, image, pdf, xlsx
    from app.services.file_types import DOCX, JPEG, PDF, PNG, XLSX

    if mime_type == PDF.mime_type:
        return pdf.extract(data, ocr)
    if mime_type == DOCX.mime_type:
        return docx.extract(data)
    if mime_type == XLSX.mime_type:
        return xlsx.extract(data)
    if mime_type in (PNG.mime_type, JPEG.mime_type):
        return image.extract(data, ocr)
    raise UnreadableDocumentError(f"no extractor for {mime_type}")


__all__ = [
    "EXTRACTION_VERSION",
    "Block",
    "ExtractionError",
    "ExtractionResult",
    "Ocr",
    "OcrUnavailableError",
    "UnreadableDocumentError",
    "extract",
]
