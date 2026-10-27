"""Optional CPU OCR for clearly text-dominant pages; figures/uncertainty fall back to vision."""

import io
import threading
from functools import lru_cache
from PIL import Image, ImageOps

LOCK = threading.RLock()


@lru_cache(maxsize=1)
def engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def text_page(content):
    try:
        import numpy as np
        import cv2

        with Image.open(io.BytesIO(content)) as source:
            rgb = np.array(ImageOps.exif_transpose(source).convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        ink = gray < 160
        ys = np.flatnonzero(ink.sum(1) > 3)
        bands = np.split(ys, np.where(np.diff(ys) > 2)[0] + 1) if len(ys) else []
        # A clear single-column page can bypass a detector that misses long print lines.
        if (gray > 235).mean() > 0.9 and 4 <= len(bands) <= 80 and all(5 <= len(b) <= 80 for b in bands):
            lines = []
            with LOCK:
                for band in bands:
                    xs = np.flatnonzero(ink[band[0] : band[-1] + 1].sum(0))
                    if len(xs) < 10:
                        break
                    if np.diff(xs).max() > 2 * len(band):
                        break
                    crop = rgb[max(0, band[0] - 4) : band[-1] + 5, max(0, xs[0] - 4) : xs[-1] + 5]
                    found, _ = engine()(crop, use_det=False, use_cls=False)
                    if not found or min(float(r[-1]) for r in found) < 0.90:
                        break
                    lines.extend(str(r[-2]) for r in found)
                else:
                    text = "\n".join(lines)
                    if len(text) >= 80:
                        return text, ["由本机OCR逐行识别，请对照原页核对单位、否定与数字"]
        with LOCK:
            result, _ = engine()(content)
        if not result:
            return None
        text = "\n".join(str(row[1]) for row in result)
        if len(text) < 80 or min(float(row[2]) for row in result) < 0.90:
            return None
        # Do not discard significant non-text marks/diagrams merely because some labels were readable.
        mask = np.zeros(gray.shape, dtype="uint8")
        for box, _, _ in result:
            cv2.fillPoly(mask, [np.array(box, dtype="int32")], 1)
        mask = cv2.dilate(mask, np.ones((5, 5), dtype="uint8"))
        ink = gray < 160
        coverage = float(((mask > 0) & ink).sum()) / max(1, int(ink.sum()))
        if coverage < 0.96:
            return None
        return text, ["由本机OCR识别，以文字为主；请对照原页核对单位、否定与数字"]
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
