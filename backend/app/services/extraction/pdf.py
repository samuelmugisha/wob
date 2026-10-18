import io
import statistics

from app.services.extraction.base import Block, ExtractionResult, UnreadableDocumentError
from app.services.extraction.ocr import Ocr

# A page with fewer extractable characters than this, but with images, is treated as scanned.
MIN_TEXT_CHARS = 25
OCR_RESOLUTION = 300
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 120


def extract(data: bytes, ocr: Ocr) -> ExtractionResult:
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        page_count = len(pdf.pages)
    except Exception as exc:  # pdfminer raises many unrelated types for bad input
        if "password" in repr(exc).lower():
            raise UnreadableDocumentError("the PDF is password-protected") from exc
        raise UnreadableDocumentError(f"the PDF could not be opened: {exc!r}") from exc

    result = ExtractionResult(blocks=[], method="pdf_text", pages=page_count)
    confidences: list[float] = []
    with pdf:
        for number, page in enumerate(pdf.pages, start=1):
            blocks = _page_blocks(page, number)
            has_text = sum(len(b.render()) for b in blocks) >= MIN_TEXT_CHARS
            if not has_text and page.images:
                image = page.to_image(resolution=OCR_RESOLUTION).original
                ocr_text = ocr.read(image)
                blocks = [
                    Block("paragraph", p.strip(), page=number)
                    for p in ocr_text.text.split("\n\n")
                    if p.strip()
                ]
                result.ocr_pages.append(number)
                if ocr_text.mean_confidence is not None:
                    confidences.append(ocr_text.mean_confidence)
            if not blocks:
                result.empty_pages.append(number)
            result.blocks.extend(blocks)

    if result.ocr_pages:
        result.method = "ocr" if len(result.ocr_pages) == result.pages else "pdf_text+ocr"
    if confidences:
        result.ocr_mean_confidence = statistics.fmean(confidences)
    return result


def _inside(obj: dict, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    mid_x = (obj["x0"] + obj["x1"]) / 2
    mid_y = (obj["top"] + obj["bottom"]) / 2
    return x0 <= mid_x <= x1 and top <= mid_y <= bottom


def _page_blocks(page, number: int) -> list[Block]:
    """Headings, paragraphs and tables of one page, in top-to-bottom order."""
    tables = page.find_tables()
    bboxes = [t.bbox for t in tables]
    positioned: list[tuple[float, Block]] = []

    for table in tables:
        rows = [[cell or "" for cell in row] for row in table.extract()]
        block = Block.table(rows, page=number)
        if block.rows:
            positioned.append((table.bbox[1], block))

    text_page = page.filter(
        lambda obj: obj.get("object_type") != "char" or not any(_inside(obj, b) for b in bboxes)
    )
    lines = text_page.extract_text_lines(return_chars=True, strip=True)
    sizes = [c["size"] for line in lines for c in line["chars"] if c["text"].strip()]
    body_size = statistics.median(sizes) if sizes else 0

    paragraph: list[str] = []
    paragraph_top = 0.0
    previous_bottom: float | None = None
    previous_height = 0.0

    def flush() -> None:
        if paragraph:
            positioned.append((paragraph_top, Block("paragraph", " ".join(paragraph), number)))
            paragraph.clear()

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        line_sizes = [c["size"] for c in line["chars"] if c["text"].strip()]
        size = statistics.fmean(line_sizes) if line_sizes else body_size
        is_heading = (
            body_size > 0
            and size >= body_size * HEADING_SIZE_RATIO
            and len(text) <= MAX_HEADING_CHARS
            and not text.endswith((".", ",", ";"))
        )
        height = line["bottom"] - line["top"]
        gap = line["top"] - previous_bottom if previous_bottom is not None else 0
        if is_heading:
            flush()
            level = 1 if size >= body_size * 1.5 else 2
            positioned.append((line["top"], Block("heading", text, number, level=level)))
        else:
            if paragraph and gap > max(height, previous_height) * 0.8:
                flush()
            if not paragraph:
                paragraph_top = line["top"]
            paragraph.append(text)
        previous_bottom = line["bottom"]
        previous_height = height
    flush()

    positioned.sort(key=lambda item: item[0])
    return [block for _, block in positioned]
