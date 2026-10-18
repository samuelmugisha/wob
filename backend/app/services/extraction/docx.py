import io
import re

from app.services.extraction.base import Block, ExtractionResult, UnreadableDocumentError

_HEADING_STYLE = re.compile(r"^(?:heading|überschrift|titre)\s*(\d)", re.IGNORECASE)


def extract(data: bytes) -> ExtractionResult:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx/lxml raise many types for malformed packages
        raise UnreadableDocumentError(f"the Word document could not be opened: {exc!r}") from exc

    result = ExtractionResult(blocks=[], method="docx")
    # Walk the body in document order so tables stay between the paragraphs around them.
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = " ".join(item.text.split())
            if not text:
                continue
            style = (item.style.name if item.style is not None else "") or ""
            match = _HEADING_STYLE.match(style)
            if style.lower() == "title":
                result.blocks.append(Block("heading", text, level=1))
            elif match:
                result.blocks.append(Block("heading", text, level=int(match.group(1))))
            else:
                result.blocks.append(Block("paragraph", text))
        elif isinstance(item, Table):
            rows = _table_rows(item)
            block = Block.table(rows)
            if block.rows:
                result.blocks.append(block)
    return result


def _table_rows(table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        cells: list[str] = []
        previous = None
        for cell in row.cells:
            # Merged cells repeat the same object; keep one copy.
            if cell._tc is previous:
                continue
            previous = cell._tc
            cells.append(cell.text)
        rows.append(cells)
    return rows
