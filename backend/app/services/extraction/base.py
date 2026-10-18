from dataclasses import dataclass, field
from typing import Any, Literal


class ExtractionError(Exception):
    """Base class for extraction problems."""


class UnreadableDocumentError(ExtractionError):
    """The file itself can't be read (corrupt, password-protected). Retrying won't help."""


class OcrUnavailableError(ExtractionError):
    """OCR is needed but the OCR engine isn't installed. Retrying after setup will help."""


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str = ""
    page: int | None = None
    level: int = 1  # heading level; 1 is the top level
    rows: list[list[str]] = field(default_factory=list)  # tables only; rows[0] is the header

    @staticmethod
    def table(rows: list[list[str]], page: int | None = None) -> "Block":
        rows = [[" ".join(cell.split()) for cell in row] for row in rows]
        rows = [row for row in rows if any(row)]
        return Block("table", page=page, rows=rows)

    def render(self) -> str:
        if self.kind == "table":
            return "\n".join(render_row(row) for row in self.rows)
        return self.text


def render_row(row: list[str]) -> str:
    return "| " + " | ".join(row) + " |"


@dataclass
class ExtractionResult:
    blocks: list[Block]
    method: str
    pages: int | None = None
    ocr_pages: list[int] = field(default_factory=list)
    ocr_mean_confidence: float | None = None
    empty_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def quality(self) -> dict[str, Any]:
        characters = sum(len(b.render()) for b in self.blocks)
        quality: dict[str, Any] = {
            "method": self.method,
            "characters": characters,
            "tables": sum(1 for b in self.blocks if b.kind == "table"),
            "headings": sum(1 for b in self.blocks if b.kind == "heading"),
            "warnings": list(self.warnings),
        }
        if self.pages is not None:
            quality["pages"] = self.pages
            quality["empty_pages"] = self.empty_pages
        if self.ocr_pages:
            quality["ocr_pages"] = self.ocr_pages
        if self.ocr_mean_confidence is not None:
            quality["ocr_mean_confidence"] = round(self.ocr_mean_confidence, 1)
            if self.ocr_mean_confidence < 70:
                quality["warnings"].append("low OCR confidence: check the extracted text")
        if characters == 0:
            quality["warnings"].append("no text could be extracted")
        return quality
