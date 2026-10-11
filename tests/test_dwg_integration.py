"""DWG van begin tot eind, met de echte LibreDWG (dwg2dxf.exe). Wordt
overgeslagen als die niet aanwezig is (python scripts/fetch_libredwg.py)."""

import io
import shutil

import pymupdf
import pytest
from conftest import FIXTURES_DIR

from src.core.dwg import convert_dwg_to_pdf, is_dwg_available
from src.core.layers import list_layers
from src.core.pipeline import run_clean, run_room_detection
from src.webapp.app import create_app

SIMPLE_FLOORPLAN_DWG = FIXTURES_DIR / "simple_floorplan.dwg"

pytestmark = pytest.mark.skipif(not is_dwg_available(), reason="LibreDWG dwg2dxf not available")


def test_dwg_converts_to_layered_pdf_with_named_rooms(tmp_path):
    dwg_path = tmp_path / "input.dwg"
    shutil.copyfile(SIMPLE_FLOORPLAN_DWG, dwg_path)
    result = convert_dwg_to_pdf(dwg_path, tmp_path / "input.pdf")
    assert result.text_count >= 4

    doc = pymupdf.open(tmp_path / "input.pdf")
    assert {"A-WALL", "A-DOOR", "A-ANNO-TEXT", "AREA-FILL"} <= {layer["name"] for layer in list_layers(doc)}

    page = doc[0]
    clean = run_clean(doc, page, scale=4.0, selected_layers=["A-WALL", "A-DOOR"])
    assert clean.mode_a
    rooms = run_room_detection(page, 4.0, clean).rooms
    assert {r.name for r in rooms} == {"Toilet", "Berging"}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _upload(client, data: bytes, name: str):
    return client.post("/upload", data={"pdf": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def test_upload_dwg_returns_layers_and_recommendation(client):
    resp = _upload(client, SIMPLE_FLOORPLAN_DWG.read_bytes(), "plan.dwg")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["source_type"] == "dwg"
    assert "A-WALL" in data["layers"]
    assert {"A-WALL", "A-DOOR"} <= set(data["recommended_layers"])
    assert "AREA-FILL" not in data["recommended_layers"]


def test_upload_rejects_unknown_file_with_readable_message(client):
    resp = _upload(client, b"PK\x03\x04 not a drawing", "plan.dwg")
    assert resp.status_code == 415
    assert resp.content_type.startswith("text/plain")
    assert "not a PDF or DWG" in resp.get_data(as_text=True)


def test_upload_truncated_dwg_gives_readable_error(client):
    resp = _upload(client, SIMPLE_FLOORPLAN_DWG.read_bytes()[:200], "broken.dwg")
    assert resp.status_code == 422
    assert resp.content_type.startswith("text/plain")
    assert "<html" not in resp.get_data(as_text=True).lower()
