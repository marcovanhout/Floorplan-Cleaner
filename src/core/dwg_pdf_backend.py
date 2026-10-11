"""Snelle ezdxf -> PDF-weergave met een PDF-laag (OCG) per CAD-laag en
onzichtbare echte tekst.

ezdxf's eigen PyMuPdfRenderBackend roept per lijntje Shape.finish() aan op
één gedeelde, steeds langer wordende string - kwadratisch, minuten werk voor
een grote tekening. Deze backend verzamelt PDF-pad-operatoren per
(laag, lijn/vlak, kleur, dikte) in lijsten en schrijft aan het eind één
content-stream weg.

Gebouwd op interne onderdelen van ezdxf 1.4.4 (vastgepind in requirements.txt).
"""

import copy
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pymupdf
from ezdxf.addons.drawing import layout
from ezdxf.addons.drawing import pymupdf as ezdxf_pymupdf
from ezdxf.addons.drawing.pipeline import prepare_string_for_rendering
from ezdxf.addons.drawing.properties import layer_key
from ezdxf.math import BoundingBox2d, Matrix44, Vec2, Vec3
from ezdxf.path import Command

# Verhouding hoofdletterhoogte / fontgrootte van Helvetica.
HELV_CAP_HEIGHT_RATIO = 0.718
MIN_TEXT_FONTSIZE_PT = 1.0


@dataclass
class CapturedText:
    text: str
    transform: Matrix44  # glyph-ruimte -> tekeningcoördinaten (WCS)
    cap_height: float  # in glyph-ruimte, vóór `transform`


def _f(v: float) -> str:
    return f"{v:.2f}"


def _path_ops(path, out: list[str], close: bool) -> None:
    start = path.start
    out.append(f"{_f(start.x)} {_f(start.y)} m")
    for cmd in path.commands():
        end = cmd.end
        if cmd.type == Command.MOVE_TO:
            if close:
                out.append("h")
            out.append(f"{_f(end.x)} {_f(end.y)} m")
        elif cmd.type == Command.LINE_TO:
            out.append(f"{_f(end.x)} {_f(end.y)} l")
        elif cmd.type == Command.CURVE3_TO:
            c = cmd.ctrl
            c1 = start + (c - start) * (2 / 3)
            c2 = end + (c - end) * (2 / 3)
            out.append(f"{_f(c1.x)} {_f(c1.y)} {_f(c2.x)} {_f(c2.y)} {_f(end.x)} {_f(end.y)} c")
        elif cmd.type == Command.CURVE4_TO:
            a, b = cmd.ctrl1, cmd.ctrl2
            out.append(f"{_f(a.x)} {_f(a.y)} {_f(b.x)} {_f(b.y)} {_f(end.x)} {_f(end.y)} c")
        start = end
    if close:
        out.append("h")


class FastRenderBackend(ezdxf_pymupdf.PyMuPdfRenderBackend):
    """Coördinaten komen binnen in PDF-punten met de oorsprong linksboven
    (zoals ezdxf's eigen backend ze krijgt)."""

    def __init__(self, page, settings, layer_names: dict[str, str]):
        super().__init__(page, settings)
        self.layer_names = layer_names  # layer_key -> originele naam
        self.groups: dict[tuple, list[str]] = defaultdict(list)

    def get_optional_content_group(self, layer_name: str) -> int:
        key = layer_key(layer_name)
        if key not in self._optional_content_groups:
            self._optional_content_groups[key] = self.doc.add_ocg(
                name=self.layer_names.get(key, layer_name), config=-1, on=True
            )
        return self._optional_content_groups[key]

    def _stroke(self, props) -> list[str]:
        rgb = self.resolve_color(props.color)
        width = round(self.resolve_stroke_width(props.lineweight), 2)
        return self.groups[(props.layer, "S", rgb, width)]

    def _fill(self, props) -> list[str]:
        return self.groups[(props.layer, "F", self.resolve_color(props.color), 0)]

    def set_background(self, color) -> None:
        pass  # transparant; de tool maakt de achtergrond zelf

    def draw_point(self, pos, properties) -> None:
        self._stroke(properties).append(f"{_f(pos.x)} {_f(pos.y)} m {_f(pos.x)} {_f(pos.y)} l")

    def draw_line(self, start, end, properties) -> None:
        self._stroke(properties).append(f"{_f(start.x)} {_f(start.y)} m {_f(end.x)} {_f(end.y)} l")

    def draw_solid_lines(self, lines, properties) -> None:
        out = self._stroke(properties)
        for s, e in lines:
            out.append(f"{_f(s.x)} {_f(s.y)} m {_f(e.x)} {_f(e.y)} l")

    def draw_path(self, path, properties) -> None:
        if len(path):
            _path_ops(path, self._stroke(properties), close=False)

    def draw_filled_paths(self, paths, properties) -> None:
        out = self._fill(properties)
        for p in paths:
            _path_ops(p, out, close=True)
        out.append("f*")

    def draw_filled_polygon(self, points, properties) -> None:
        v = points.to_list()
        if len(v) < 3:
            return
        out = self._fill(properties)
        out.append(f"{_f(v[0][0])} {_f(v[0][1])} m")
        out.extend(f"{_f(p[0])} {_f(p[1])} l" for p in v[1:])
        out.append("h f*")

    def draw_image(self, image_data, properties) -> None:
        pass  # rasterafbeeldingen in de tekening zijn niet nodig voor de lijnen

    def finalize(self) -> None:
        by_layer: dict[str, list[str]] = defaultdict(list)
        for (layer, kind, (r, g, b), width), ops in self.groups.items():
            if not ops:
                continue
            if kind == "S":
                chunk = f"q {r:.3f} {g:.3f} {b:.3f} RG {width} w 1 J 1 j\n" + "\n".join(ops) + "\nS\nQ"
            else:
                chunk = f"q {r:.3f} {g:.3f} {b:.3f} rg\n" + "\n".join(ops) + "\nQ"
            by_layer[layer].append(chunk)

        # Oorsprong linksboven -> PDF-ruimte (oorsprong linksonder).
        parts = [f"q 1 0 0 -1 0 {self.page_height_in_pt} cm"]
        props = []
        for i, (layer, chunks) in enumerate(by_layer.items()):
            name = f"L{i}"
            props.append(f"/{name} {self.get_optional_content_group(layer)} 0 R")
            parts.append(f"/OC /{name} BDC")
            parts.extend(chunks)
            parts.append("EMC")
        parts.append("Q")

        doc, page = self.doc, self.page
        kind, value = doc.xref_get_key(page.xref, "Resources")
        if kind == "xref":
            res_xref = int(value.split()[0])
        else:
            res_xref = doc.get_new_xref()
            doc.update_object(res_xref, value if kind == "dict" else "<<>>")
            doc.xref_set_key(page.xref, "Resources", f"{res_xref} 0 R")
        doc.xref_set_key(res_xref, "Properties", "<<" + " ".join(props) + ">>")

        stream_xref = doc.get_new_xref()
        doc.update_object(stream_xref, "<<>>")
        # Niet comprimeren: tijdelijk bestand, scheelt ~1 s op grote tekeningen.
        doc.update_stream(stream_xref, "\n".join(parts).encode("latin-1"), compress=False)
        doc.xref_set_key(page.xref, "Contents", f"{stream_xref} 0 R")


class FastPdfBackend(ezdxf_pymupdf.PyMuPdfBackend):
    """Recorder: eerst tekent de ezdxf-Frontend hierin, daarna levert
    `render_pdf()` het PDF-document op."""

    def __init__(self, layer_names: dict[str, str] | None = None) -> None:
        super().__init__()
        self.layer_names = layer_names or {}
        self.texts: list[CapturedText] = []

    def content_box(self, trim_ratio: float) -> tuple[BoundingBox2d | None, bool]:
        """Omtrek van wat écht getekend is, zonder losse verre uitschieters
        (een vergeten lijntje ver weg maakt de plattegrond anders piepklein).
        Alleen bijgesneden als het volledige gebied `trim_ratio` keer groter
        is. Retourneert (omtrek, bijgesneden)."""
        boxes = []
        for record in self.records:
            b = record.bbox()
            if b.has_data:
                boxes.append((b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y))
        if not boxes:
            return None, False
        arr = np.array(boxes)

        def box_of(a) -> BoundingBox2d:
            return BoundingBox2d([Vec2(a[:, 0].min(), a[:, 1].min()), Vec2(a[:, 2].max(), a[:, 3].max())])

        full = box_of(arr)
        cx, cy = (arr[:, 0] + arr[:, 2]) / 2, (arr[:, 1] + arr[:, 3]) / 2
        x_lo, x_hi = np.percentile(cx, [1, 99])
        y_lo, y_hi = np.percentile(cy, [1, 99])
        pad_x, pad_y = (x_hi - x_lo) * 0.1, (y_hi - y_lo) * 0.1
        inside = (cx >= x_lo - pad_x) & (cx <= x_hi + pad_x) & (cy >= y_lo - pad_y) & (cy <= y_hi + pad_y)
        if not inside.any():
            return full, False
        trimmed = box_of(arr[inside])
        if max(full.size.x, full.size.y) >= trim_ratio * max(trimmed.size.x, trimmed.size.y, 1e-9):
            return trimmed, True
        return full, False

    def capture_text(self, text: str, transform: Matrix44, cap_height: float, dxftype: str) -> None:
        text = prepare_string_for_rendering(text, dxftype).strip()
        if text:
            self.texts.append(CapturedText(text, transform, cap_height))

    def render_pdf(
        self,
        page: layout.Page,
        settings: layout.Settings,
        render_box: BoundingBox2d | None = None,
    ) -> tuple[bytes, int]:
        """Retourneert (pdf-bytes, aantal ingevoegde tekstregels). Kan maar
        één keer aangeroepen worden: de opname wordt ter plekke getransformeerd."""
        player = self.player()
        if render_box is None:
            render_box = player.bbox()
        output_layout = layout.Layout(render_box, flip_y=True)
        page = output_layout.get_final_page(page, settings)
        settings = copy.copy(settings)
        settings.output_coordinate_space = ezdxf_pymupdf.get_coordinate_output_space(page)
        m = output_layout.get_placement_matrix(page, settings=settings, top_origin=True)
        player.transform(m)

        backend = FastRenderBackend(page, settings, self.layer_names)
        player.replay(backend)
        n_texts = self._insert_invisible_texts(backend.page, m)
        return backend.doc.tobytes(garbage=1), n_texts

    def _insert_invisible_texts(self, page: pymupdf.Page, m: Matrix44) -> int:
        """Echte (onzichtbare, render_mode 3) tekst op de plek van de getekende
        tekst, zodat de bestaande ruimtenaam-herkenning (page.get_text) werkt.
        Bewust buiten alle PDF-lagen: ook vindbaar als die laag uit staat."""
        if not self.texts:
            return 0
        shape = page.new_shape()
        count = 0
        for t in self.texts:
            to_page = t.transform @ m
            origin = to_page.transform(Vec3(0, 0, 0))
            x_dir = to_page.transform_direction(Vec3(1, 0, 0))
            y_dir = to_page.transform_direction(Vec3(0, 1, 0))
            cap_pt = t.cap_height * y_dir.magnitude
            if cap_pt <= 0 or x_dir.magnitude == 0:
                continue
            fontsize = max(MIN_TEXT_FONTSIZE_PT, cap_pt / HELV_CAP_HEIGHT_RATIO)
            # Paginacoördinaten met y omlaag: positieve hoek = met de klok mee.
            angle = math.degrees(math.atan2(x_dir.y, x_dir.x))
            point = pymupdf.Point(origin.x, origin.y)
            shape.insert_text(
                point,
                t.text,
                fontsize=fontsize,
                fontname="helv",
                render_mode=3,
                morph=(point, pymupdf.Matrix(1, 1).prerotate(-angle)),
            )
            count += 1
        shape.commit()
        return count
