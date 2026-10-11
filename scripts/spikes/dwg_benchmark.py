"""Benchmark DWG -> layered PDF -> existing tool pipeline on the local test DWGs.

Reads the real (never committed) drawings in "Test PDF/", writes PDFs and
cleaned PNGs to scripts/spikes/_out/dwg/ (gitignored).

    .venv\\Scripts\\python scripts/spikes/dwg_benchmark.py
"""

import shutil
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.constants import (  # noqa: E402
    DEFAULT_DROP_KEYWORDS,
    DEFAULT_KEEP_KEYWORDS,
    DWG_FALLBACK_DROP_KEYWORDS,
)
from src.core.dwg import convert_dwg_to_pdf  # noqa: E402
from src.core.layers import layers_without_keywords, list_layers, recommend_layers  # noqa: E402
from src.core.names import extract_room_names_from_pdf  # noqa: E402
from src.core.pipeline import run_clean, run_room_detection  # noqa: E402

OUT = ROOT / "scripts" / "spikes" / "_out" / "dwg"
SCALE = 4.0


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dwgs = sorted((ROOT / "Test PDF").glob("*.dwg"))
    if len(sys.argv) > 1:
        dwgs = [p for p in dwgs if p.stem in sys.argv[1:]]
    for src in dwgs:
        work = OUT / src.stem
        work.mkdir(exist_ok=True)
        dwg = work / "input.dwg"
        shutil.copyfile(src, dwg)
        pdf = work / "input.pdf"

        res = convert_dwg_to_pdf(dwg, pdf)
        doc = pymupdf.open(pdf)
        page = doc[0]
        layers = list_layers(doc)
        recommended = sorted(
            recommend_layers(doc, DEFAULT_KEEP_KEYWORDS, DEFAULT_DROP_KEYWORDS)
            or layers_without_keywords(doc, DWG_FALLBACK_DROP_KEYWORDS)
        )
        anchors, candidates = extract_room_names_from_pdf(page, SCALE)

        t0 = time.perf_counter()
        clean = run_clean(doc, page, scale=SCALE, selected_layers=recommended)
        det = run_room_detection(page, SCALE, clean)
        t_tool = time.perf_counter() - t0
        named = sum(1 for r in det.rooms if r.name and not r.name.startswith("room_"))
        clean.image.save(work / "clean.png")

        size_mm = f"{page.rect.width * 25.4 / 72:.0f}x{page.rect.height * 25.4 / 72:.0f}mm"
        conv = sum(res.timings.values())
        print(
            f"{src.stem:16s} convert {conv:5.1f}s ({', '.join(f'{k} {v:.1f}' for k, v in res.timings.items())})"
            f" | page {size_mm} | {len(layers)} layers, {len(recommended)} recommended"
            f" | {res.text_count} texts, {len(anchors)} codes, {len(candidates)} names"
            f" | tool {t_tool:4.1f}s, mode_a={clean.mode_a}, {len(det.rooms)} rooms ({named} named)"
        )
        for w in res.warnings:
            print(f"{'':16s} ! {w}")


if __name__ == "__main__":
    main()
