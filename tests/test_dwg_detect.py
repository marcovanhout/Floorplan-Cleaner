from pathlib import Path

from src.core import dwg


def test_sniff_kind_recognises_pdf_dwg_and_other():
    assert dwg.sniff_kind(b"%PDF-1.7\n...") == "pdf"
    assert dwg.sniff_kind(b"\xef\xbb\xbf\r\n%PDF-1.4") == "pdf"  # voorloopbytes toegestaan
    assert dwg.sniff_kind(b"AC1027\x00\x00") == "dwg"
    assert dwg.sniff_kind(b"AC1009\x00\x00") == "dwg"
    assert dwg.sniff_kind(b"PK\x03\x04") is None
    assert dwg.sniff_kind(b"") is None


def test_find_dwg2dxf_prefers_bundled_copy(monkeypatch, tmp_path):
    bundled = tmp_path / "dwg2dxf.exe"
    bundled.write_bytes(b"")
    monkeypatch.setattr(dwg, "_candidate_paths", lambda: [tmp_path / "missing.exe", bundled])
    monkeypatch.setattr(dwg.shutil, "which", lambda name: r"C:\elsewhere\dwg2dxf.exe")
    assert dwg.find_dwg2dxf() == bundled


def test_find_dwg2dxf_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr(dwg, "_candidate_paths", lambda: [tmp_path / "missing.exe"])
    monkeypatch.setattr(dwg.shutil, "which", lambda name: r"C:\elsewhere\dwg2dxf.exe")
    assert dwg.find_dwg2dxf() == Path(r"C:\elsewhere\dwg2dxf.exe")
    assert dwg.is_dwg_available()


def test_dwg_unavailable_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(dwg, "_candidate_paths", lambda: [tmp_path / "missing.exe"])
    monkeypatch.setattr(dwg.shutil, "which", lambda name: None)
    assert dwg.find_dwg2dxf() is None
    assert not dwg.is_dwg_available()
