"""DWG->PDF-weergave, getest op ezdxf-documenten in het geheugen (geen
LibreDWG nodig)."""

import ezdxf
import numpy as np
import pymupdf
import pytest
from ezdxf.addons.drawing import Frontend
from ezdxf.xclip import XClip

from src.core import dwg
from src.core.layers import apply_explicit_layer_selection, list_layers


def _render(doc) -> tuple[pymupdf.Document, list[str]]:
    warnings: list[str] = []
    pdf_bytes, _ = dwg.render_doc_to_pdf(doc, warnings)
    return pymupdf.open(stream=pdf_bytes, filetype="pdf"), warnings


def _ink_bbox(pdf: pymupdf.Document, layer: str) -> pymupdf.Rect:
    apply_explicit_layer_selection(pdf, [layer])
    dpi = 72
    pix = pdf[0].get_pixmap(dpi=dpi)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[..., :3].min(axis=2)
    ys, xs = np.nonzero(arr < 200)
    assert len(xs), f"nothing drawn on layer {layer}"
    return pymupdf.Rect(xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)


def _new_doc():
    doc = ezdxf.new("R2018", units=4)
    doc.layers.add("FRAME")
    doc.modelspace().add_lwpolyline([(0, 0), (10000, 0), (10000, 8000), (0, 8000)], close=True,
                                    dxfattribs={"layer": "FRAME"})
    return doc


def test_pdf_layers_keep_original_names_and_toggle():
    doc = _new_doc()
    doc.layers.add("A-Wall")
    doc.modelspace().add_line((1000, 1000), (9000, 1000), dxfattribs={"layer": "A-Wall"})
    pdf, _ = _render(doc)

    assert {layer["name"] for layer in list_layers(pdf)} == {"FRAME", "A-Wall"}
    wall = _ink_bbox(pdf, "A-Wall")
    frame = _ink_bbox(pdf, "FRAME")
    assert wall.height < 5 and frame.height > 100  # alleen de gekozen laag wordt getekend


def _word_center(pdf, text):
    words = [w for w in pdf[0].get_text("words") if w[4] == text]
    assert words, f"{text!r} not found as real text"
    x0, y0, x1, y1 = words[0][:4]
    return (x0 + x1) / 2, (y0 + y1) / 2


@pytest.mark.parametrize("kind", ["text", "rotated", "mtext", "nested_attrib"])
def test_invisible_text_lies_on_drawn_text(kind):
    doc = _new_doc()
    doc.layers.add("T")
    msp = doc.modelspace()
    if kind == "text":
        msp.add_text("TL-1.01", height=250, dxfattribs={"layer": "T", "insert": (2000, 2000)})
        expected = "TL-1.01"
    elif kind == "rotated":
        msp.add_text("TL-2.02", height=250, rotation=90, dxfattribs={"layer": "T", "insert": (5000, 2000)})
        expected = "TL-2.02"
    elif kind == "mtext":
        msp.add_mtext("{\\fArial|b1;Kantoor}", dxfattribs={"layer": "T", "insert": (2000, 6000), "char_height": 250})
        expected = "Kantoor"
    else:
        inner = doc.blocks.new("INNER")
        inner.add_attdef("NAME", insert=(0, 0), height=250, dxfattribs={"layer": "T"})
        outer = doc.blocks.new("OUTER")
        outer.add_blockref("INNER", (500, 500)).add_auto_attribs({"NAME": "Berging"})
        msp.add_blockref("OUTER", (6000, 5000))
        expected = "Berging"

    pdf, _ = _render(doc)
    cx, cy = _word_center(pdf, expected)
    glyphs = _ink_bbox(pdf, "T")
    margin = max(glyphs.width, glyphs.height) * 0.25
    assert glyphs.x0 - margin <= cx <= glyphs.x1 + margin
    assert glyphs.y0 - margin <= cy <= glyphs.y1 + margin


def test_invisible_text_found_even_with_its_layer_switched_off():
    doc = _new_doc()
    doc.layers.add("NAMES")
    doc.modelspace().add_text("TL-1.01", height=250, dxfattribs={"layer": "NAMES", "insert": (2000, 2000)})
    pdf, _ = _render(doc)
    apply_explicit_layer_selection(pdf, ["FRAME"])
    assert "TL-1.01" in [w[4] for w in pdf[0].get_text("words")]


def test_aci7_lines_become_black_not_white():
    doc = _new_doc()
    doc.layers.add("A-WALL", color=7)
    doc.modelspace().add_line((1000, 4000), (9000, 4000), dxfattribs={"layer": "A-WALL"})
    pdf, _ = _render(doc)
    _ink_bbox(pdf, "A-WALL")  # faalt als de lijn wit (onzichtbaar) getekend is


def test_repair_fixes_empty_mline_linetype_and_render_succeeds():
    doc = _new_doc()
    style = doc.mline_styles.new("BROKEN")
    style.elements.append(0.5, 7, "CONTINUOUS")
    style.elements.append(-0.5, 7, "")
    doc.modelspace().add_mline([(1000, 1000), (5000, 1000)], dxfattribs={"style_name": "BROKEN"})

    assert dwg.repair_doc(doc) >= 1
    assert all(e.linetype for e in style.elements)
    _, warnings = _render(doc)
    assert not warnings


def test_repair_discards_unreadable_block_clipping(monkeypatch):
    doc = _new_doc()
    doc.blocks.new("B").add_line((0, 0), (1000, 1000))
    insert = doc.modelspace().add_blockref("B", (2000, 2000))
    XClip(insert).set_block_clipping_path([(0, 0), (500, 500)])

    def broken(_vertices):
        raise ValueError("clipping box not detectable")

    monkeypatch.setattr(dwg.clipping_portal, "find_best_clipping_shape", broken)
    assert dwg.repair_doc(doc) == 1
    assert not XClip(insert).has_clipping_path


def test_missing_xrefs_are_reported():
    doc = _new_doc()
    doc.add_xref_def(r"C:\projects\Kelder.dwg", "Kelder")
    assert dwg.missing_xrefs(doc) == ["Kelder.dwg"]


def test_far_away_stray_object_is_left_out_of_view():
    doc = _new_doc()
    msp = doc.modelspace()
    for i in range(100):  # een echte plattegrond: veel objecten bij elkaar
        msp.add_line((100 * i, 100), (100 * i, 7900), dxfattribs={"layer": "FRAME"})
    doc.layers.add("STRAY")
    msp.add_line((5_000_000, 5_000_000), (5_000_010, 5_000_000), dxfattribs={"layer": "STRAY"})
    pdf, warnings = _render(doc)
    assert any("far away" in w for w in warnings)
    frame = _ink_bbox(pdf, "FRAME")
    assert frame.width > pdf[0].rect.width * 0.5  # plattegrond niet piepklein


def test_one_undrawable_object_is_skipped_not_fatal(monkeypatch):
    doc = _new_doc()
    doc.modelspace().add_circle((5000, 4000), 500)
    original = Frontend._build_dispatch_table

    def with_broken_circle(self):
        table = original(self)

        def boom(entity, properties):
            raise RuntimeError("broken entity")

        table["CIRCLE"] = boom
        return table

    monkeypatch.setattr(Frontend, "_build_dispatch_table", with_broken_circle)
    pdf, warnings = _render(doc)
    assert any("1 object(s)" in w for w in warnings)
    _ink_bbox(pdf, "FRAME")


def test_page_size_follows_drawing_scale_within_a3_a0():
    from ezdxf.math import BoundingBox2d

    def page_mm(w_units, h_units, mm_per_unit=1.0):
        page = dwg.choose_page(BoundingBox2d([(0, 0), (w_units, h_units)]), mm_per_unit)
        return page.width, page.height

    w, h = page_mm(60_000, 40_000)  # 60 x 40 m gebouw in mm -> 600 x 400 mm op 1:100
    assert 600 < w < 700 and 400 < h < 500
    w, _ = page_mm(5_000, 3_000)  # klein -> minimaal A3-breedte
    assert w >= 420
    w, _ = page_mm(500, 300, mm_per_unit=1000.0)  # 500 x 300 m (eenheid m) -> max A0
    assert w <= 1189 * 1.2
