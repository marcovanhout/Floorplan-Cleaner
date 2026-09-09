"""Orchestratie van de core-stappen: opschonen -> ruimtes detecteren -> exporteren.

CLI (src/cli.py) en webapp (src/webapp/routes.py) roepen beide deze functies
aan; hier zit geen argparse- of Flask-specifieke code.
"""

from PIL import Image

from .constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from .export import save_room_crops, write_room_log
from .layers import apply_layer_filter, has_usable_layers
from .names import extract_room_names_from_pdf, match_names_to_rooms, match_names_to_rooms_ocr
from .raster import clean_via_raster
from .render import force_black_lines, render_page
from .rooms import detect_room_boxes
from .types import CleanResult, DetectionResult, ExportResult, RoomRecord


def run_clean(
    doc,
    page,
    scale: float = 4.0,
    force_raster: bool = False,
    keep_keywords: list[str] | None = None,
    drop_keywords: list[str] | None = None,
) -> CleanResult:
    keep_keywords = keep_keywords if keep_keywords is not None else DEFAULT_KEEP_KEYWORDS
    drop_keywords = drop_keywords if drop_keywords is not None else DEFAULT_DROP_KEYWORDS

    mode_a = not force_raster and has_usable_layers(doc, keep_keywords)
    if mode_a:
        kept, dropped = apply_layer_filter(doc, keep_keywords, drop_keywords)
        img = force_black_lines(render_page(page, scale, alpha=True))
        return CleanResult(image=img, mode_a=True, kept_layers=kept, dropped_layers=dropped)

    img, ocr_boxes = clean_via_raster(page, scale)
    return CleanResult(image=img, mode_a=False, ocr_boxes=ocr_boxes)


def boxes_to_room_records(
    room_boxes: dict[int, tuple[int, int, int, int]],
    room_names: dict[int, str | None],
) -> list[RoomRecord]:
    return [
        RoomRecord(id=f"room_{lid}", bbox=bbox, name=room_names.get(lid), source="auto")
        for lid, bbox in room_boxes.items()
    ]


def run_room_detection(
    page,
    scale: float,
    clean_result: CleanResult,
    dilate_iters: int | None = None,
    min_pixels: int = 25000,
) -> DetectionResult:
    if dilate_iters is None:
        dilate_iters = 4 if clean_result.mode_a else 6
    room_boxes, labels = detect_room_boxes(
        clean_result.image, dilate_iters=dilate_iters, min_pixels=min_pixels
    )

    if clean_result.mode_a:
        anchors, candidates = extract_room_names_from_pdf(page, scale)
        room_names, anchor_log = match_names_to_rooms(
            room_boxes, labels, anchors, candidates, max_name_dist_px=80 * scale
        )
    else:
        room_names = match_names_to_rooms_ocr(
            room_boxes, clean_result.ocr_boxes, max_dist_px=60 * scale
        )
        anchor_log = []

    # anchor_log.room_id komt uit names.py als de ruwe scipy-label-id
    # (string); breng dit op één lijn met de "room_<lid>"-conventie die
    # boxes_to_room_records hieronder gebruikt voor RoomRecord.id.
    for entry in anchor_log:
        if entry.room_id is not None:
            entry.room_id = f"room_{entry.room_id}"

    rooms = boxes_to_room_records(room_boxes, room_names)
    return DetectionResult(rooms=rooms, anchor_log=anchor_log, mode_a=clean_result.mode_a)


def rotate_clockwise(
    image: Image.Image, rooms: list[RoomRecord]
) -> tuple[Image.Image, list[RoomRecord]]:
    """Roteert de opgeschoonde plattegrond 90 graden met de klok mee, en
    rekent de ruimte-vakken (in dezelfde afbeeldingspixel-coordinaten) mee
    om zodat ze op hun plek blijven staan.

    Formule geverifieerd tegen Image.Transpose.ROTATE_270 (= 90 graden CW):
    een punt (x, y) in de oude afbeelding (hoogte H) komt op (H - y, x) in
    de nieuwe terecht, dus bbox (x0,y0,x1,y1) -> (H-y1, x0, H-y0, x1).
    """
    orig_height = image.height
    rotated_image = image.transpose(Image.Transpose.ROTATE_270)
    rotated_rooms = [
        RoomRecord(
            id=r.id,
            bbox=(orig_height - r.bbox[3], r.bbox[0], orig_height - r.bbox[1], r.bbox[2]),
            name=r.name,
            source=r.source,
        )
        for r in rooms
    ]
    return rotated_image, rotated_rooms


def export_rooms(
    clean_img,
    rooms: list[RoomRecord],
    out_dir: str,
    pdf_path: str,
    anchor_log: list,
    mode_a: bool,
    margin_frac: float = 0.35,
    min_margin_px: int = 120,
) -> ExportResult:
    id_to_filename = save_room_crops(
        clean_img, rooms, out_dir, margin_frac=margin_frac, min_margin_px=min_margin_px
    )
    import os

    log_path = os.path.join(out_dir, "_log.txt")
    write_room_log(log_path, pdf_path, rooms, id_to_filename, anchor_log, mode_a)
    return ExportResult(out_dir=out_dir, filenames=id_to_filename, log_path=log_path)
