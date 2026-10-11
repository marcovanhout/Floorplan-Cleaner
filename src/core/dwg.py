"""DWG -> PDF met lagen, via LibreDWG (dwg2dxf.exe) en ezdxf.

De rest van de tool werkt alleen met PDF's; deze module maakt van een DWG
een PDF met een PDF-laag per CAD-laag en onzichtbare echte tekst, zodat de
bestaande flow (lagenkiezer, MODE A, ruimtenamen) ongewijzigd werkt.
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf import recover, units
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
from ezdxf.addons.drawing.properties import layer_key
from ezdxf.math import BoundingBox2d
from ezdxf.tools import clipping_portal
from ezdxf.xclip import XClip

from .dwg_pdf_backend import FastPdfBackend

logger = logging.getLogger(__name__)

DWG2DXF_TIMEOUT_S = 180
# Ruime witrand: de ruimtedetectie (rooms.py) neemt het GROOTSTE witte vlak
# als "buitenwereld". Met een krappe rand kan een grote ruimte groter zijn
# dan die rand en wordt dan zelf als buiten gezien.
PAGE_MARGIN_FRACTION = 0.08
PAGE_MARGIN_MIN_MM = 10.0
# Paginaformaat: de tekening op ~1:100, begrensd tussen A3 en A0 - zoals echte
# plattegrond-PDF's, waar de ruimtedetectie (min_pixels, naam-afstand) op
# is afgesteld.
PAGE_SCALE_DENOMINATOR = 100.0
PAGE_LONG_SIDE_MIN_MM = 420.0
PAGE_LONG_SIDE_MAX_MM = 1189.0
# Losse, verre objecten (een vergeten lijntje kilometers verderop) maken de
# plattegrond anders piepklein. Alleen bijsnijden als het verschil groot is.
OUTLIER_TRIM_RATIO = 3.0

# Eerste 6 bytes van een DWG: versiecode. Ouder dan R13 leest LibreDWG
# niet betrouwbaar.
_DWG_TOO_OLD = {b"AC1.40", b"AC1.50", b"AC2.10", b"AC1001", b"AC1002", b"AC1003",
                b"AC1004", b"AC1006", b"AC1009"}


class DwgConversionError(Exception):
    """Fout met een melding die zo aan de gebruiker getoond kan worden."""


@dataclass
class DwgConversionResult:
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    text_count: int = 0
    layer_count: int = 0


def sniff_kind(data: bytes) -> str | None:
    """'pdf', 'dwg' of None, op basis van de inhoud (niet de extensie)."""
    if b"%PDF-" in data[:1024]:  # de PDF-standaard staat wat voorloopbytes toe
        return "pdf"
    if data[:4] == b"AC10" or data[:6] in _DWG_TOO_OLD:
        return "dwg"
    return None


def _candidate_paths() -> list[Path]:
    paths = []
    if getattr(sys, "frozen", False):
        paths.append(Path(sys._MEIPASS) / "libredwg" / "dwg2dxf.exe")
    paths.append(Path(__file__).resolve().parents[2] / "vendor" / "libredwg" / "dwg2dxf.exe")
    return paths


def find_dwg2dxf() -> Path | None:
    for p in _candidate_paths():
        if p.is_file():
            return p
    found = shutil.which("dwg2dxf")
    return Path(found) if found else None


def is_dwg_available() -> bool:
    return find_dwg2dxf() is not None


def dwg_to_dxf(dwg_path: Path, dxf_path: Path) -> None:
    exe = find_dwg2dxf()
    if exe is None:
        raise DwgConversionError("DWG support is not available in this installation.")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    dwg_path, dxf_path = dwg_path.resolve(), dxf_path.resolve()
    try:
        proc = subprocess.run(
            [str(exe), "-y", "-o", str(dxf_path), str(dwg_path)],
            cwd=dwg_path.parent,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=DWG2DXF_TIMEOUT_S,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        raise DwgConversionError(
            f"Reading the DWG took longer than {DWG2DXF_TIMEOUT_S} seconds and was stopped."
        ) from None
    stderr_tail = proc.stderr[-1000:].decode("utf-8", "replace")
    if proc.returncode != 0 or not dxf_path.is_file() or dxf_path.stat().st_size == 0:
        logger.warning("dwg2dxf failed (exit %s): %s", proc.returncode, stderr_tail)
        raise DwgConversionError(
            "This DWG file could not be read. It may be damaged or use an unsupported "
            "format; try exporting it to PDF instead."
        )
    logger.debug("dwg2dxf stderr (tail): %s", stderr_tail)


def load_dxf(dxf_path: Path, warnings: list[str]):
    try:
        return ezdxf.readfile(str(dxf_path))
    except ezdxf.DXFStructureError:
        logger.info("Plain DXF load failed, retrying in recover mode")
    try:
        doc, auditor = recover.readfile(str(dxf_path))
    except ezdxf.DXFStructureError as e:
        raise DwgConversionError("This DWG file could not be read (damaged structure).") from e
    warnings.append("The drawing had structural errors and was repaired while reading; check the result.")
    logger.info("Recovered DXF with %d fixes", len(auditor.fixes))
    return doc


def _all_inserts(doc):
    for block in doc.blocks:
        yield from block.query("INSERT")
    for lay in doc.layouts:
        yield from lay.query("INSERT")


def repair_doc(doc) -> int:
    """Herstel bekende eigenaardigheden in LibreDWG's DXF-uitvoer die ezdxf's
    tekenmodule laten crashen. Retourneert het aantal reparaties."""
    repairs = 0
    # Lege lijnstijl in MLINE-stijlen -> ezdxf weigert "".
    for _, style in doc.mline_styles:
        elements = list(style.elements)
        if any(not e.linetype for e in elements):
            style.elements.elements = [
                e if e.linetype else e._replace(linetype="BYLAYER") for e in elements
            ]
            repairs += 1
    # Onleesbare uitsnede (XCLIP) van een blok -> zonder uitsnede tekenen.
    seen = set()
    for insert in _all_inserts(doc):
        if id(insert) in seen:
            continue
        seen.add(id(insert))
        try:
            clip = XClip(insert)
            if not (clip.has_clipping_path and clip.is_clipping_enabled):
                continue
            path = clip.get_wcs_clipping_path()
            if not path.is_inverted_clip:
                clipping_portal.find_best_clipping_shape(path.vertices)
        except Exception:  # noqa: BLE001 - elke kapotte uitsnede: weghalen
            try:
                XClip(insert).discard_clipping_path()
                repairs += 1
            except Exception:  # noqa: BLE001
                logger.warning("Could not discard broken clipping on %s", insert)
    return repairs


def missing_xrefs(doc) -> list[str]:
    names = []
    for block in doc.blocks:
        if block.block_record.is_xref:
            path = block.block.dxf.get("xref_path", "") or block.name
            names.append(Path(path.replace("\\", "/")).name)
    return sorted(set(names))


def choose_layout(doc):
    msp = doc.modelspace()
    if len(msp):
        return msp
    for lay in doc.layouts:
        if lay.name != "Model" and len(lay):
            return lay
    raise DwgConversionError("This DWG file contains no drawing.")


def _mm_per_unit(doc) -> float:
    try:
        return units.conversion_factor(doc.header.get("$INSUNITS", 0), units.MM)
    except (TypeError, KeyError):
        return 1.0  # eenheidloos: in NL vrijwel altijd mm


def choose_page(box: BoundingBox2d | None, mm_per_unit: float) -> layout.Page:
    if box is None or not box.has_data:
        w_mm, h_mm = PAGE_LONG_SIDE_MIN_MM, PAGE_LONG_SIDE_MIN_MM * 297 / 420
    else:
        w_mm = max(box.size.x * mm_per_unit / PAGE_SCALE_DENOMINATOR, 1e-6)
        h_mm = max(box.size.y * mm_per_unit / PAGE_SCALE_DENOMINATOR, 1e-6)
        long_side = max(w_mm, h_mm)
        target = min(max(long_side, PAGE_LONG_SIDE_MIN_MM), PAGE_LONG_SIDE_MAX_MM)
        f = target / long_side
        w_mm, h_mm = w_mm * f, h_mm * f
    m = max(PAGE_MARGIN_MIN_MM, PAGE_MARGIN_FRACTION * max(w_mm, h_mm))
    return layout.Page(w_mm + 2 * m, h_mm + 2 * m, layout.Units.mm, margins=layout.Margins.all(m))


class SafeFrontend(Frontend):
    """Eén object dat niet getekend kan worden, breekt niet de hele
    omzetting af; het wordt overgeslagen en geteld."""

    failed = 0

    def draw_entity(self, entity, properties) -> None:
        try:
            super().draw_entity(entity, properties)
        except Exception:  # noqa: BLE001
            self.failed += 1
            logger.debug("Skipped entity %s", entity, exc_info=True)


def render_doc_to_pdf(doc, warnings: list[str]) -> tuple[bytes, int]:
    """Tekent een ezdxf-document als PDF. Retourneert (pdf-bytes, aantal tekstregels)."""
    lay = choose_layout(doc)
    layer_names = {layer_key(l.dxf.name): l.dxf.name for l in doc.layers}
    backend = FastPdfBackend(layer_names)
    # Witte achtergrond: AutoCAD-kleur 7 ("zwart/wit") wordt dan zwart i.p.v.
    # wit - anders verdwijnen o.a. muren in die kleur bij het zwart-maken.
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE)
    frontend = SafeFrontend(RenderContext(doc), backend, config=cfg)

    original_draw_text = frontend.pipeline.draw_text

    def draw_text(text, transform, properties, cap_height, dxftype="TEXT"):
        backend.capture_text(text, transform, cap_height, dxftype)
        original_draw_text(text, transform, properties, cap_height, dxftype)

    frontend.pipeline.draw_text = draw_text
    frontend.draw_layout(lay, finalize=True)
    if frontend.failed:
        warnings.append(f"{frontend.failed} object(s) in the drawing could not be drawn and were skipped.")

    box, trimmed = backend.content_box(OUTLIER_TRIM_RATIO)
    if box is None:
        raise DwgConversionError("This DWG file contains nothing that can be drawn.")
    if trimmed:
        warnings.append("Some objects far away from the floorplan were left out of view.")
    page = choose_page(box, _mm_per_unit(doc))
    return backend.render_pdf(page, layout.Settings(fit_page=True), render_box=box)


def convert_dwg_to_pdf(dwg_path: Path, pdf_path: Path) -> DwgConversionResult:
    """Zet een DWG om naar een PDF met lagen. Gooit DwgConversionError met
    een gebruikersvriendelijke melding als dat niet lukt."""
    result = DwgConversionResult()
    dxf_path = dwg_path.with_suffix(".dxf")

    t0 = time.perf_counter()
    dwg_to_dxf(dwg_path, dxf_path)
    result.timings["dwg_to_dxf"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    doc = load_dxf(dxf_path, result.warnings)
    result.timings["load"] = time.perf_counter() - t0

    if repair_doc(doc):
        logger.info("Applied repairs to the converted drawing")
    xrefs = missing_xrefs(doc)
    if xrefs:
        result.warnings.append(
            "This drawing refers to other drawing files that were not uploaded, so parts may "
            "be missing: " + ", ".join(xrefs)
        )

    t0 = time.perf_counter()
    try:
        pdf_bytes, result.text_count = render_doc_to_pdf(doc, result.warnings)
    except DwgConversionError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Rendering the converted DWG failed")
        raise DwgConversionError("This DWG file could not be converted.") from e
    result.timings["render"] = time.perf_counter() - t0

    pdf_path.write_bytes(pdf_bytes)
    dxf_path.unlink(missing_ok=True)
    result.layer_count = len(doc.layers)
    logger.info(
        "DWG converted in %.1fs (%s), %d text lines, warnings: %s",
        sum(result.timings.values()),
        ", ".join(f"{k} {v:.1f}s" for k, v in result.timings.items()),
        result.text_count,
        result.warnings or "none",
    )
    return result
