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


def _local_median_color(rgb: np.ndarray, local_window: int, downsample: int) -> np.ndarray:
    """Schat de "echte" vlakkleur ter plekke van elke pixel: de mediaankleur
    (per kanaal apart) in een klein venster eromheen - ongevoelig voor een
    dunne lijn erdoorheen, die binnen zo'n venster altijd in de minderheid
    is. Zie _colored_mask voor waarom dit nodig is en waarom uitgedund wordt
    vóór het filter (snelheid op een groot blad)."""
    small = rgb[::downsample, ::downsample, :]
    median_small = np.stack(
        [ndimage.median_filter(small[..., c], size=local_window) for c in range(3)], axis=-1
    )
    median = np.repeat(np.repeat(median_small, downsample, axis=0), downsample, axis=1)
    return median[: rgb.shape[0], : rgb.shape[1], :]


def _hue_matches(rgb: np.ndarray, reference_rgb: np.ndarray, neutral_floor: float = 0.02) -> np.ndarray:
    """Heeft een pixel dezelfde kleurzweem als een referentiekleur (de lokale
    vlakkleur, zie _local_median_color), ongeacht hoe donker/licht hij is?

    Vergelijkt de kleur-RICHTING (elk kanaal min het grijzeanteel, dus zonder
    helderheid) via cosinus-gelijkenis - alleen de tint telt, niet hoe donker
    de pixel is. Alleen een pixel ZONDER noemenswaardige eigen kleur (bijna
    grijs/zwart) telt altijd als "passend", ongeacht de referentie - zo'n
    pixel introduceert nooit een eigen, vreemde kleur (dit is ook het meest
    voorkomende geval: een gewone zwarte lijn op een wit vlak). `neutral_floor`
    is een ABSOLUTE (geen genormaliseerde/verhouding-)drempel, gecalibreerd
    op een echt testbestand: normale anti-aliasing-ruis van een zwarte lijn
    bleek daar zo goed als 0 (99e percentiel exact 0.0), terwijl een echt
    gekleurde maar heel donkere pixel (bv. een blauwe arceringslijn die in
    zijn kern bijna zwart rendert) een duidelijk meetbare 0.04 gaf - een
    verhouding-gebaseerde maat zoals _saturation() zou hier juist NIET werken
    (die is zelf instabiel/onbetrouwbaar vlak bij zwart, zie de toelichting
    bij _colored_mask verderop).

    Belangrijk: dit is NIET symmetrisch. Een kleurloze REFERENTIE (bv. een
    wit vlak) maakt een gekleurde pixel niet automatisch "passend" - dat was
    een eerdere fout hierin: een arceringslijn met een eigen kleur op een wit
    vlak "botste" dan technisch nergens mee (wit heeft immers geen kleur om
    tegen te botsen) en bleef daardoor ten onrechte beschermd. Heeft de pixel
    zelf wel kleur maar de referentie niet, dan wijst de cosinus-gelijkenis
    hieronder dat vanzelf af (het scalair product wordt 0)."""
    px_chroma = rgb - rgb.min(axis=2, keepdims=True)
    ref_chroma = reference_rgb - reference_rgb.min(axis=2, keepdims=True)
    px_norm = np.linalg.norm(px_chroma, axis=2)
    ref_norm = np.linalg.norm(ref_chroma, axis=2)

    pixel_is_neutral = px_norm < neutral_floor

    dot = (px_chroma * ref_chroma).sum(axis=2)
    denom = np.where(px_norm * ref_norm > 1e-6, px_norm * ref_norm, 1.0)
    cos_sim = dot / denom

    return pixel_is_neutral | (cos_sim > 0.7)


def _colored_mask(
    rgb: np.ndarray,
    sat_threshold: float,
    local_window: int = 7,
    local_delta: float = 0.1,
    downsample: int = 4,
    fringe_dilate_px: int = 1,
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
    zwarte vegen langs die hulplijnen tot gevolg.

    Alleen "donkerder dan de omgeving" bleek op zijn beurt ook niet genoeg,
    gevonden bij een heel ander soort bestand: een plattegrond met
    classificatiezones aangeduid via ARCERING (streeppatronen) i.p.v. vlakke
    kleur. Zo'n arceringslijn kan, afhankelijk van de kleur inkt, in zijn
    dunne kern zelf ook bijna zwart renderen (bv. blauwe arcering) - en werd
    daardoor ten onrechte als "een lijn die beschermd moet blijven" gezien,
    net als een deur. Het onderscheid: een deurlijn over een kleurvlak neemt
    de kleur van DAT vlak over (dezelfde tint als zijn omgeving); een
    arceringslijn heeft juist een EIGEN kleur die niet bij zijn omgeving
    (meestal wit) hoort. Daarom telt een donkere pixel alleen nog als
    "beschermde lijn" als zijn kleurzweem overeenkomt met die van zijn
    lokale omgeving (zie _hue_matches) - wijkt de kleur af, dan is het
    vermoedelijk zelf een classificatiekleur en mag hij alsnog weg.

    Een mediaanfilter op volle resolutie is op een groot ingescand blad
    (tientallen miljoenen pixels) te traag (tientallen seconden). De lokale
    vlakkleur verandert echter alleen op kamerschaal, niet van pixel tot
    pixel - de mediaan hoeft dus niet op elke pixel apart berekend te worden.
    Eerst uitdunnen (elke `downsample`-ste pixel), daar het venster op
    toepassen, en weer terug opschalen is >100x sneller en geeft vrijwel
    dezelfde uitkomst.

    Het venster moet ook groot genoeg zijn t.o.v. de arceringsdichtheid: bij
    een fijn KRUIS-arceringspatroon (twee sets diagonale lijnen) is er op de
    kruispunten lokaal duidelijk meer inkt dan waar de lijnen elkaar niet
    raken. Een te klein venster (5, uitgedund op elke 3e pixel) ving op die
    kruispunten zelf ook te veel van die extra inkt mee, waardoor de
    "lokale vlakkleur" ter plekke zelf licht kleurig werd geschat i.p.v.
    zuiver wit - en de kruispunt-pixel zo alsnog ten onrechte als
    "beschermde lijn" telde (zichtbaar als een regelmatig grid van kleine
    gekleurde kruisjes in het resultaat, op een echt testbestand met een
    dicht kruisarcering-patroon). Empirisch geverifieerd: een groter venster
    (7, uitgedund op elke 4e pixel) verdunt de kruispunt-inkt voldoende
    binnen het venster om weer een zuiver witte schatting te geven (kleur-
    residu op dat testbestand van 2.8% naar 0.3% van de pixels, wat overeen-
    kwam met gewone anti-aliasing-ruis) - en heeft, apart geverifieerd tegen
    dezelfde deur-over-kleurvlak-testgevallen als hierboven, géén meetbaar
    effect op die eerdere fix (pixel-identieke uitkomst).

    Zelfs met dat grotere venster bleek er nog een LAATSTE restje over: de
    verzadiging-drempel (`sat_threshold`) pakt alleen de sterk verzadigde
    KERN van een arceringslijn - het vage anti-aliasing-randje eromheen
    (bv. RGB 251,245,251, nauwelijks roze) haalt die drempel niet en blijft
    dus gewoon in het beeld staan. Dat lijkt onschuldig (het is bijna wit),
    maar de laatste stap in clean_via_raster maakt ELK niet-zuiver-wit pixel
    volledig ondoorzichtig zwart (nodig om dunne muurlijnen niet te laten
    verbleken, zie de toelichting daar) - en promoveert zo'n vaag randje
    alsnog tot volledig zwart. Het resultaat: een dunner "spookbeeld" van
    dezelfde arcering, nooit echt weg. Opgelost door het te-verwijderen
    gebied een paar pixels te laten "uitdijen" (dilateren), zodat dat vage
    randje ook meegepakt wordt. Cruciaal: die uitdijing mag NOOIT een als
    `is_line_like` beschermd pixel overschrijven - zonder die uitzondering
    bleek een simpele uitdijing een deurboog/tekst die tegen een gekleurd
    vlak aan ligt volledig weg te vagen (elke lijnpixel daar ligt namelijk
    al binnen een paar pixels van een net-verwijderd gekleurd pixel).
    Geverifieerd op zowel het arcering-bestand (spookbeeld praktisch weg)
    als de deur-over-kleurvlak-testgevallen (pixel-identiek aan zonder
    uitdijing).
    """
    local_median = _local_median_color(rgb, local_window, downsample)
    cmax = rgb.max(axis=2)
    local_median_cmax = local_median.max(axis=2)
    is_darker = (local_median_cmax - cmax) > local_delta
    is_line_like = is_darker & _hue_matches(rgb, local_median)
    colored = (_saturation(rgb) > sat_threshold) & ~is_line_like
    if fringe_dilate_px > 0:
        colored = ndimage.binary_dilation(colored, iterations=fringe_dilate_px) & ~is_line_like
    return colored


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
