"""Regressietest: vergelijkt de geport core-pipeline met het originele
Plattegrond_Schoonmaker_v1/floorplan_cleaner.py-prototype op dezelfde
synthetische fixture. Mechanische controle dat de refactor (modules
splitsen, print() -> return-waarden, RoomRecord i.p.v. label-ids) geen
gedrag heeft veranderd.
"""

import numpy as np

import floorplan_cleaner as v1  # uit Plattegrond_Schoonmaker_v1/, via conftest.py sys.path
import fitz

from src.core.export import save_room_crops
from src.core.pipeline import run_clean, run_room_detection

from conftest import SIMPLE_FLOORPLAN_PDF

SCALE = 2.0


def _run_v1(pdf_path, scale):
    doc = v1.fitz.open(str(pdf_path))
    page = doc[0]
    mode_a = v1.has_usable_layers(doc, v1.DEFAULT_KEEP_KEYWORDS)
    assert mode_a
    img = v1.clean_via_layers(doc, page, scale, v1.DEFAULT_KEEP_KEYWORDS, v1.DEFAULT_DROP_KEYWORDS)
    room_boxes, labels = v1.detect_room_boxes(img, dilate_iters=4)
    anchors, candidates = v1.extract_room_names_from_pdf(page, scale)
    room_names, anchor_log = v1.match_names_to_rooms(
        room_boxes, labels, anchors, candidates, max_name_dist_px=80 * scale
    )
    return img, room_boxes, room_names


def _run_v2(pdf_path, scale):
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    clean_result = run_clean(doc, page, scale=scale)
    assert clean_result.mode_a
    detection = run_room_detection(page, scale, clean_result)
    return clean_result.image, detection.rooms


def test_ported_pipeline_matches_v1_prototype_image_and_rooms():
    v1_img, v1_boxes, v1_names = _run_v1(SIMPLE_FLOORPLAN_PDF, SCALE)
    v2_img, v2_rooms = _run_v2(SIMPLE_FLOORPLAN_PDF, SCALE)

    assert np.array_equal(np.array(v1_img), np.array(v2_img)), "opgeschoonde afbeelding wijkt af"
    assert len(v1_boxes) == len(v2_rooms) == 1

    v1_room_names = sorted(n for n in v1_names.values() if n)
    v2_room_names = sorted(r.name for r in v2_rooms if r.name)
    assert v1_room_names == v2_room_names == ["Toilet"]


def test_ported_export_matches_v1_prototype_filenames(tmp_path):
    v1_img, v1_boxes, v1_names = _run_v1(SIMPLE_FLOORPLAN_PDF, SCALE)
    v1_filenames = v1.save_room_crops(v1_img, v1_boxes, v1_names, str(tmp_path / "v1"))

    _, v2_rooms = _run_v2(SIMPLE_FLOORPLAN_PDF, SCALE)
    v2_filenames = save_room_crops(v1_img, v2_rooms, str(tmp_path / "v2"))

    assert sorted(v1_filenames.values()) == sorted(v2_filenames.values()) == ["toilet.png"]
