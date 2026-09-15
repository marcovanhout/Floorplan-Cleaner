"""Export van losse ruimte-PNG's + leesbaar logbestand.

Werkt op RoomRecord-lijsten (zie types.py) i.p.v. de interne scipy-ndimage
label-ids, zodat dit ook werkt op een door de gebruiker gecorrigeerde
(samengevoegd/nieuw getekend/verwijderd) ruimtelijst uit de correctie-UI.
"""

import logging
import os

from PIL import Image

from .names import sanitize_filename
from .types import AnchorLogEntry, RoomRecord

logger = logging.getLogger(__name__)

# Basismarge (voor kanten ZONDER aangrenzende deur) - puur voor visuele
# ademruimte rond de muren zelf. Bewust klein: het vangen van een
# deurzwaai is de taak van de deur-detectie hieronder, niet van deze
# marge (die eerder als vaste, ruime waarde ook deuren moest vangen, en
# daardoor op elke kant - ook lege - even groot moest zijn: te ruim voor
# de meeste kanten, of alsnog te krap voor de grootste deurzwaai).
BASE_MARGIN_MIN_PT = 30.0

# Hoever een vak nog als "ertegenaan" telt (i.p.v. toevallig ergens
# anders in de tekening te staan), en hoeveel extra ruimte NA het
# deur-vakje zelf nog wordt meegenomen (voor het deurklink-/
# scharniersymbool net buiten de kern van de deurzwaai).
DOOR_TOUCH_TOLERANCE_PT = 15.0
DOOR_EXTRA_BUFFER_PT = 20.0


def _is_doorlike(bbox: tuple[int, int, int, int], door_area_threshold: float) -> bool:
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    return door_area_threshold > 0 and (w * h) < door_area_threshold


def _estimate_door_area_threshold(areas: list[float]) -> float:
    """Schat de scheidingsgrens tussen een "deur-achtig" klein vakje en een
    echte ruimte, VOOR DEZE tekening specifiek.

    Eerste poging was simpel: alles kleiner dan 35% van de MEDIAAN-
    vakgrootte. Bleek onbetrouwbaar op een tekening met veel deur-vakjes
    t.o.v. weinig echte ruimtes (bv. een lange gang met veel kleine
    kamers): dan bestaat al meer dan de helft van alle gevonden vakken uit
    deur-vakjes, en valt de mediaan zelf al middenin die groep i.p.v. bij
    de grens met de echte ruimtes (concreet gezien op W-WR-68-011: 44
    deur-vakjes tegenover 17 echte ruimtes).

    In plaats daarvan: zoek naar de grootste RELATIEVE sprong tussen
    opeenvolgende (gesorteerde) vakgroottes - in de praktijk zit er een
    duidelijke kloof tussen "deur-vakjes" (die onderling qua grootte
    weinig verschillen) en "echte ruimtes" (die ook onderling verschillen,
    maar als groep een stuk groter zijn) - op het geteste bestand bv. een
    sprong van >2,7x tussen het grootste deur-vakje en de kleinste echte
    ruimte, tegen hooguit een paar procent verschil binnen elke groep
    afzonderlijk. De zoekruimte is beperkt tot het 10e-90e percentiel van
    de gesorteerde lijst, zodat een toevallige uitschieter (bv. één
    extreem grote ruimte, of de buitenmuur-omtrek als geheel) niet per
    ongeluk als "de" grens wordt aangezien.
    """
    positive = sorted(a for a in areas if a > 0)
    n = len(positive)
    if n < 4:
        return 0.0  # te weinig data om betrouwbaar te clusteren
    lo = max(1, round(n * 0.1))
    hi = min(n - 1, round(n * 0.9))
    best_ratio, best_idx = 1.0, None
    for i in range(lo, hi):
        ratio = positive[i] / positive[i - 1]
        if ratio > best_ratio:
            best_ratio, best_idx = ratio, i
    if best_idx is None or best_ratio < 1.5:
        return 0.0  # geen duidelijke kloof gevonden - geen aanname doen
    return (positive[best_idx - 1] + positive[best_idx]) / 2


def save_room_crops(
    clean_img: Image.Image,
    rooms: list[RoomRecord],
    out_dir: str,
    scale: float = 1.0,
    margin_frac: float = 0.15,
) -> dict[str, str]:
    """Snijd elke ruimte uit clean_img met marge en sla op als PNG.

    De marge is per kant: kanten zonder aangrenzend deur-achtig vak
    krijgen alleen een kleine, vaste basismarge (BASE_MARGIN_MIN_PT); een
    kant met een aangrenzend klein vak (vrijwel altijd een deur, zie
    _is_doorlike) wordt specifiek op die kant uitgebreid tot voorbij dat
    vak. Zo blijft een lege kant strak, en krijgt een deur - ongeacht hoe
    ver die toevallig uitsteekt - altijd precies genoeg ruimte, in plaats
    van één vaste marge die voor de ene deur te krap en voor de andere
    kant te ruim is (empirisch bleek de benodigde marge tussen deuren op
    hetzelfde bestand al 2x te verschillen - zie git-historie).

    Retourneert {room.id: bestandsnaam}.
    """
    os.makedirs(out_dir, exist_ok=True)
    W, H = clean_img.size
    ordered = sorted(rooms, key=lambda r: (r.bbox[1], r.bbox[0]))

    base_min_margin_px = round(BASE_MARGIN_MIN_PT * scale)
    touch_tol_px = round(DOOR_TOUCH_TOLERANCE_PT * scale)
    door_buffer_px = round(DOOR_EXTRA_BUFFER_PT * scale)
    areas = [(r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]) for r in rooms]
    door_area_threshold = _estimate_door_area_threshold(areas)

    # Tel hoe vaak elke (gesaneerde) naam voorkomt, zodat we ALLE
    # instanties van een dubbele naam nummeren (naam_1, naam_2, ...),
    # niet alleen de tweede en volgende. Een nog-naamloos vak (bv. een
    # handmatig getekend vakje dat nooit hernoemd is - de meeste ruimtes
    # krijgen inmiddels al bij de detectie een naam, zie
    # pipeline.assign_placeholder_names) krijgt hier zijn "room_NN"-
    # terugvalnaam AL toegekend, in dezelfde stap als echte namen -
    # zo telt zo'n terugvalnaam gewoon mee in name_counts en krijgt een
    # eventuele botsing met een al bestaande "room_NN" dezelfde _1/_2-
    # suffix als elke andere dubbele naam, i.p.v. dat het ene bestand het
    # andere stilzwijgend overschrijft.
    name_counts: dict[str, int] = {}
    bases: dict[str, str] = {}
    unnamed_counter = 0
    for room in ordered:
        if room.name:
            base = sanitize_filename(room.name)
        else:
            unnamed_counter += 1
            base = f"room_{unnamed_counter:02d}"
        bases[room.id] = base
        name_counts[base] = name_counts.get(base, 0) + 1

    id_to_filename: dict[str, str] = {}
    running: dict[str, int] = {}
    for room in ordered:
        # Vak kan uit de correctie-UI komen (handmatig getekend/versleept) -
        # clip naar de afbeeldingsgrenzen en sla over als er dan niets
        # overblijft, i.p.v. te crashen op een ongeldige crop-rechthoek.
        x0, x1 = sorted(room.bbox[0:3:2])
        y0, y1 = sorted(room.bbox[1:4:2])
        x0, x1 = max(0, min(x0, W)), max(0, min(x1, W))
        y0, y1 = max(0, min(y0, H)), max(0, min(y1, H))
        if x1 - x0 < 1 or y1 - y0 < 1:
            logger.warning(
                "Skipped room %s during export: box falls outside the image.", room.id
            )
            continue

        bw, bh = x1 - x0, y1 - y0
        mx = max(int(bw * margin_frac), base_min_margin_px)
        my = max(int(bh * margin_frac), base_min_margin_px)
        cx0, cy0, cx1, cy1 = x0 - mx, y0 - my, x1 + mx, y1 + my

        # Kanten met een aangrenzend deur-achtig vak specifiek uitbreiden
        # tot voorbij dat vak (i.p.v. te vertrouwen op de vaste basismarge
        # hierboven, die daar niet voor bedoeld is).
        for other in rooms:
            if other.id == room.id or not _is_doorlike(other.bbox, door_area_threshold):
                continue
            ox0, oy0, ox1, oy1 = other.bbox
            touching = not (
                ox1 < x0 - touch_tol_px
                or ox0 > x1 + touch_tol_px
                or oy1 < y0 - touch_tol_px
                or oy0 > y1 + touch_tol_px
            )
            if touching:
                cx0 = min(cx0, ox0 - door_buffer_px)
                cy0 = min(cy0, oy0 - door_buffer_px)
                cx1 = max(cx1, ox1 + door_buffer_px)
                cy1 = max(cy1, oy1 + door_buffer_px)

        cx0, cy0 = max(0, cx0), max(0, cy0)
        cx1, cy1 = min(W, cx1), min(H, cy1)

        base = bases[room.id]
        running[base] = running.get(base, 0) + 1
        if name_counts[base] > 1:
            filename = f"{base}_{running[base]}.png"
        else:
            filename = f"{base}.png"

        crop = clean_img.crop((cx0, cy0, cx1, cy1))
        path = os.path.join(out_dir, filename)
        crop.save(path)
        id_to_filename[room.id] = filename
    return id_to_filename


def write_room_log(
    log_path: str,
    pdf_path: str,
    rooms: list[RoomRecord],
    id_to_filename: dict[str, str],
    anchor_log: list[AnchorLogEntry],
    mode_a: bool,
) -> str:
    """Schrijf _log.txt: welke PNG's zijn gemaakt, en welke in de tekening
    gevonden ruimtenamen GEEN eigen PNG kregen (met reden).

    anchor_log komt uit de ORIGINELE automatische detectie; rooms is de
    UITEINDELIJKE (evt. door de gebruiker in de correctie-UI aangepaste)
    ruimtelijst - het log weerspiegelt dus wat de gebruiker heeft
    goedgekeurd, niet alleen de automatische gok.
    """
    rooms_by_id = {r.id: r for r in rooms}
    lines = []
    lines.append(f"Room log for: {pdf_path}")
    lines.append(f"Method: {'CAD layers (precise)' if mode_a else 'Image recognition (best effort)'}")
    lines.append(f"Number of detected room areas: {len(rooms)}")
    lines.append("")
    lines.append("=== PNGs created ===")
    ordered = sorted(rooms, key=lambda r: (r.bbox[1], r.bbox[0]))
    for room in ordered:
        fname = id_to_filename.get(room.id, "?")
        name = room.name or "(no name recognized - sequence number used)"
        lines.append(f"  - {fname}  <-  {name}")

    if anchor_log:
        lines.append("")
        lines.append("=== Room names found in the drawing WITHOUT their own PNG ===")
        any_missing = False
        reported_codes = set()
        for entry in anchor_log:
            code, name, room_id = entry.code, entry.name, entry.room_id
            if not name or code in reported_codes:
                continue
            final_room = rooms_by_id.get(room_id) if room_id is not None else None
            final_name = final_room.name if final_room else None
            fname = id_to_filename.get(room_id) if room_id is not None else None
            if room_id is not None and final_name == name and fname:
                continue  # deze ruimte kreeg wel degelijk zijn eigen PNG
            reported_codes.add(code)
            any_missing = True
            if room_id is None:
                reason = "could not be linked to a detected room area"
            elif not entry.direct_hit:
                guess_name = final_name or "(unnamed area)"
                reason = (
                    f"no dedicated room area detected at this location (likely "
                    f"filtered out as too small, or not fully enclosed by walls) - "
                    f"the nearest recognized room was '{guess_name}' "
                    f"({id_to_filename.get(room_id, '?')}), but this is a guess, not a "
                    f"confirmed match"
                )
            elif entry.suppressed:
                reason = (
                    "merged with other room(s) into 1 large area with no clear "
                    "dividing wall - no automatic name used "
                    f"(see {id_to_filename.get(room_id, '?')})"
                )
            elif final_room is None:
                reason = "deleted or merged during manual correction"
            elif final_name and final_name != name:
                reason = (
                    f"merged with room '{final_name}' - both fall within the same "
                    f"area ({id_to_filename.get(room_id, '?')})"
                )
            else:
                reason = "unknown reason"
            lines.append(f"  - {name} (code {code}): {reason}")
        if not any_missing:
            lines.append("  (none - every recognized room name got its own PNG)")

    lines.append("")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return log_path
