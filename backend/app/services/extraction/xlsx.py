import io
import zipfile
from datetime import date, datetime

from app.services.extraction.base import Block, ExtractionResult, UnreadableDocumentError


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        midnight = value.time() == datetime.min.time()
        return value.date().isoformat() if midnight else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def extract(data: bytes) -> ExtractionResult:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise UnreadableDocumentError(f"the spreadsheet could not be opened: {exc}") from exc

    result = ExtractionResult(blocks=[], method="xlsx")
    if any(sheet.sheet_state != "visible" for sheet in workbook.worksheets):
        result.warnings.append("workbook has hidden sheets; their contents were included")
    try:
        for sheet in workbook.worksheets:
            rows = [[_cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
            rows = [row for row in rows if any(cell.strip() for cell in row)]
            if not rows:
                continue
            # Drop columns that are empty in every row.
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            keep = [i for i in range(width) if any(r[i].strip() for r in rows)]
            rows = [[r[i] for i in keep] for r in rows]
            result.blocks.append(Block("heading", f"Sheet: {sheet.title}", level=1))
            result.blocks.append(Block.table(rows))
    finally:
        workbook.close()
    return result
