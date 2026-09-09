"""Raster + OCR fallback (MODE B: geen bruikbare CAD-lagen, bv. platgeslagen/gescande PDF)."""

import logging
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .render import render_page

logger = logging.getLogger(__name__)

# De Tesseract-Windows-installer (zie README) voegt zichzelf niet altijd toe
# aan de PATH-omgevingsvariabele (een vinkje dat niet standaard aanstaat) -
# zonder deze fallback zou elke gebruiker bij wie dat vinkje uit stond zelf
# zijn systeeminstellingen moeten aanpassen, terwijl het programma gewoon op
# schijf staat. Eerst PATH proberen (normale/verwachte situatie), pas als dat
# niks oplevert deze standaardlocaties controleren.
_COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

_tesseract_cmd_resolved = False  # eenmalig zoeken, niet bij elke aanroep een proces starten


def _ensure_tesseract_cmd() -> None:
    global _tesseract_cmd_resolved
    if _tesseract_cmd_resolved:
        return
    _tesseract_cmd_resolved = True

    import pytesseract

    if shutil.which(pytesseract.pytesseract.tesseract_cmd):
        return  # al vindbaar via PATH, niks aan te passen
    for candidate in _COMMON_TESSERACT_PATHS:
        if Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def is_tesseract_available() -> bool:
    try:
        import pytesseract

        _ensure_tesseract_cmd()
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# Tesseract herkent standaard vooral horizontale tekst - ruimtenamen in een
# scheve/gedraaide plattegrond staan vaak verticaal en werden daardoor
# helemaal niet gevonden. Oplossing: de afbeelding in alle 4 standen (0/90/
# 180/270 graden) langs OCR halen; k = aantal stappen van 90 graden met de
# klok mee dat is toegepast VOORDAT die pas draait.
_OCR_ROTATIONS = [
    (0, None),
    (1, Image.Transpose.ROTATE_270),  # 90 graden met de klok mee
    (2, Image.Transpose.ROTATE_180),
    (3, Image.Transpose.ROTATE_90),  # 90 graden tegen de klok in (= 270 met de klok mee)
]


def _unrotate_box(
    box: tuple[int, int, int, int], k: int, orig_w: int, orig_h: int
) -> tuple[int, int, int, int]:
    """Herleidt een bbox die gevonden is in een gedraaide variant van de
    afbeelding (zie _OCR_ROTATIONS) terug naar coordinaten in de
    ONgedraaide afbeelding. Elke formule hieronder is losstaand geverifieerd
    tegen een testrechthoek door de bijbehorende PIL-transpose."""
    x0, y0, x1, y1 = box
    if k == 0:
        return x0, y0, x1, y1
    if k == 1:  # ROTATE_270 (90 graden CW)
        return y0, orig_h - x1, y1, orig_h - x0
    if k == 2:  # ROTATE_180
        return orig_w - x1, orig_h - y1, orig_w - x0, orig_h - y0
    return orig_w - y1, x0, orig_w - y0, x1  # k == 3, ROTATE_90 (90 graden CCW)


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


def _colored_mask(
    rgb: np.ndarray,
    sat_threshold: float,
    local_window: int = 5,
    local_delta: float = 0.1,
    downsample: int = 3,
) -> np.ndarray:
    """Welke pixels tellen als "gekleurd vlak" (en dus weg te vlakken)?

    Puur op verzadiging afgaan is niet genoeg: waar een zwarte lijn (bv. een
    deurzwaai) over een gekleurd vlak getekend is, ontstaat door anti-aliasing
    een mengkleur die numeriek toch een hoge verzadiging heeft - (max-min)/max
    is instabiel vlak bij zwart. Zo'n lijn-pixel is dus ondanks die "kleur"
    duidelijk donkerder dan het vlak eromheen - maar HOEVEEL donkerder
    verschilt sterk per lijn (een dunne deurzwaai over een fel kleurvlak kan
    best licht ogen) en per klantbestand (elke tekenaar gebruikt andere
    kleuren). Een vaste helderheidsgrens ("alles onder X is een lijn") bleek
    daardoor niet betrouwbaar: te streng en dunne lijnen verdwijnen alsnog,
    te soepel en er blijft kleurresidu staan.

    In plaats daarvan wordt elke pixel vergeleken met de MEDIAAN-helderheid
    in zijn directe omgeving (een klein venster) - dat is een schatting van
    de "echte" vlakkleur ter plekke, ongevoelig voor een dunne lijn (die
    binnen zo'n venster altijd in de minderheid is, of hij nu donkerder of
    lichter is dan het vlak). Een MAX-venster bleek niet te gebruiken: vlak-
    pixels naast een lichte (bijna-witte) hulplijn in het kleurvlak kregen
    daardoor zelf ook een hoge lokale max, leken zo "opvallend donkerder"
    dan hun buren, en werden per ongeluk als lijn behandeld - met dikke
    zwarte vegen langs die hulplijnen tot gevolg. Alleen pixels die
    duidelijk DONKERDER zijn dan hun lokale mediaan blijven als lijn staan.

    Een mediaanfilter op volle resolutie is op een groot ingescand blad
    (tientallen miljoenen pixels) te traag (tientallen seconden). De lokale
    vlakkleur verandert echter alleen op kamerschaal, niet van pixel tot
    pixel - de mediaan hoeft dus niet op elke pixel apart berekend te worden.
    Eerst uitdunnen (elke `downsample`-ste pixel), daar het venster op
    toepassen, en weer terug opschalen is >100x sneller en geeft vrijwel
    dezelfde uitkomst.
    """
    cmax = rgb.max(axis=2)
    small = cmax[::downsample, ::downsample]
    local_median_small = ndimage.median_filter(small, size=local_window)
    local_median = np.repeat(np.repeat(local_median_small, downsample, axis=0), downsample, axis=1)
    local_median = local_median[: cmax.shape[0], : cmax.shape[1]]
    is_line_like = (local_median - cmax) > local_delta
    return (_saturation(rgb) > sat_threshold) & ~is_line_like


def clean_via_raster(
    page, scale: float, sat_threshold: float = 0.12, remove_text: bool = True
) -> tuple[Image.Image, list[tuple[int, int, int, int, str]]]:
    img = render_page(page, scale, alpha=False)
    arr = np.array(img).astype(np.float32) / 255.0

    colored_mask = _colored_mask(arr, sat_threshold)
    work = arr.copy()
    work[colored_mask] = [1, 1, 1]

    ocr_boxes: list[tuple[int, int, int, int, str]] = []
    if remove_text:
        if not is_tesseract_available():
            logger.warning(
                "OCR text removal skipped: Tesseract-OCR is not available on this system."
            )
        else:
            import pytesseract

            orig_h, orig_w = work.shape[:2]
            erased = 0
            try:
                for k, transpose in _OCR_ROTATIONS:
                    # Elke pas opnieuw vanuit de (inmiddels deels al
                    # opgeschoonde) 'work' opbouwen: al gevonden/gewiste
                    # tekst uit een vorige rotatie hoeft dan niet nog eens
                    # (met mogelijk minder zekerheid) herkend te worden.
                    gray_for_ocr = (work.mean(axis=2) * 255).astype(np.uint8)
                    ocr_img = Image.fromarray(gray_for_ocr)
                    if transpose is not None:
                        ocr_img = ocr_img.transpose(transpose)
                    data = pytesseract.image_to_data(ocr_img, output_type=pytesseract.Output.DICT)
                    n = len(data["text"])
                    for i in range(n):
                        txt = data["text"][i].strip()
                        conf = int(data["conf"][i]) if data["conf"][i] not in ("", "-1") else -1
                        if not txt or conf <= 30:
                            continue
                        rx, ry, rw, rh = (
                            data["left"][i],
                            data["top"][i],
                            data["width"][i],
                            data["height"][i],
                        )
                        x0, y0, x1, y1 = _unrotate_box((rx, ry, rx + rw, ry + rh), k, orig_w, orig_h)
                        ocr_boxes.append((x0, y0, x1, y1, txt))
                        pad = max(2, int(0.15 * (y1 - y0)))
                        px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
                        px1, py1 = min(orig_w, x1 + pad), min(orig_h, y1 + pad)
                        work[py0:py1, px0:px1] = [1, 1, 1]
                        erased += 1
                logger.info(
                    "OCR: %d text blocks removed (checked at 0/90/180/270 degrees).", erased
                )
            except Exception as e:
                logger.warning("OCR text removal skipped (%s).", e)

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
