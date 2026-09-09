"""Tests voor de Tesseract-locatie-fallback: de Windows-installer voegt
zichzelf niet altijd toe aan PATH, dus moet de app ook op de gebruikelijke
installatielocatie kunnen zoeken (zie src/core/raster.py::_ensure_tesseract_cmd)."""

import pytest

from src.core import raster


@pytest.fixture(autouse=True)
def _reset_tesseract_state(monkeypatch):
    """Elke test start met een schone lei: nog niet eerder gezocht, en
    tesseract_cmd op de standaardwaarde - anders lekt state tussen tests
    (en tussen deze tests en de rest van de suite) door de module-level cache."""
    import pytesseract

    monkeypatch.setattr(raster, "_tesseract_cmd_resolved", False)
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    yield


def test_leaves_tesseract_cmd_untouched_when_already_on_path(monkeypatch):
    monkeypatch.setattr(raster.shutil, "which", lambda cmd: r"C:\somewhere\tesseract.exe")

    raster._ensure_tesseract_cmd()

    import pytesseract

    assert pytesseract.pytesseract.tesseract_cmd == "tesseract"


def test_falls_back_to_common_install_path_when_not_on_path(monkeypatch, tmp_path):
    fake_exe = tmp_path / "tesseract.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(raster.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(raster, "_COMMON_TESSERACT_PATHS", [str(fake_exe)])

    raster._ensure_tesseract_cmd()

    import pytesseract

    assert pytesseract.pytesseract.tesseract_cmd == str(fake_exe)


def test_leaves_tesseract_cmd_untouched_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(raster.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(raster, "_COMMON_TESSERACT_PATHS", [str(tmp_path / "nope.exe")])

    raster._ensure_tesseract_cmd()

    import pytesseract

    assert pytesseract.pytesseract.tesseract_cmd == "tesseract"


def test_only_resolves_once(monkeypatch):
    calls = []
    monkeypatch.setattr(raster.shutil, "which", lambda cmd: calls.append(cmd) or None)
    monkeypatch.setattr(raster, "_COMMON_TESSERACT_PATHS", [])

    raster._ensure_tesseract_cmd()
    raster._ensure_tesseract_cmd()

    assert len(calls) == 1
