#!/usr/bin/env python3
"""
floorplan_cleaner.py
=====================
Maakt van een (AutoCAD-geexporteerde) PDF-plattegrond:
  1. een schone, vrijstaande PNG met alleen muren, deuren, ramen en
     trappen - zonder gekleurde vlakken en zonder tekst. Alle lijnen
     worden naar zuiver zwart genormaliseerd (geen paarse/gekleurde
     lijnrestjes meer).
  2. optioneel (--rooms): losse PNG's per ruimte, inclusief de deuren
     en ramen in de omringende muren, genoemd naar de ruimtenaam
     (indien herkend).

WERKWIJZE
---------
MODE A (voorkeur): als de PDF nog echte CAD-lagen (OCG's) heeft, wordt
precies bepaald welke lagen bij muren/deuren/ramen/trappen horen; alle
overige lagen (kleur, tekst, maatvoering, titelblok, legenda) gaan uit.
Ruimtenamen worden gehaald uit de PDF-tekstlaag (geen OCR nodig, dus
nauwkeurig) en gekoppeld aan elke ruimte via de dichtstbijzijnde
"ZHD-achtige" ruimtecode.

MODE B (fallback): geen bruikbare lagen (bv. platgeslagen/gescande
PDF) -> kleur wordt weggefilterd op verzadiging, tekst wordt gevonden
en verwijderd met OCR (tesseract). Ruimtes worden dan gedetecteerd via
beeldherkenning (vloeivulling/flood-fill) en genoemd via OCR-tekst in
de buurt. Dit is minder betrouwbaar dan MODE A.

GEBRUIK
-------
    python3 floorplan_cleaner.py input.pdf output.png
    python3 floorplan_cleaner.py input.pdf output.png --rooms
    python3 floorplan_cleaner.py input.pdf output.png --scale 4
    python3 floorplan_cleaner.py input.pdf output.png --force-raster
    python3 floorplan_cleaner.py input.pdf output.png --list-layers

VEREISTEN
---------
    pip install pymupdf pillow numpy matplotlib pytesseract scipy
    (en het systeempakket 'tesseract-ocr' voor OCR-tekstherkenning)

Hoofd-uitvoer is een transparante PNG (RGBA): zwarte lijnen op
transparante achtergrond. Met --rooms komt er ook een map
"<output>_ruimtes/" met een PNG per gedetecteerde ruimte.
"""

import argparse
import os
import re
import sys

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

# Standaard keywoorden voor lagen die BEHOUDEN moeten blijven.
DEFAULT_KEEP_KEYWORDS = [
    "A-WALL", "A-DOOR", "A-GLAZ", "S-STRS", "S-STAIR", "A-STAIR",
    "I-WALL",
    "MUUR", "DEUR", "RAAM", "TRAP", "GLAS", "KOZIJN",
]

DEFAULT_DROP_KEYWORDS = [
    "AREA", "ANNO", "GRID", "TOPO", "DETL", "RHK", "GRADE", "FILL & SIGN",
]

# Patronen die duiden op een "code" (geen bruikbare ruimtenaam):
# ZHD-achtige ruimtecodes, wandtype/deur/raam-codes, m²-waarden, cijfers.
CODE_PATTERNS = [
    r"^[A-Z]{2,4}[-.]",          # ZHD-1.234, generieke projectcode
    r"^[A-Z]{1,2}-[A-Za-z0-9.]+$",  # P-P2d, W-W25, PT-PT03, VL-V2i, P-Be
    r"m.$",                       # eindigt op "m2/m²" (oppervlakte)
    r"^\d",                       # begint met een cijfer (afmetingen)
]
ROOM_CODE_PATTERN = re.compile(r"[A-Z]{2,4}[-.][\d.]+")


def sanitize_filename(name):
    name = name.strip().lower()
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s/]+", "_", name)
    name = name.strip("_")
    return name or "ruimte"


def is_code_text(txt):
    t = txt.strip()
    if not t:
        return True
    return any(re.match(p, t) for p in CODE_PATTERNS)


# ----------------------------------------------------------------------
# Laag-detectie / laag-filtering (MODE A)
# ----------------------------------------------------------------------

def list_layers(doc):
    ocgs = doc.get_ocgs()
    if not ocgs:
        print("Geen OCG/CAD-lagen gevonden in deze PDF.")
        return
    print(f"{len(ocgs)} lagen gevonden:")
    for xref, info in sorted(ocgs.items(), key=lambda kv: kv[1]["name"]):
        print(f"  [{xref:>4}] {info['name']}")


def has_usable_layers(doc, keep_keywords):
    ocgs = doc.get_ocgs()
    if not ocgs:
        return False
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    if not ui_names:
        return False
    names = [info["name"] for info in ocgs.values()]
    return any(any(k.lower() in n.lower() for k in keep_keywords) for n in names)


def apply_layer_filter(doc, keep_keywords, drop_keywords):
    ocgs = doc.get_ocgs()
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    names = [info["name"] for info in ocgs.values()]
    kept, dropped = [], []
    for name in names:
        if name not in ui_names:
            continue
        matches_keep = any(k.lower() in name.lower() for k in keep_keywords)
        matches_drop = any(k.lower() in name.lower() for k in drop_keywords)
        keep = matches_keep and not matches_drop
        doc.set_layer_ui_config(name, action=0 if keep else 2)
        (kept if keep else dropped).append(name)
    print("Lagen AAN:", ", ".join(kept) if kept else "(geen)")
    print("Lagen UIT:", len(dropped), "lagen")


def render_page(page, scale, alpha=True):
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=alpha)
    mode = "RGBA" if pix.alpha else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return img.convert("RGBA")


def force_black_lines(img_rgba):
    """Normaliseer alle zichtbare pixels naar zuiver zwart, ongeacht
    brontint (bv. paarse/gekleurde CAD-laag-kleuren). Composite eerst
    op wit, gebruik de helderheid als alphakanaal."""
    arr = np.array(img_rgba).astype(np.float32) / 255.0
    rgb, a = arr[..., :3], arr[..., 3:4]
    flat = rgb * a + (1 - a)  # composite op wit
    gray = flat.mean(axis=2)
    alpha_out = ((1 - gray) * 255).astype(np.uint8)
    rgb_out = np.zeros((*gray.shape, 3), dtype=np.uint8)
    out = np.dstack([rgb_out, alpha_out])
    return Image.fromarray(out, "RGBA")


def clean_via_layers(doc, page, scale, keep_keywords, drop_keywords):
    apply_layer_filter(doc, keep_keywords, drop_keywords)
    img = render_page(page, scale, alpha=True)
    return force_black_lines(img)


# ----------------------------------------------------------------------
# Raster + OCR fallback (MODE B)
# ----------------------------------------------------------------------

def clean_via_raster(page, scale, sat_threshold=0.12, remove_text=True):
    import matplotlib.colors as mcolors

    img = render_page(page, scale, alpha=False)
    arr = np.array(img).astype(np.float32) / 255.0

    hsv = mcolors.rgb_to_hsv(arr)
    sat = hsv[..., 1]
    colored_mask = sat > sat_threshold
    work = arr.copy()
    work[colored_mask] = [1, 1, 1]

    ocr_boxes = []  # (x0,y0,x1,y1,text) in pixel coords, for room naming
    if remove_text:
        try:
            import pytesseract
            gray_for_ocr = (work.mean(axis=2) * 255).astype(np.uint8)
            ocr_img = Image.fromarray(gray_for_ocr)
            data = pytesseract.image_to_data(ocr_img, output_type=pytesseract.Output.DICT)
            n = len(data["text"])
            erased = 0
            for i in range(n):
                txt = data["text"][i].strip()
                conf = int(data["conf"][i]) if data["conf"][i] not in ("", "-1") else -1
                if txt and conf > 30:
                    x, y, w, h = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
                    ocr_boxes.append((x, y, x + w, y + h, txt))
                    pad = max(2, int(0.15 * h))
                    x0, y0 = max(0, x - pad), max(0, y - pad)
                    x1, y1 = min(work.shape[1], x + w + pad), min(work.shape[0], y + h + pad)
                    work[y0:y1, x0:x1] = [1, 1, 1]
                    erased += 1
            print(f"OCR: {erased} tekstblokken weggehaald.")
        except Exception as e:
            print(f"Waarschuwing: OCR-tekstverwijdering overgeslagen ({e}).")

    gray = work.mean(axis=2)
    L = (gray * 255).astype(np.uint8)
    alpha = 255 - L
    rgb_out = np.zeros((*L.shape, 3), dtype=np.uint8)
    out = np.dstack([rgb_out, alpha])
    return Image.fromarray(out, "RGBA"), ocr_boxes


# ----------------------------------------------------------------------
# Ruimtedetectie (flood-fill op de schone lijntekening)
# ----------------------------------------------------------------------

def detect_room_boxes(clean_img, dilate_iters=4, min_pixels=25000):
    """Vind ruimtes als omsloten witte gebieden in de schone
    lijntekening. Retourneert lijst van (x0,y0,x1,y1) pixel-bboxen."""
    from scipy import ndimage

    arr = np.array(clean_img)
    wall_mask = arr[..., 3] > 80
    struct = ndimage.generate_binary_structure(2, 2)
    dilated = ndimage.binary_dilation(wall_mask, structure=struct, iterations=dilate_iters)
    bg = ~dilated
    labels, num = ndimage.label(bg, structure=np.ones((3, 3)))
    if num == 0:
        return {}, labels
    sizes = ndimage.sum(bg, labels, range(1, num + 1))
    order = np.argsort(sizes)[::-1]
    exterior_label = int(order[0]) + 1  # grootste component = buitenwereld
    room_ids = [int(i) + 1 for i in order if sizes[i] > min_pixels and int(i) + 1 != exterior_label]

    objs = ndimage.find_objects(labels)
    boxes = {}
    for lid in room_ids:
        sl = objs[lid - 1]
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        boxes[lid] = (x0, y0, x1, y1)
    return boxes, labels


def extract_room_names_from_pdf(page, scale):
    """Haal ruimtecodes (ZHD-achtig) en kandidaat-namen uit de echte
    PDF-tekst (nauwkeuriger dan OCR). Retourneert lijst van
    (px, py, code) ankers en lijst van (px, py, tekst) naamkandidaten,
    in PIXELcoordinaten."""
    words = page.get_text("words")
    lines = {}
    for w in words:
        x0, y0, x1, y1, txt, b, l, wn = w
        lines.setdefault((b, l), []).append((x0, y0, x1, y1, txt))

    anchors, candidates = [], []
    for key, ws in lines.items():
        ws_sorted = sorted(ws, key=lambda w: w[0])
        full_text = " ".join(w[4] for w in ws_sorted)
        x0 = min(w[0] for w in ws_sorted); x1 = max(w[2] for w in ws_sorted)
        y0 = min(w[1] for w in ws_sorted); y1 = max(w[3] for w in ws_sorted)
        cx, cy = (x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale
        m = ROOM_CODE_PATTERN.search(full_text)
        if m:
            anchors.append((cx, cy, m.group(0)))
        elif not is_code_text(full_text) and len(full_text.strip()) > 2:
            candidates.append((cx, cy, full_text.strip()))
    return anchors, candidates


def match_names_to_rooms(room_boxes, labels, anchors, candidates, max_name_dist_px):
    """Koppel elke ruimte-bbox aan de dichtstbijzijnde ruimtenaam via
    ruimtecode-ankers (nearest-neighbor matching).

    Retourneert (room_names, anchor_log):
      room_names: {lid: naam-of-None} voor elke gedetecteerde ruimte
      anchor_log: lijst van dicts per ruimtecode uit de PDF-tekst, met
                  {"code", "name", "lid"} - gebruikt om achteraf te
                  rapporteren welke benoemde ruimtes GEEN eigen PNG
                  kregen en waarom.
    """
    room_names = {lid: None for lid in room_boxes}
    anchor_log = []
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
    is_room_pixel = np.isin(labels, list(room_id_set)) if room_id_set else np.zeros_like(labels, dtype=bool)
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

    for (ax, ay, code) in anchors:
        name = None
        if tree is not None:
            dist, idx = tree.query([ax, ay])
            if dist <= max_name_dist_px:
                name = candidates[idx][2]
        lid, direct_hit = point_to_room(ax, ay)
        anchor_log.append({"code": code, "name": name, "lid": lid, "direct_hit": direct_hit})
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

    for entry in anchor_log:
        entry["suppressed"] = entry["lid"] in suppressed_lids
    return room_names, anchor_log


def match_names_to_rooms_ocr(room_boxes, ocr_boxes, max_dist_px):
    """MODE B best-effort: koppel OCR-tekst aan ruimtes op basis van
    de dichtstbijzijnde ruimte-bbox (geen aparte laag-info beschikbaar,
    dus minder betrouwbaar dan de PDF-tekst-methode)."""
    room_names = {lid: None for lid in room_boxes}
    if not ocr_boxes:
        return room_names
    for lid, (x0, y0, x1, y1) in room_boxes.items():
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best_txt, bestd = None, float("inf")
        for (bx0, by0, bx1, by1, txt) in ocr_boxes:
            tcx, tcy = (bx0 + bx1) / 2, (by0 + by1) / 2
            if not (x0 - max_dist_px <= tcx <= x1 + max_dist_px and
                    y0 - max_dist_px <= tcy <= y1 + max_dist_px):
                continue
            d = (tcx - cx) ** 2 + (tcy - cy) ** 2
            if d < bestd and len(txt) > 2:
                best_txt, bestd = txt, d
        room_names[lid] = best_txt
    return room_names


def save_room_crops(clean_img, room_boxes, room_names, out_dir, margin_frac=0.35, min_margin_px=120):
    os.makedirs(out_dir, exist_ok=True)
    W, H = clean_img.size
    ordered = sorted(room_boxes.items(), key=lambda kv: (kv[1][1], kv[1][0]))

    # Tel hoe vaak elke (gesaneerde) naam voorkomt, zodat we ALLE
    # instanties van een dubbele naam nummeren (naam_1, naam_2, ...),
    # niet alleen de tweede en volgende.
    name_counts = {}
    bases = {}
    for lid, _ in ordered:
        name = room_names.get(lid)
        base = sanitize_filename(name) if name else None
        bases[lid] = base
        if base:
            name_counts[base] = name_counts.get(base, 0) + 1

    lid_to_filename = {}
    running = {}
    unnamed_counter = 0
    for lid, (x0, y0, x1, y1) in ordered:
        bw, bh = x1 - x0, y1 - y0
        mx = max(int(bw * margin_frac), min_margin_px)
        my = max(int(bh * margin_frac), min_margin_px)
        cx0, cy0 = max(0, x0 - mx), max(0, y0 - my)
        cx1, cy1 = min(W, x1 + mx), min(H, y1 + my)

        base = bases[lid]
        if base:
            running[base] = running.get(base, 0) + 1
            if name_counts[base] > 1:
                filename = f"{base}_{running[base]}.png"
            else:
                filename = f"{base}.png"
        else:
            unnamed_counter += 1
            filename = f"ruimte_{unnamed_counter:02d}.png"

        crop = clean_img.crop((cx0, cy0, cx1, cy1))
        path = os.path.join(out_dir, filename)
        crop.save(path)
        lid_to_filename[lid] = filename
    return lid_to_filename


def write_room_log(log_path, pdf_path, room_boxes, room_names, lid_to_filename,
                    anchor_log, mode_a):
    lines = []
    lines.append(f"Ruimte-log voor: {pdf_path}")
    lines.append(f"Methode: {'MODE A (CAD-lagen)' if mode_a else 'MODE B (beeldherkenning, best effort)'}")
    lines.append(f"Aantal gedetecteerde ruimte-vlakken: {len(room_boxes)}")
    lines.append("")
    lines.append("=== Aangemaakte PNG's ===")
    ordered = sorted(room_boxes.items(), key=lambda kv: (kv[1][1], kv[1][0]))
    for lid, _ in ordered:
        fname = lid_to_filename.get(lid, "?")
        name = room_names.get(lid) or "(geen naam herkend - volgnummer gebruikt)"
        lines.append(f"  - {fname}  <-  {name}")

    if anchor_log:
        lines.append("")
        lines.append("=== Ruimtenamen uit de tekening ZONDER eigen PNG ===")
        any_missing = False
        reported_codes = set()
        for entry in anchor_log:
            code, name, lid = entry["code"], entry["name"], entry["lid"]
            if not name or code in reported_codes:
                continue
            final_name = room_names.get(lid) if lid is not None else None
            fname = lid_to_filename.get(lid) if lid is not None else None
            if lid is not None and final_name == name and fname:
                continue  # deze ruimte kreeg wel degelijk zijn eigen PNG
            reported_codes.add(code)
            any_missing = True
            if lid is None:
                reason = "kon niet aan een gedetecteerd ruimte-vlak gekoppeld worden"
            elif not entry.get("direct_hit"):
                guess_name = room_names.get(lid) or "(onbenoemd vlak)"
                reason = (f"geen eigen ruimte-vlak gedetecteerd op deze plek (waarschijnlijk "
                          f"te klein gefilterd, of niet volledig omsloten door muren) - "
                          f"dichtstbijzijnde herkende ruimte was '{guess_name}' "
                          f"({lid_to_filename.get(lid, '?')}), maar dit is een gok, geen "
                          f"bevestigde samenvoeging")
            elif entry.get("suppressed"):
                reason = ("samengevoegd met andere ruimte(s) tot 1 groot vlak zonder "
                          "duidelijke scheidingsmuur - geen automatische naam gebruikt "
                          f"(zie {lid_to_filename.get(lid, '?')})")
            elif final_name and final_name != name:
                reason = (f"samengevoegd met ruimte '{final_name}' - beide vallen "
                          f"binnen hetzelfde vlak ({lid_to_filename.get(lid, '?')})")
            else:
                reason = "onbekende reden"
            lines.append(f"  - {name} (code {code}): {reason}")
        if not any_missing:
            lines.append("  (geen - alle herkende ruimtenamen kregen een eigen PNG)")

    lines.append("")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return log_path


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pdf")
    ap.add_argument("output_png")
    ap.add_argument("--scale", type=float, default=4.0, help="renderresolutie-factor (default 4x)")
    ap.add_argument("--force-raster", action="store_true", help="sla laag-detectie over, gebruik altijd MODE B")
    ap.add_argument("--no-ocr", action="store_true", help="in MODE B geen OCR-tekstverwijdering doen")
    ap.add_argument("--list-layers", action="store_true", help="toon gevonden CAD-lagen en stop")
    ap.add_argument("--rooms", action="store_true", help="genereer ook losse PNG's per ruimte")
    ap.add_argument("--room-margin", type=float, default=0.35,
                     help="extra marge rond elke ruimte, als fractie van de ruimte-afmeting (default 0.35)")
    ap.add_argument("--keep-keywords", type=str, default=",".join(DEFAULT_KEEP_KEYWORDS),
                     help="komma-gescheiden keywoorden voor te behouden lagen")
    ap.add_argument("--drop-keywords", type=str, default=",".join(DEFAULT_DROP_KEYWORDS),
                     help="komma-gescheiden keywoorden die altijd uit moeten")
    ap.add_argument("--page", type=int, default=0, help="paginanummer (0-based), default 0")
    args = ap.parse_args()

    doc = fitz.open(args.input_pdf)
    page = doc[args.page]

    if args.list_layers:
        list_layers(doc)
        return

    keep_keywords = [k for k in args.keep_keywords.split(",") if k]
    drop_keywords = [k for k in args.drop_keywords.split(",") if k]

    mode_a = not args.force_raster and has_usable_layers(doc, keep_keywords)
    ocr_boxes = []
    if mode_a:
        print("-> Bruikbare CAD-lagen gevonden: MODE A (laag-filtering).")
        img = clean_via_layers(doc, page, args.scale, keep_keywords, drop_keywords)
    else:
        print("-> Geen bruikbare CAD-lagen: MODE B (kleur+OCR fallback).")
        img, ocr_boxes = clean_via_raster(page, args.scale, remove_text=not args.no_ocr)

    img.save(args.output_png)
    print(f"Opgeslagen: {args.output_png} ({img.width}x{img.height}px)")

    if args.rooms:
        try:
            print("\nRuimtes detecteren...")
            room_boxes, labels = detect_room_boxes(img, dilate_iters=4 if mode_a else 6)
            print(f"{len(room_boxes)} ruimte(s) gevonden.")

            anchor_log = []
            if mode_a:
                anchors, candidates = extract_room_names_from_pdf(page, args.scale)
                room_names, anchor_log = match_names_to_rooms(room_boxes, labels, anchors, candidates,
                                                                max_name_dist_px=80 * args.scale)
            else:
                room_names = match_names_to_rooms_ocr(room_boxes, ocr_boxes, max_dist_px=60 * args.scale)

            n_named = sum(1 for v in room_names.values() if v)
            print(f"{n_named}/{len(room_boxes)} ruimte(s) automatisch benoemd; "
                  f"de rest krijgt een volgnummer (ruimte_NN).")
            if not mode_a and room_boxes:
                print("Let op: ruimte-detectie zonder CAD-lagen is een beste-poging "
                      "(beeldherkenning) en minder betrouwbaar dan met CAD-lagen.")

            out_dir = os.path.splitext(args.output_png)[0] + "_ruimtes"
            lid_to_filename = save_room_crops(img, room_boxes, room_names, out_dir, margin_frac=args.room_margin)
            print(f"{len(lid_to_filename)} losse ruimte-PNG's opgeslagen in: {out_dir}")

            log_path = os.path.join(out_dir, "_log.txt")
            write_room_log(log_path, args.input_pdf, room_boxes, room_names,
                            lid_to_filename, anchor_log, mode_a)
            print(f"Log opgeslagen: {log_path}")
        except ModuleNotFoundError as e:
            print(f"\nWAARSCHUWING: losse ruimte-PNG's overgeslagen - ontbrekend "
                  f"Python-pakket ({e.name}).")
            print(f"Installeer het met: pip install {e.name}")
            print("De hoofdplattegrond hierboven is wel gewoon goed opgeslagen.")
        except Exception as e:
            print(f"\nWAARSCHUWING: losse ruimte-PNG's overgeslagen door een "
                  f"onverwachte fout: {e}")
            print("De hoofdplattegrond hierboven is wel gewoon goed opgeslagen.")


if __name__ == "__main__":
    main()
