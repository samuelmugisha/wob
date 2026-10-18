import io

from PIL import Image, UnidentifiedImageError

from app.services.extraction.base import Block, ExtractionResult, UnreadableDocumentError
from app.services.extraction.ocr import Ocr


def extract(data: bytes, ocr: Ocr) -> ExtractionResult:
    try:
        # PIL's default MAX_IMAGE_PIXELS guard raises on decompression bombs.
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise UnreadableDocumentError(f"the image could not be read: {exc}") from exc

    text = ocr.read(image)
    blocks = [Block("paragraph", p.strip(), page=1) for p in text.text.split("\n\n") if p.strip()]
    return ExtractionResult(
        blocks=blocks,
        method="image_ocr",
        pages=1,
        ocr_pages=[1],
        ocr_mean_confidence=text.mean_confidence,
        empty_pages=[] if blocks else [1],
    )
