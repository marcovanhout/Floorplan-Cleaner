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


def save_room_crops(
    clean_img: Image.Image,
    rooms: list[RoomRecord],
    out_dir: str,
    margin_frac: float = 0.35,
    min_margin_px: int = 120,
) -> dict[str, str]:
    """Snijd elke ruimte uit clean_img met marge en sla op als PNG.

    Retourneert {room.id: bestandsnaam}.
    """
    os.makedirs(out_dir, exist_ok=True)
    W, H = clean_img.size
    ordered = sorted(rooms, key=lambda r: (r.bbox[1], r.bbox[0]))

    # Tel hoe vaak elke (gesaneerde) naam voorkomt, zodat we ALLE
    # instanties van een dubbele naam nummeren (naam_1, naam_2, ...),
    # niet alleen de tweede en volgende.
    name_counts: dict[str, int] = {}
    bases: dict[str, str | None] = {}
    for room in ordered:
        base = sanitize_filename(room.name) if room.name else None
        bases[room.id] = base
        if base:
            name_counts[base] = name_counts.get(base, 0) + 1

    id_to_filename: dict[str, str] = {}
    running: dict[str, int] = {}
    unnamed_counter = 0
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
        mx = max(int(bw * margin_frac), min_margin_px)
        my = max(int(bh * margin_frac), min_margin_px)
        cx0, cy0 = max(0, x0 - mx), max(0, y0 - my)
        cx1, cy1 = min(W, x1 + mx), min(H, y1 + my)

        base = bases[room.id]
        if base:
            running[base] = running.get(base, 0) + 1
            if name_counts[base] > 1:
                filename = f"{base}_{running[base]}.png"
            else:
                filename = f"{base}.png"
        else:
            unnamed_counter += 1
            filename = f"room_{unnamed_counter:02d}.png"

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
