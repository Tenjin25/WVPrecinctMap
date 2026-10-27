"""OCR the precinct-level U.S. Senate rows in Calhoun County's 2010 PDF."""

from __future__ import annotations

import io
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(".vendor/rapidocr")))
sys.path.insert(0, str(Path(".vendor/pymupdf")))

import pymupdf
from PIL import Image
from rapidocr_onnxruntime import RapidOCR


SOURCE = Path("data/openelections-sources-wv/2010/Calhoun WV 2010 Election Results.pdf")
TARGETS = ("RAESE", "MANCHIN", "BECKER", "JOHNSON")


def first_integer(items: list[str]) -> int:
    for item in items:
        if re.fullmatch(r"\d+", item.strip()):
            return int(item)
    raise ValueError(f"No integer found in OCR tokens: {items!r}")


def main() -> None:
    engine = RapidOCR()
    document = pymupdf.open(SOURCE)
    for page_number, page in enumerate(document, 1):
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        image = image.crop((0, 0, image.width, 1900)).resize((image.width // 2, 950))
        result, _ = engine(image)
        texts = [item[1] for item in (result or [])]
        if not any("SENAT" in text.upper() for text in texts):
            continue
        precinct = next((text for text in texts if re.search(r"\d{4}\s+PRECINCT", text)), "")
        values: dict[str, int] = {}
        for target in TARGETS:
            def target_score(text: str) -> float:
                words = re.findall(r"[A-Z]+", text.upper())
                return max((SequenceMatcher(None, target, word).ratio() for word in words), default=0)

            index = max(
                range(len(texts)),
                key=lambda i: target_score(texts[i]),
            )
            score = target_score(texts[index])
            if score < 0.5:
                raise ValueError(f"Page {page_number}: no OCR match for {target}: {texts[index]!r}")
            values[target] = first_integer(texts[index + 1 : index + 8])
        print(page_number, precinct, values, flush=True)


if __name__ == "__main__":
    main()
