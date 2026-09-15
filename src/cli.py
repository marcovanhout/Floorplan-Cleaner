#!/usr/bin/env python3
"""
floorplan_cleaner CLI
======================
Command-line interface bovenop src/core - behoudt het v1-gedrag van
Plattegrond_Schoonmaker_v1/floorplan_cleaner.py, maar roept nu de geport
en herbruikbare core-module aan i.p.v. zelf de verwerking te doen.

USAGE
-----
    python -m src.cli input.pdf output.png
    python -m src.cli input.pdf output.png --rooms
    python -m src.cli input.pdf output.png --scale 4
    python -m src.cli input.pdf output.png --force-raster
    python -m src.cli input.pdf output.png --list-layers
"""

import argparse
import os

import pymupdf as fitz

from .core.constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from .core.layers import list_layers
from .core.pipeline import export_rooms, run_clean, run_room_detection


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pdf")
    ap.add_argument("output_png")
    ap.add_argument("--scale", type=float, default=4.0, help="render resolution factor (default 4x)")
    ap.add_argument("--force-raster", action="store_true", help="skip layer detection, always use image-based cleaning")
    ap.add_argument("--no-ocr", action="store_true", help="do not perform OCR text removal in image-based cleaning")
    ap.add_argument("--list-layers", action="store_true", help="show found CAD layers and stop")
    ap.add_argument("--rooms", action="store_true", help="also generate separate PNGs per room")
    ap.add_argument(
        "--room-margin",
        type=float,
        default=0.35,
        help="extra margin around each room, as a fraction of the room size (default 0.35)",
    )
    ap.add_argument(
        "--keep-keywords",
        type=str,
        default=",".join(DEFAULT_KEEP_KEYWORDS),
        help="comma-separated keywords for layers to keep",
    )
    ap.add_argument(
        "--drop-keywords",
        type=str,
        default=",".join(DEFAULT_DROP_KEYWORDS),
        help="comma-separated keywords for layers to always drop",
    )
    ap.add_argument("--page", type=int, default=0, help="page number (0-based), default 0")
    args = ap.parse_args()

    doc = fitz.open(args.input_pdf)
    page = doc[args.page]

    if args.list_layers:
        layers = list_layers(doc)
        if not layers:
            print("No OCG/CAD layers found in this PDF.")
        else:
            print(f"{len(layers)} layer(s) found:")
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
        remove_text=not args.no_ocr,
    )
    if clean_result.mode_a:
        print("-> Usable CAD layers found: cleaning via CAD layers.")
    else:
        print("-> No usable CAD layers: falling back to image recognition (color + OCR).")

    clean_result.image.save(args.output_png)
    print(f"Saved: {args.output_png} ({clean_result.image.width}x{clean_result.image.height}px)")

    if args.rooms:
        try:
            print("\nDetecting rooms...")
            detection = run_room_detection(page, args.scale, clean_result)
            print(f"{len(detection.rooms)} room(s) found.")

            n_named = sum(1 for r in detection.rooms if r.name)
            print(
                f"{n_named}/{len(detection.rooms)} room(s) named automatically; "
                f"the rest get a sequence number (room_NN)."
            )
            if not clean_result.mode_a and detection.rooms:
                print(
                    "Note: room detection without CAD layers is a best-effort "
                    "(image recognition) and less reliable than with CAD layers."
                )

            out_dir = os.path.splitext(args.output_png)[0] + "_rooms"
            result = export_rooms(
                clean_result.image,
                detection.rooms,
                out_dir,
                args.input_pdf,
                detection.anchor_log,
                clean_result.mode_a,
                scale=args.scale,
                margin_frac=args.room_margin,
            )
            print(f"{len(result.filenames)} separate room PNG(s) saved in: {out_dir}")
            print(f"Log saved: {result.log_path}")
        except ModuleNotFoundError as e:
            print(
                f"\nWARNING: separate room PNGs skipped - missing "
                f"Python package ({e.name})."
            )
            print(f"Install it with: pip install {e.name}")
            print("The main floorplan above was saved fine.")
        except Exception as e:
            print(
                f"\nWARNING: separate room PNGs skipped due to an "
                f"unexpected error: {e}"
            )
            print("The main floorplan above was saved fine.")


if __name__ == "__main__":
    main()
