"""Orchestratie van de core-stappen: opschonen -> ruimtes detecteren -> exporteren.

CLI (src/cli.py) en webapp (src/webapp/routes.py) roepen beide deze functies
aan; hier zit geen argparse- of Flask-specifieke code.
"""

import math

from PIL import Image, ImageDraw

from .constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from .export import save_room_crops, write_room_log
from .layers import apply_explicit_layer_selection, apply_layer_filter, has_usable_layers, list_layers
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
    selected_layers: list[str] | None = None,
    remove_text: bool = True,
) -> CleanResult:
    """selected_layers: expliciete lijst laagnamen (bv. rechtstreeks uit de
    laag-kiezer in de webapp) - heeft voorrang op keep_keywords/drop_keywords
    en dwingt MODE A af zolang de PDF uberhaupt lagen heeft (geen keywoord-
    gok meer nodig of dit een 'bruikbare' laag-PDF is: de gebruiker heeft dat
    zelf al aangegeven door lagen aan te vinken). CLI-gebruik (geen laag-
    kiezer beschikbaar) laat dit op None en valt terug op de keywoorden."""
    keep_keywords = keep_keywords if keep_keywords is not None else DEFAULT_KEEP_KEYWORDS
    drop_keywords = drop_keywords if drop_keywords is not None else DEFAULT_DROP_KEYWORDS

    has_layers = bool(list_layers(doc))
    mode_a = not force_raster and has_layers and (
        selected_layers is not None or has_usable_layers(doc, keep_keywords)
    )
    if mode_a:
        if selected_layers is not None:
            kept, dropped = apply_explicit_layer_selection(doc, selected_layers)
        else:
            kept, dropped = apply_layer_filter(doc, keep_keywords, drop_keywords)
        img = force_black_lines(render_page(page, scale, alpha=True))
        return CleanResult(image=img, mode_a=True, kept_layers=kept, dropped_layers=dropped)

    img, ocr_boxes = clean_via_raster(page, scale, remove_text=remove_text)
    return CleanResult(image=img, mode_a=False, ocr_boxes=ocr_boxes)


def boxes_to_room_records(
    room_boxes: dict[int, tuple[int, int, int, int]],
    room_names: dict[int, str | None],
) -> list[RoomRecord]:
    return [
        RoomRecord(id=f"room_{lid}", bbox=bbox, name=room_names.get(lid), source="auto")
        for lid, bbox in room_boxes.items()
    ]


def assign_placeholder_names(rooms: list[RoomRecord]) -> None:
    """Geeft elke ruimte zonder herkende naam (geen ruimtecode-anker in de
    PDF-tekst gevonden, of geen OCR-tekst dichtbij genoeg) een eigen,
    oplopende naam "room_01", "room_02", enz. - in dezelfde volgorde
    (boven->onder, dan links->rechts) die save_room_crops() bij export ook
    gebruikt voor nog-naamloze vakken.

    Bewust GEEN "raad de naam uit de dichtstbijzijnde tekst"-terugval
    (zoals MODE B's OCR-matching al doet): bij een PDF met CAD-lagen staat
    er vaak net zoveel niet-naam-tekst (drukwaarden, ventilatievouden,
    GMP-classificaties, maatvoering) als echte ruimtenamen, en een verkeerd
    geraden naam is misleidender dan een neutraal volgnummer. Dit maakt
    "room_01" een ECHTE naam (geen speciaal geval meer) - zo komt de naam
    die de gebruiker in de correctiestap ziet vanaf het begin al overeen
    met de bestandsnaam die de export ervoor zal gebruiken, ook al wordt
    er verder niks aan de ruimte veranderd."""
    ordered = sorted(rooms, key=lambda r: (r.bbox[1], r.bbox[0]))
    counter = 0
    for room in ordered:
        if not room.name:
            counter += 1
            room.name = f"room_{counter:02d}"


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
    assign_placeholder_names(rooms)
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


def rotate_by_angle(
    image: Image.Image, rooms: list[RoomRecord], degrees: float
) -> tuple[Image.Image, list[RoomRecord]]:
    """Roteert de opgeschoonde plattegrond met een WILLEKEURIGE hoek (met de
    klok mee), voor de "vrije hoek"-optie naast de 90-graden-knop
    (rotate_clockwise hierboven, die exact/lossless blijft voor de gangbare
    90-graden-stappen).

    Ruimte-vakken blijven overal in de app eenvoudige RECHTE rechthoeken
    (correctiescherm, export-uitsnede) - bij een hoek die niet in de buurt
    van 0/90/180/270 graden ligt, wordt de rechte omtrek om een dan
    schuinstaande ruimte daardoor noodzakelijkerwijs RUIMER dan de ruimte
    zelf (de rechte bounding box van de 4 gedraaide hoekpunten). Bewuste
    keuze, akkoord bevonden: bij een kleine rechtzet-correctie (het meest
    voorkomende gebruik) is dit verwaarloosbaar; alleen bij een grote
    afwijking van een rechte hoek wordt de uitsnede merkbaar ruimer.

    Formule geverifieerd met een testrechthoek tegen PIL's
    Image.rotate(-degrees, expand=True) (PIL roteert tegen de klok in bij
    een positieve hoek, dus -degrees voor met de klok mee, consistent met
    de bestaande 90-knop): een punt (x,y) -> roteer rond het midden van de
    ORIGINELE afbeelding met -degrees, verschuif naar het midden van de
    NIEUWE (groter geworden) afbeelding.
    """
    orig_w, orig_h = image.size
    rotated_image = image.rotate(
        -degrees, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0)
    )
    new_w, new_h = rotated_image.size

    theta = math.radians(degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = orig_w / 2, orig_h / 2
    ncx, ncy = new_w / 2, new_h / 2

    def transform_point(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - cx, y - cy
        nx = dx * cos_t - dy * sin_t
        ny = dx * sin_t + dy * cos_t
        return nx + ncx, ny + ncy

    rotated_rooms = []
    for r in rooms:
        x0, y0, x1, y1 = r.bbox
        corners = [transform_point(x, y) for x, y in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        rotated_rooms.append(
            RoomRecord(
                id=r.id,
                bbox=(round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))),
                name=r.name,
                source=r.source,
            )
        )
    return rotated_image, rotated_rooms


def erase_rect(image: Image.Image, x0: int, y0: int, x1: int, y1: int) -> Image.Image:
    """Vlakt een door de gebruiker aangewezen rechthoek volledig transparant -
    voor het handmatig wegvegen van restjes die de automatische opschoning
    laat staan (bv. tekst die OCR miste). Los van de ruimte-vakken zelf, die
    veranderen hierdoor niet."""
    img = image.convert("RGBA")
    x0, x1 = sorted((max(0, min(x0, img.width)), max(0, min(x1, img.width))))
    y0, y1 = sorted((max(0, min(y0, img.height)), max(0, min(y1, img.height))))
    if x1 > x0 and y1 > y0:
        ImageDraw.Draw(img).rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0, 0))
    return img


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
