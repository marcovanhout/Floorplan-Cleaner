#!/usr/bin/env python3
"""
floorplan_cleaner CLI
======================
Command-line interface bovenop src/core - behoudt het v1-gedrag van
Plattegrond_Schoonmaker_v1/floorplan_cleaner.py, maar roept nu de geport
en herbruikbare core-module aan i.p.v. zelf de verwerking te doen.

GEBRUIK
-------
    python -m src.cli input.pdf output.png
    python -m src.cli input.pdf output.png --rooms
    python -m src.cli input.pdf output.png --scale 4
    python -m src.cli input.pdf output.png --force-raster
    python -m src.cli input.pdf output.png --list-layers
"""

import argparse
import os

import fitz  # PyMuPDF

from .core.constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from .core.layers import list_layers
from .core.pipeline import export_rooms, run_clean, run_room_detection


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pdf")
    ap.add_argument("output_png")
    ap.add_argument("--scale", type=float, default=4.0, help="renderresolutie-factor (default 4x)")
    ap.add_argument("--force-raster", action="store_true", help="sla laag-detectie over, gebruik altijd MODE B")
    ap.add_argument("--no-ocr", action="store_true", help="in MODE B geen OCR-tekstverwijdering doen")
    ap.add_argument("--list-layers", action="store_true", help="toon gevonden CAD-lagen en stop")
    ap.add_argument("--rooms", action="store_true", help="genereer ook losse PNG's per ruimte")
    ap.add_argument(
        "--room-margin",
        type=float,
        default=0.35,
        help="extra marge rond elke ruimte, als fractie van de ruimte-afmeting (default 0.35)",
    )
    ap.add_argument(
        "--keep-keywords",
        type=str,
        default=",".join(DEFAULT_KEEP_KEYWORDS),
        help="komma-gescheiden keywoorden voor te behouden lagen",
    )
    ap.add_argument(
        "--drop-keywords",
        type=str,
        default=",".join(DEFAULT_DROP_KEYWORDS),
        help="komma-gescheiden keywoorden die altijd uit moeten",
    )
    ap.add_argument("--page", type=int, default=0, help="paginanummer (0-based), default 0")
    args = ap.parse_args()

    doc = fitz.open(args.input_pdf)
    page = doc[args.page]

    if args.list_layers:
        layers = list_layers(doc)
        if not layers:
            print("Geen OCG/CAD-lagen gevonden in deze PDF.")
        else:
            print(f"{len(layers)} lagen gevonden:")
            for layer in layers:
                print(f"  [{layer['xref']:>4}] {layer['name']}")
        return

    keep_keywords = [k for k in args.keep_keywords.split(",") if k]
    drop_keywords = [k for k in args.drop_keywords.split(",") if k]

    clean_result = run_clean(
        doc,
        page,
        scale=args.scale,
        force_raster=args.force_raster,
        keep_keywords=keep_keywords,
        drop_keywords=drop_keywords,
    )
    if clean_result.mode_a:
        print("-> Bruikbare CAD-lagen gevonden: MODE A (laag-filtering).")
    else:
        print("-> Geen bruikbare CAD-lagen: MODE B (kleur+OCR fallback).")

    clean_result.image.save(args.output_png)
    print(f"Opgeslagen: {args.output_png} ({clean_result.image.width}x{clean_result.image.height}px)")

    if args.rooms:
        try:
            print("\nRuimtes detecteren...")
            detection = run_room_detection(page, args.scale, clean_result)
            print(f"{len(detection.rooms)} ruimte(s) gevonden.")

            n_named = sum(1 for r in detection.rooms if r.name)
            print(
                f"{n_named}/{len(detection.rooms)} ruimte(s) automatisch benoemd; "
                f"de rest krijgt een volgnummer (ruimte_NN)."
            )
            if not clean_result.mode_a and detection.rooms:
                print(
                    "Let op: ruimte-detectie zonder CAD-lagen is een beste-poging "
                    "(beeldherkenning) en minder betrouwbaar dan met CAD-lagen."
                )

            out_dir = os.path.splitext(args.output_png)[0] + "_ruimtes"
            result = export_rooms(
                clean_result.image,
                detection.rooms,
                out_dir,
                args.input_pdf,
                detection.anchor_log,
                clean_result.mode_a,
                margin_frac=args.room_margin,
            )
            print(f"{len(result.filenames)} losse ruimte-PNG's opgeslagen in: {out_dir}")
            print(f"Log opgeslagen: {result.log_path}")
        except ModuleNotFoundError as e:
            print(
                f"\nWAARSCHUWING: losse ruimte-PNG's overgeslagen - ontbrekend "
                f"Python-pakket ({e.name})."
            )
            print(f"Installeer het met: pip install {e.name}")
            print("De hoofdplattegrond hierboven is wel gewoon goed opgeslagen.")
        except Exception as e:
            print(
                f"\nWAARSCHUWING: losse ruimte-PNG's overgeslagen door een "
                f"onverwachte fout: {e}"
            )
            print("De hoofdplattegrond hierboven is wel gewoon goed opgeslagen.")


if __name__ == "__main__":
    main()
