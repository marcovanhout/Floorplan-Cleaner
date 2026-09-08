"""Ruimtenaam-extractie (PDF-tekst en OCR) en koppeling aan gedetecteerde ruimtes."""

import os
import re

import numpy as np

from .constants import CODE_PATTERNS, ROOM_CODE_PATTERN
from .types import AnchorLogEntry


def sanitize_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s/]+", "_", name)
    name = name.strip("_")
    return name or "ruimte"


def is_code_text(txt: str) -> bool:
    t = txt.strip()
    if not t:
        return True
    return any(re.match(p, t) for p in CODE_PATTERNS)


def extract_room_names_from_pdf(page, scale: float):
    """Haal ruimtecodes (ZHD-achtig) en kandidaat-namen uit de echte
    PDF-tekst (nauwkeuriger dan OCR). Retourneert lijst van
    (px, py, code) ankers en lijst van (px, py, tekst) naamkandidaten,
    in PIXELcoordinaten."""
    words = page.get_text("words")
    lines: dict[tuple[int, int], list] = {}
    for w in words:
        x0, y0, x1, y1, txt, b, l, wn = w
        lines.setdefault((b, l), []).append((x0, y0, x1, y1, txt))

    anchors, candidates = [], []
    for key, ws in lines.items():
        ws_sorted = sorted(ws, key=lambda w: w[0])
        full_text = " ".join(w[4] for w in ws_sorted)
        x0 = min(w[0] for w in ws_sorted)
        x1 = max(w[2] for w in ws_sorted)
        y0 = min(w[1] for w in ws_sorted)
        y1 = max(w[3] for w in ws_sorted)
        cx, cy = (x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale
        m = ROOM_CODE_PATTERN.search(full_text)
        if m:
            anchors.append((cx, cy, m.group(0)))
        elif not is_code_text(full_text) and len(full_text.strip()) > 2:
            candidates.append((cx, cy, full_text.strip()))
    return anchors, candidates


def match_names_to_rooms(
    room_boxes: dict[int, tuple[int, int, int, int]],
    labels: np.ndarray,
    anchors: list,
    candidates: list,
    max_name_dist_px: float,
) -> tuple[dict[int, str | None], list[AnchorLogEntry]]:
    """Koppel elke ruimte-bbox aan de dichtstbijzijnde ruimtenaam via
    ruimtecode-ankers (nearest-neighbor matching).

    Retourneert (room_names, anchor_log):
      room_names: {lid: naam-of-None} voor elke gedetecteerde ruimte
      anchor_log: lijst van AnchorLogEntry per ruimtecode uit de PDF-tekst,
                  gebruikt om achteraf te rapporteren welke benoemde
                  ruimtes GEEN eigen PNG kregen en waarom.
    """
    room_names: dict[int, str | None] = {lid: None for lid in room_boxes}
    anchor_log: list[AnchorLogEntry] = []
    if not anchors:
        return room_names, anchor_log
    if candidates:
        from scipy.spatial import cKDTree

        cand_pts = np.array([(c[0], c[1]) for c in candidates])
        tree = cKDTree(cand_pts)
    else:
        tree = None

    h, w = labels.shape

    # Voorbereiding voor nauwkeurige "dichtstbijzijnde ruimte"-fallback:
    # voor elke muur/niet-ruimte-pixel bepalen we via een euclidische
    # afstandstransformatie de ECHTE dichtstbijzijnde ruimte-pixel
    # (i.p.v. de grove aanname "dichtstbijzijnde bbox-middelpunt").
    room_id_set = set(room_boxes.keys())
    is_room_pixel = np.isin(labels, list(room_id_set)) if room_id_set else np.zeros_like(
        labels, dtype=bool
    )
    nearest_idx = None
    if room_id_set and not is_room_pixel.all():
        from scipy.ndimage import distance_transform_edt

        _, nearest_idx = distance_transform_edt(~is_room_pixel, return_indices=True)

    def point_to_room(px, py):
        xi, yi = int(px), int(py)
        xi = min(max(xi, 0), w - 1)
        yi = min(max(yi, 0), h - 1)
        lid = int(labels[yi, xi])
        if lid in room_boxes:
            return lid, True
        if nearest_idx is not None:
            ny, nx = nearest_idx[0][yi, xi], nearest_idx[1][yi, xi]
            lid2 = int(labels[ny, nx])
            if lid2 in room_boxes:
                return lid2, False
        return None, False

    raw_entries = []
    for (ax, ay, code) in anchors:
        name = None
        if tree is not None:
            dist, idx = tree.query([ax, ay])
            if dist <= max_name_dist_px:
                name = candidates[idx][2]
        lid, direct_hit = point_to_room(ax, ay)
        raw_entries.append({"code": code, "name": name, "lid": lid, "direct_hit": direct_hit})
        if lid is not None and room_names.get(lid) is None and name:
            room_names[lid] = name

    # Veiligheidsmaatregel: een abnormaal grote ruimte (veel groter dan
    # de mediane ruimte) is vermoedelijk een samenvoeging van meerdere
    # fysieke ruimtes zonder scheidingsmuur/deur - een enkele naam
    # daarvoor zou misleidend zijn. Val dan terug op een volgnummer.
    areas = [((x1 - x0) * (y1 - y0)) for (x0, y0, x1, y1) in room_boxes.values()]
    suppressed_lids = set()
    if areas:
        median_area = sorted(areas)[len(areas) // 2]
        for lid, (x0, y0, x1, y1) in room_boxes.items():
            area = (x1 - x0) * (y1 - y0)
            if median_area > 0 and area > 6 * median_area:
                room_names[lid] = None
                suppressed_lids.add(lid)

    for entry in raw_entries:
        anchor_log.append(
            AnchorLogEntry(
                code=entry["code"],
                name=entry["name"],
                room_id=str(entry["lid"]) if entry["lid"] is not None else None,
                direct_hit=entry["direct_hit"],
                suppressed=entry["lid"] in suppressed_lids,
            )
        )
    return room_names, anchor_log


def match_names_to_rooms_ocr(
    room_boxes: dict[int, tuple[int, int, int, int]],
    ocr_boxes: list[tuple[int, int, int, int, str]],
    max_dist_px: float,
) -> dict[int, str | None]:
    """MODE B best-effort: koppel OCR-tekst aan ruimtes op basis van
    de dichtstbijzijnde ruimte-bbox (geen aparte laag-info beschikbaar,
    dus minder betrouwbaar dan de PDF-tekst-methode)."""
    room_names: dict[int, str | None] = {lid: None for lid in room_boxes}
    if not ocr_boxes:
        return room_names
    for lid, (x0, y0, x1, y1) in room_boxes.items():
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best_txt, bestd = None, float("inf")
        for (bx0, by0, bx1, by1, txt) in ocr_boxes:
            tcx, tcy = (bx0 + bx1) / 2, (by0 + by1) / 2
            if not (
                x0 - max_dist_px <= tcx <= x1 + max_dist_px
                and y0 - max_dist_px <= tcy <= y1 + max_dist_px
            ):
                continue
            d = (tcx - cx) ** 2 + (tcy - cy) ** 2
            if d < bestd and len(txt) > 2:
                best_txt, bestd = txt, d
        room_names[lid] = best_txt
    return room_names
