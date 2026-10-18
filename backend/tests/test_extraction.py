import io
import zipfile

import pytest

from app.services.extraction import Ocr, OcrUnavailableError, UnreadableDocumentError, extract
from app.services.file_types import DOCX, PDF, PNG, XLSX
from tests import fixture_files

ocr = Ocr()
needs_tesseract = pytest.mark.skipif(not ocr.available(), reason="tesseract is not installed")


def test_pdf_text_headings_and_tables() -> None:
    result = extract(fixture_files.pdf_with_structure(), PDF.mime_type, ocr)
    assert result.method == "pdf_text"
    assert result.pages == 2

    headings = [(b.text, b.level, b.page) for b in result.blocks if b.kind == "heading"]
    assert ("Nomination statement", 1, 1) in headings
    assert ("Board appointments", 2, 1) in headings
    assert ("Community leadership", 2, 2) in headings

    tables = [b for b in result.blocks if b.kind == "table"]
    assert len(tables) == 1
    assert tables[0].rows[0] == ["Year", "Organisation", "Role"]
    assert ["2021", "Example Holdings", "Audit Chair"] in tables[0].rows

    # Table text isn't duplicated into paragraphs, and order follows the page.
    paragraphs = " ".join(b.text for b in result.blocks if b.kind == "paragraph")
    assert "Audit Chair" not in paragraphs
    assert "chair of the audit committee" in paragraphs
    kinds = [b.kind for b in result.blocks]
    assert kinds.index("table") > kinds.index("heading")
    assert result.quality()["tables"] == 1


def test_password_protected_pdf_is_unreadable() -> None:
    data = fixture_files.pdf_with_structure(encrypt="secret")
    with pytest.raises(UnreadableDocumentError, match="password"):
        extract(data, PDF.mime_type, ocr)


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(UnreadableDocumentError):
        extract(b"%PDF-1.7\nthis is not really a pdf", PDF.mime_type, ocr)


def test_docx_keeps_order_headings_and_tables() -> None:
    result = extract(fixture_files.docx_document(), DOCX.mime_type, ocr)
    assert [b.kind for b in result.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "table",
        "paragraph",
    ]
    assert result.blocks[0].text == "Supporting letter"
    assert result.blocks[2].level == 2
    assert result.blocks[3].rows == [["Organisation", "Role"], ["Example Holdings", "Audit Chair"]]


def test_broken_docx_is_unreadable() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "not xml")
    with pytest.raises(UnreadableDocumentError):
        extract(buffer.getvalue(), DOCX.mime_type, ocr)


def test_xlsx_sheets_become_tables() -> None:
    result = extract(fixture_files.xlsx_workbook(), XLSX.mime_type, ocr)
    assert [b.kind for b in result.blocks] == ["heading", "table"]
    assert result.blocks[0].text == "Sheet: Attendance"
    assert result.blocks[1].rows == [
        ["Meeting date", "Attended", "Notes"],
        ["2025-03-14", "Yes", "Chaired"],
        ["2025-06-20", "Yes", "4"],
    ]


def test_ocr_unavailable_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytesseract

    def missing(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", missing)
    with pytest.raises(OcrUnavailableError):
        extract(fixture_files.text_image("Board minutes"), PNG.mime_type, ocr)


@needs_tesseract
def test_image_ocr() -> None:
    result = extract(
        fixture_files.text_image("Appointed Chair of the Board\nin March 2022"), PNG.mime_type, ocr
    )
    text = " ".join(b.text for b in result.blocks)
    assert "Chair of the Board" in text
    assert result.method == "image_ocr"
    assert result.ocr_mean_confidence is not None and result.ocr_mean_confidence > 60


@needs_tesseract
def test_scanned_pdf_pages_are_ocred() -> None:
    result = extract(fixture_files.scanned_pdf("Certificate of Directorship"), PDF.mime_type, ocr)
    assert result.ocr_pages == [1]
    assert result.method == "ocr"
    assert "Certificate of Directorship" in " ".join(b.text for b in result.blocks)
