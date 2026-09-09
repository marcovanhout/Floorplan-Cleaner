"""Raster + OCR fallback (MODE B: geen bruikbare CAD-lagen, bv. platgeslagen/gescande PDF)."""

import logging

import numpy as np
from PIL import Image

from .render import render_page

logger = logging.getLogger(__name__)


def is_tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _saturation(rgb: np.ndarray) -> np.ndarray:
    """HSV-verzadiging van een (H, W, 3) float-array in [0, 1], zonder matplotlib.

    S = (max - min) / max, 0 waar max == 0 (zuiver zwart telt niet als 'gekleurd').
    """
    cmax = rgb.max(axis=2)
    cmin = rgb.min(axis=2)
    sat = np.zeros_like(cmax)
    nonzero = cmax > 0
    sat[nonzero] = (cmax[nonzero] - cmin[nonzero]) / cmax[nonzero]
    return sat


def clean_via_raster(
    page, scale: float, sat_threshold: float = 0.12, remove_text: bool = True
) -> tuple[Image.Image, list[tuple[int, int, int, int, str]]]:
    img = render_page(page, scale, alpha=False)
    arr = np.array(img).astype(np.float32) / 255.0

    sat = _saturation(arr)
    colored_mask = sat > sat_threshold
    work = arr.copy()
    work[colored_mask] = [1, 1, 1]

    ocr_boxes: list[tuple[int, int, int, int, str]] = []
    if remove_text:
        if not is_tesseract_available():
            logger.warning(
                "OCR-tekstverwijdering overgeslagen: Tesseract-OCR is niet beschikbaar op dit systeem."
            )
        else:
            import pytesseract

            try:
                gray_for_ocr = (work.mean(axis=2) * 255).astype(np.uint8)
                ocr_img = Image.fromarray(gray_for_ocr)
                data = pytesseract.image_to_data(ocr_img, output_type=pytesseract.Output.DICT)
                n = len(data["text"])
                erased = 0
                for i in range(n):
                    txt = data["text"][i].strip()
                    conf = int(data["conf"][i]) if data["conf"][i] not in ("", "-1") else -1
                    if txt and conf > 30:
                        x, y, w, h = (
                            data["left"][i],
                            data["top"][i],
                            data["width"][i],
                            data["height"][i],
                        )
                        ocr_boxes.append((x, y, x + w, y + h, txt))
                        pad = max(2, int(0.15 * h))
                        x0, y0 = max(0, x - pad), max(0, y - pad)
                        x1, y1 = min(work.shape[1], x + w + pad), min(work.shape[0], y + h + pad)
                        work[y0:y1, x0:x1] = [1, 1, 1]
                        erased += 1
                logger.info("OCR: %d tekstblokken weggehaald.", erased)
            except Exception as e:
                logger.warning("OCR-tekstverwijdering overgeslagen (%s).", e)

    gray = work.mean(axis=2)
    L = (gray * 255).astype(np.uint8)
    # Een rechtstreekse alpha = 255-L geeft dunne/anti-aliased lijnen een
    # zwakke dekking (een lichtgrijs randpixel wordt een bijna onzichtbaar
    # doorzichtig pixel) - muren waren daardoor nauwelijks te onderscheiden
    # van de transparante achtergrond. Elk zichtbaar (niet-wit) pixel wordt
    # daarom volledig ondoorzichtig zwart, puur transparant/zwart in plaats
    # van een geleidelijke overgang - past ook beter bij het doel (schone
    # lijntekening, geen grijswaarden-render).
    alpha = np.where(L < 250, 255, 0).astype(np.uint8)
    rgb_out = np.zeros((*L.shape, 3), dtype=np.uint8)
    out = np.dstack([rgb_out, alpha])
    return Image.fromarray(out, "RGBA"), ocr_boxes
