#!/usr/bin/env python3
"""
Route 1-spike: bevat de PDF al een exacte, onzichtbare ruimte-polygoon per
kamer (zoals CAD-software vaak genereert voor oppervlakteberekening)?

Losstaand, wegwerp-onderzoeksscript - NIET geimporteerd door /src, NIET
onderdeel van de pytest-suite. Handmatig te draaien tegen een lokale
(nooit gecommitte) test-PDF:

    python scripts/spikes/route1_area_layer_spike.py "Test PDF/Bijlage A2.pdf"

Zie PROJECT_SPEC.md sectie 4 (Route 1) en het implementatieplan voor de
volledige achtergrond. Diagnostische output (incl. eventuele
overlay-PNG's) gaat naar scripts/spikes/_out/, dat gitignored is - deze
is afgeleid van een echte klanttekening en mag nooit gecommit worden.
"""

import argparse
import os
import sys

import pymupdf as fitz
import numpy as np

CANDIDATE_KEYWORDS = ["AREA", "RUIMTE", "ROOM", "OPPERVLAK"]


def step1_list_ocgs(doc):
    print("\n=== Stap 1: OCG's + layer_ui_configs ===")
    ocgs = doc.get_ocgs()
    if not ocgs:
        print("Geen OCG's gevonden in deze PDF.")
        return []
    candidates = []
    for xref, info in sorted(ocgs.items(), key=lambda kv: kv[1]["name"]):
        name = info["name"]
        is_candidate = any(k.lower() in name.lower() for k in CANDIDATE_KEYWORDS)
        marker = " <-- kandidaat" if is_candidate else ""
        print(f"  [{xref:>4}] {name}  (on={info['on']}){marker}")
        if is_candidate:
            candidates.append((xref, name))

    print("\n  layer_ui_configs() (zichtbaarheid/vergrendeling zoals gebruiker ziet):")
    for u in doc.layer_ui_configs():
        marker = " <-- kandidaat" if any(k.lower() in u["text"].lower() for k in CANDIDATE_KEYWORDS) else ""
        print(f"    {u}{marker}")
    return candidates


def step2_isolated_render(doc, page, candidates, scale, out_dir):
    print("\n=== Stap 2: geisoleerde force-render per kandidaat-laag ===")
    if not candidates:
        print("Geen kandidaat-lagen gevonden, stap overgeslagen.")
        return
    ocgs = doc.get_ocgs()
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    all_names = [info["name"] for info in ocgs.values()]
    candidate_names = {name for _, name in candidates}

    for name in all_names:
        if name not in ui_names:
            continue
        doc.set_layer_ui_config(name, action=0 if name in candidate_names else 2)

    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=True)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    alpha = arr[..., 3] if pix.n == 4 else None
    rgb = arr[..., :3]

    print(f"  Pixmap: {pix.width}x{pix.height}, kanalen={pix.n}")
    if alpha is not None:
        nonzero_alpha = int((alpha > 0).sum())
        print(f"  Pixels met alpha > 0: {nonzero_alpha} ({100 * nonzero_alpha / alpha.size:.4f}%)")
    unique_colors = len(np.unique(rgb.reshape(-1, 3), axis=0))
    print(f"  Aantal unieke RGB-kleuren: {unique_colors}")
    print(
        "  (Een render met alpha>0-pixels maar 'onzichtbaar voor het oog' in een "
        "gewone viewer wijst op near-white-on-white of een fill met alpha=0 - "
        "numeriek wel aanwezig.)"
    )

    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "step2_isolated_render.png")
    Image.fromarray(arr, "RGBA" if pix.n == 4 else "RGB").save(out_path)
    print(f"  Opgeslagen: {out_path}")


def step3_drawings(page, candidates):
    print("\n=== Stap 3: page.get_drawings(), GEFILTERD op kandidaat-lagen ===")
    print(f"  PyMuPDF-versie: {getattr(fitz, 'pymupdf_version', getattr(fitz, 'VersionBind', '?'))}")

    drawings = page.get_drawings()
    print(f"  {len(drawings)} drawing-objecten in totaal op de pagina (alle lagen).")
    if drawings:
        sample = drawings[0]
        print(f"  Sleutels van een voorbeeld-object: {sorted(sample.keys())}")

    candidate_names = {name for _, name in candidates}
    per_layer = {}
    for d in drawings:
        layer = d.get("layer")
        if layer in candidate_names:
            per_layer.setdefault(layer, []).append(d)

    invisible_candidates = []
    for layer, items in per_layer.items():
        print(f"\n  Laag '{layer}': {len(items)} drawing-object(en).")
        rects = [d.get("rect") for d in items if d.get("rect")]
        if rects:
            by_area = sorted(rects, key=lambda r: r.width * r.height)
            print(f"    Kleinste rect: {by_area[0]}  Grootste rect: {by_area[-1]}")
        n_multi_item = sum(1 for d in items if len(d.get("items", [])) >= 3)
        n_re = sum(1 for d in items if any(it[0] == "re" for it in d.get("items", [])))
        print(f"    Objecten met >=3 pad-items: {n_multi_item}, met een 're' (rechthoek)-item: {n_re}")
        for d in items:
            fill = d.get("fill")
            fill_opacity = d.get("fill_opacity", 1)
            path_items = [it for it in d.get("items", []) if it and it[0] in ("re", "l", "c")]
            looks_like_polygon = len(path_items) >= 3 or any(it[0] == "re" for it in path_items)
            if (fill is None or fill_opacity == 0) and looks_like_polygon:
                invisible_candidates.append(d)

    print(
        f"\n  Totaal: objecten op kandidaat-lagen die eruitzien als polygoon "
        f"ZONDER zichtbare fill/opacity: {len(invisible_candidates)}"
    )
    return invisible_candidates


def step4_content_stream(doc, page, candidates):
    print("\n=== Stap 4: raw content-stream (/OC ... BDC ... EMC), ONGEFILTERD op laag ===")
    print(
        "  Let op: dit telt ALLE /OC-getagde content op de pagina (elke laag "
        "gebruikt /OC-tags), niet specifiek de kandidaat-laag - puur "
        "informatief/sanity-check, stap 3 (hierboven, wel per-laag gefilterd) "
        "is het doorslaggevende signaal."
    )
    if not candidates:
        print("Geen kandidaat-lagen (uit stap 1), stap overgeslagen.")
        return
    candidate_xrefs = {xref for xref, _ in candidates}

    try:
        xref = page.xref
        content = doc.xref_stream(xref) if hasattr(doc, "xref_stream") else None
    except Exception as e:
        print(f"  Kon contentstream niet direct lezen ({e}), probeer page.read_contents().")
        content = None

    if content is None:
        try:
            content = page.read_contents()
        except Exception as e:
            print(f"  Kon geen contentstream lezen: {e}")
            return

    text = content.decode("latin-1", errors="replace")
    bdc_count = text.count("/OC")
    print(f"  '/OC' markering komt {bdc_count}x voor in de contentstream.")

    # Zoek BDC-blokken die verwijzen naar een kandidaat-OCG-xref via een
    # /OC /MCxx-achtige indirectie is normaal (via page /Resources /Properties);
    # we doen hier een ruwe, informatieve telling van pad-operators binnen
    # elk BDC..EMC blok dat een /OC-tag heeft, als indicatie van geometrie.
    import re

    blocks = re.findall(r"/OC\s*/\S+\s*BDC(.*?)EMC", text, flags=re.DOTALL)
    print(f"  {len(blocks)} BDC..EMC-blokken met een /OC-tag gevonden.")
    path_ops_total = 0
    for b in blocks:
        path_ops_total += len(re.findall(r"\b(m|l|re|c|h)\b", b))
    print(f"  Totaal aantal pad-operators (m/l/re/c/h) binnen die blokken: {path_ops_total}")
    if path_ops_total > 0:
        print(
            "  -> Er zit geometrie in /OC-getagde content op de pagina in het "
            "algemeen (verwacht - vrijwel alle CAD-content is OC-getagd). "
            "Zegt niets specifieks over de kandidaat-laag; zie stap 3."
        )


def step5_annotations(page):
    print("\n=== Stap 5: annotaties/widgets (fallback) ===")
    annots = list(page.annots()) if page.annots() else []
    widgets = list(page.widgets()) if page.widgets() else []
    print(f"  {len(annots)} annotatie(s), {len(widgets)} widget(s) op de pagina.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf_path")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()

    out_dir = os.path.join(os.path.dirname(__file__), "_out")

    doc = fitz.open(args.pdf_path)
    page = doc[args.page]

    candidates = step1_list_ocgs(doc)
    step2_isolated_render(doc, page, candidates, args.scale, out_dir)
    step3_drawings(page, candidates)
    step4_content_stream(doc, page, candidates)
    step5_annotations(page)

    print(
        "\n=== Samenvatting ===\n"
        "Beoordeel handmatig: bevat stap 3/4 concrete polygoongeometrie op de "
        "kandidaat-laag (Stap 1)? Zo ja -> Route 1 kansrijk, vervolgstap is "
        "polygons.py + detect_room_boxes_from_polygons() in src/core. Zo nee "
        "-> flood-fill (rooms.py) blijft de aanpak, Route 1 wordt gesloten."
    )


if __name__ == "__main__":
    main()
