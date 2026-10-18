from dataclasses import dataclass

from PIL import Image

from app.services.extraction.base import OcrUnavailableError


@dataclass(frozen=True)
class OcrText:
    text: str
    mean_confidence: float | None  # 0-100, over recognised words


class Ocr:
    """Tesseract OCR. The binary must be installed (it is in the worker image)."""

    def __init__(self, languages: str = "eng") -> None:
        self.languages = languages

    def available(self) -> bool:
        import pytesseract

        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError:
            return False
        return True

    def read(self, image: Image.Image) -> OcrText:
        import pytesseract

        try:
            data = pytesseract.image_to_data(
                image.convert("RGB"), lang=self.languages, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError("OCR engine (tesseract) is not installed") from exc

        # Rebuild text line by line from word boxes, keeping Tesseract's reading order.
        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
            confidence = float(data["conf"][i])
            if confidence >= 0:
                confidences.append(confidence)

        paragraphs: dict[tuple[int, int], list[str]] = {}
        for (block, par, _), words in lines.items():
            paragraphs.setdefault((block, par), []).append(" ".join(words))
        text = "\n\n".join(" ".join(p) for p in paragraphs.values())
        mean = sum(confidences) / len(confidences) if confidences else None
        return OcrText(text, mean)
