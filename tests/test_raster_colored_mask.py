"""Tests voor _colored_mask: welke pixels in MODE B als "vlakkleur" gezien
worden (en dus weggevlakt worden) versus als lijntekening blijven staan.

Ontstaan uit een echt gerapporteerd probleem: op een platte PDF met
gekleurde GMP-classificatievlakken (roze/groen) werden deurzwaai-lijnen die
over zo'n vlak heen getekend zijn, meegeveegd met de kleurverwijdering -
het slot van de PDF-renderer anti-aliast zo'n lijn tegen de kleur eronder,
waardoor de pixel numeriek "gekleurd" lijkt terwijl hij duidelijk donkerder
is dan het vlak. Zie ook: een dunne lijn kan per klantbestand/lijngewicht
heel verschillend "donker" zijn, dus een vaste helderheidsgrens werkt niet
betrouwbaar - vandaar de lokale-mediaan-aanpak die hier getest wordt."""

import numpy as np
from PIL import Image, ImageDraw

from src.core.raster import _colored_mask


def _flat_fill_with_line(fill_rgb: tuple[int, int, int], line_alpha: float) -> np.ndarray:
    """Een effen gekleurd vlak met een dunne, anti-aliased lijn erover (zoals
    een deurzwaai over een GMP-kleurvlak) - gerenderd op 4x resolutie en
    teruggeschaald, net als een PDF-renderer een dunne lijn anti-aliast."""
    scale = 4
    size = 120 * scale
    img = Image.new("RGB", (size, size), fill_rgb)
    draw = ImageDraw.Draw(img)
    # line_alpha simuleert een dunner/lichter lijngewicht: bij 1.0 zuiver
    # zwart, bij lagere waarden een mengkleur richting de vlakkleur (zoals
    # een dunne hairline-lijn na anti-aliasing er in het echt uitziet).
    line_rgb = tuple(int(c * (1 - line_alpha)) for c in fill_rgb)
    draw.line([(10 * scale, 10 * scale), (110 * scale, 110 * scale)], fill=line_rgb, width=2)
    img = img.resize((120, 120), Image.LANCZOS)
    return np.array(img).astype(np.float32) / 255.0


def test_flat_fill_without_any_line_is_fully_colored():
    fill = (178, 96, 138)  # roze, zoals in het geraporteerde bestand
    arr = np.tile(np.array(fill, dtype=np.float32) / 255.0, (80, 80, 1))
    mask = _colored_mask(arr, sat_threshold=0.12)
    assert mask.all(), "een egaal kleurvlak zonder enige lijn moet overal als 'kleur' gezien worden"


def test_strong_dark_line_over_colored_fill_is_preserved():
    """Een stevige, bijna-zwarte lijn (zoals de deur naar B102/A100 in het
    geraporteerde bestand) moet altijd als lijn behouden blijven."""
    arr = _flat_fill_with_line(fill_rgb=(178, 96, 138), line_alpha=0.95)
    mask = _colored_mask(arr, sat_threshold=0.12)
    not_colored = ~mask
    assert not_colored.sum() > 20, "de lijn moet als niet-gekleurd (lijn) herkend worden"


def test_faint_line_over_colored_fill_is_still_preserved():
    """Een veel zwakker/lichter aangezet lijntje (zoals de deurzwaai naar het
    groene vlak A101, die aanmerkelijk lichter renderde dan de deur naar het
    roze vlak) moet OOK bewaard blijven - dit was het scenario waarop de
    eerdere, vaste-drempel-aanpak faalde."""
    arr = _flat_fill_with_line(fill_rgb=(103, 211, 136), line_alpha=0.45)
    mask = _colored_mask(arr, sat_threshold=0.12)
    not_colored = ~mask
    assert not_colored.sum() > 20, "ook een zwak/licht lijntje moet als lijn herkend blijven"


def test_light_reference_line_does_not_leave_a_halo_in_the_fill():
    """Een BIJNA-WITTE hulplijn binnen een kleurvlak (zoals de dunne
    diagonale referentielijnen in het geraporteerde bestand) mag de
    omliggende vlakpixels niet per ongeluk als 'lijn' laten doorgaan - dat
    gaf eerder dikke zwarte vegen rond zulke hulplijnen in het eindresultaat."""
    fill = (103, 211, 136)
    scale = 4
    size = 120 * scale
    img = Image.new("RGB", (size, size), fill)
    draw = ImageDraw.Draw(img)
    light_rgb = tuple(min(255, int(c * 1.15) + 10) for c in fill)  # net iets lichter dan het vlak
    draw.line([(10 * scale, 10 * scale), (110 * scale, 110 * scale)], fill=light_rgb, width=2)
    img = img.resize((120, 120), Image.LANCZOS)
    arr = np.array(img).astype(np.float32) / 255.0

    mask = _colored_mask(arr, sat_threshold=0.12)
    # Pixels een paar rijen/kolommen van de hulplijn af horen nog gewoon
    # "vlak" (effen kleur) te zijn en dus als gekleurd behandeld te worden.
    fill_region = mask[20:40, 20:40]
    assert fill_region.all(), "vlakpixels naast een lichte hulplijn mogen niet als lijn behandeld worden"
