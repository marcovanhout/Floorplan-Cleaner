"""Pagina-rendering en normalisatie naar zuiver zwarte lijnen."""

import pymupdf as fitz
import numpy as np
from PIL import Image


def render_page(page, scale: float, alpha: bool = True) -> Image.Image:
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=alpha)
    mode = "RGBA" if pix.alpha else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return img.convert("RGBA") if alpha else img


def force_black_lines(img_rgba: Image.Image) -> Image.Image:
    """Normaliseer alle zichtbare pixels naar zuiver zwart, ongeacht
    brontint (bv. paarse/gekleurde CAD-laag-kleuren). Composite eerst
    op wit, gebruik de helderheid daarna als alphakanaal.

    Een rechtstreekse alpha = 1-helderheid gaf dunne/anti-aliased lijnen
    (heel gewoon bij dunne CAD-lijngewichten) een zwakke dekking: in de
    correctiestap - waar de afbeelding tegen een witte achtergrond getoond
    wordt - oogde dat nog acceptabel, maar in de geëxporteerde PNG (echte
    transparantie, bv. geopend in een beeldbewerkingsprogramma) waren
    lijnen daardoor nauwelijks zichtbaar. Elk zichtbaar (niet-wit) pixel
    wordt daarom volledig ondoorzichtig zwart, puur zwart/transparant i.p.v.
    een geleidelijke overgang - zelfde aanpak als MODE B (zie raster.py)."""
    arr = np.array(img_rgba).astype(np.float32) / 255.0
    rgb, a = arr[..., :3], arr[..., 3:4]
    flat = rgb * a + (1 - a)  # composite op wit
    gray = flat.mean(axis=2)
    L = (gray * 255).astype(np.uint8)
    alpha_out = np.where(L < 250, 255, 0).astype(np.uint8)
    rgb_out = np.zeros((*gray.shape, 3), dtype=np.uint8)
    out = np.dstack([rgb_out, alpha_out])
    return Image.fromarray(out, "RGBA")


def image_to_png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
