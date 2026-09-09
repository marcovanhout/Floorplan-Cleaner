"""Tests voor de multi-rotatie-OCR in MODE B: ruimtenamen staan vaak
verticaal/gedraaid in een scheve plattegrond, en Tesseract herkent
standaard alleen horizontale tekst. clean_via_raster() draait de
afbeelding daarom 4x (0/90/180/270) langs OCR en herleidt gevonden
tekstvakken terug naar de ONgedraaide coordinaten (_unrotate_box)."""

import numpy as np
from PIL import Image, ImageDraw

from src.core.raster import _OCR_ROTATIONS, _unrotate_box


def _bbox_of_marker(img: Image.Image) -> tuple[int, int, int, int]:
    """Vindt de bounding box van een rood vlak in img (inclusief pixelranden,
    net als een OCR-'word'-box: left/top/width/height)."""
    arr = np.array(img)
    mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 50) & (arr[:, :, 2] < 50)
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def test_unrotate_box_matches_marker_position_for_every_rotation():
    orig_w, orig_h = 100, 60
    orig_bbox = (10, 5, 30, 15)  # dicht bij linksboven, breder dan hoog

    base = Image.new("RGB", (orig_w, orig_h), "white")
    ImageDraw.Draw(base).rectangle(orig_bbox, fill="red")

    for k, transpose in _OCR_ROTATIONS:
        rotated = base if transpose is None else base.transpose(transpose)
        rotated_bbox = _bbox_of_marker(rotated)

        recovered = _unrotate_box(rotated_bbox, k, orig_w, orig_h)

        # PIL's rechthoek-fill is inclusief de laatste pixelrij/-kolom,
        # dus tot 1px afwijking door afronding is verwacht.
        for got, want in zip(recovered, orig_bbox):
            assert abs(got - want) <= 1, (k, recovered, orig_bbox)


def test_unrotate_box_k0_is_identity():
    box = (12, 34, 56, 78)
    assert _unrotate_box(box, 0, 999, 888) == box
