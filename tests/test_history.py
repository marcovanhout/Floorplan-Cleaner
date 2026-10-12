"""Undo/redo van afbeeldingswijzigingen in het correctiescherm (zie
src/webapp/history.py): via de echte Flask-routes, met een kleine
kunstmatige tekening."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.webapp.app import create_app
from src.webapp.history import HISTORY_LIMIT
from src.webapp.state import cleanup_job, create_job


def _drawing():
    # Zwart-op-transparant zoals een echte opgeschoonde tekening, met een
    # asymmetrisch patroon zodat een verkeerde draairichting opvalt.
    img = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 60, 30], outline=(0, 0, 0, 255), width=3)
    draw.line([70, 10, 115, 70], fill=(0, 0, 0, 255), width=2)
    draw.rectangle([10, 50, 25, 75], fill=(0, 0, 0, 255))
    return img


@pytest.fixture
def job_client():
    job = create_job(b"%PDF-1.4", "test.pdf")
    job.clean_image = _drawing()
    client = create_app().test_client()
    try:
        yield job, client
    finally:
        cleanup_job(job.job_id)


def _pixels(job):
    return np.array(job.clean_image)


def _post(client, job, action, body=None):
    resp = client.post(f"/jobs/{job.job_id}/{action}", json=body or {})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _erase(client, job, rect):
    x0, y0, x1, y1 = rect
    return _post(client, job, "erase", {"x0": x0, "y0": y0, "x1": x1, "y1": y1})["step_id"]


def _rotate(client, job):
    return _post(client, job, "rotate", {"rooms": []})["step_id"]


def _rotate_angle(client, job, degrees):
    return _post(client, job, "rotate-angle", {"rooms": [], "degrees": degrees})["step_id"]


def test_erase_undo_redo_is_pixel_exact(job_client):
    job, client = job_client
    original = _pixels(job)
    step = _erase(client, job, (0, 0, 40, 40))
    erased = _pixels(job)
    assert not np.array_equal(original, erased)

    assert _post(client, job, "undo", {"step_id": step})["kind"] == "erase"
    assert np.array_equal(_pixels(job), original)

    _post(client, job, "redo", {"step_id": step})
    assert np.array_equal(_pixels(job), erased)


def test_rotate90_undo_redo_is_exact(job_client):
    job, client = job_client
    original = _pixels(job)
    step = _rotate(client, job)
    rotated = _pixels(job)
    assert rotated.shape[:2] == (120, 80)

    data = _post(client, job, "undo", {"step_id": step})
    assert (data["width"], data["height"]) == (120, 80)
    assert np.array_equal(_pixels(job), original)

    _post(client, job, "redo", {"step_id": step})
    assert np.array_equal(_pixels(job), rotated)


def test_rotate_angle_undo_restores_original_and_redo_the_rotation(job_client):
    job, client = job_client
    original = _pixels(job)
    step = _rotate_angle(client, job, 17)
    rotated = _pixels(job)

    _post(client, job, "undo", {"step_id": step})
    assert np.array_equal(_pixels(job), original)

    _post(client, job, "redo", {"step_id": step})
    assert np.array_equal(_pixels(job), rotated)


def test_mixed_sequence_undoes_and_redoes_in_order(job_client):
    job, client = job_client
    states = [_pixels(job)]
    steps = []
    for action in (
        lambda: _erase(client, job, (0, 0, 30, 30)),
        lambda: _rotate(client, job),
        lambda: _erase(client, job, (0, 0, 20, 50)),
        lambda: _rotate_angle(client, job, -5),
    ):
        steps.append(action())
        states.append(_pixels(job))

    for i in reversed(range(len(steps))):
        _post(client, job, "undo", {"step_id": steps[i]})
        assert np.array_equal(_pixels(job), states[i])
    for i in range(len(steps)):
        _post(client, job, "redo", {"step_id": steps[i]})
        assert np.array_equal(_pixels(job), states[i + 1])


def test_new_change_after_undo_clears_redo(job_client):
    job, client = job_client
    step = _erase(client, job, (0, 0, 10, 10))
    _post(client, job, "undo", {"step_id": step})
    _erase(client, job, (50, 50, 60, 60))
    resp = client.post(f"/jobs/{job.job_id}/redo", json={"step_id": step})
    assert resp.status_code == 409


def test_wrong_step_id_is_refused_and_changes_nothing(job_client):
    job, client = job_client
    _erase(client, job, (0, 0, 10, 10))
    before = _pixels(job)
    resp = client.post(f"/jobs/{job.job_id}/undo", json={"step_id": "something-else"})
    assert resp.status_code == 409
    assert np.array_equal(_pixels(job), before)


def test_history_is_limited(job_client):
    job, client = job_client
    for i in range(HISTORY_LIMIT + 5):
        _erase(client, job, (i, 0, i + 1, 1))
    assert len(job.undo_stack) == HISTORY_LIMIT


def test_erase_outside_the_drawing_is_still_a_step(job_client):
    # De browser telt elke veeg als stap; ook een veeg die helemaal naast
    # de tekening valt moet dus als (lege) stap terug te draaien zijn.
    job, client = job_client
    original = _pixels(job)
    step = _erase(client, job, (500, 500, 600, 600))
    _post(client, job, "undo", {"step_id": step})
    assert np.array_equal(_pixels(job), original)


def test_opening_the_correction_screen_clears_history(job_client):
    job, client = job_client
    _erase(client, job, (0, 0, 10, 10))
    assert client.get(f"/jobs/{job.job_id}/detect").status_code == 200
    assert job.undo_stack == [] and job.redo_stack == []


def test_image_region_returns_exactly_that_part_after_undo(job_client):
    # Undo van een veeg tekent in de browser alleen dit stukje terug.
    import io

    job, client = job_client
    original = _pixels(job)
    step = _erase(client, job, (5, 5, 45, 35))
    _post(client, job, "undo", {"step_id": step})
    resp = client.get(f"/jobs/{job.job_id}/image-region?x0=5&y0=5&x1=45&y1=35")
    assert resp.status_code == 200
    region = np.array(Image.open(io.BytesIO(resp.data)).convert("RGBA"))
    assert np.array_equal(region, original[5:35, 5:45])
