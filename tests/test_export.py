import numpy as np
from PIL import Image

from src.core.export import save_room_crops, write_room_log
from src.core.types import AnchorLogEntry, RoomRecord


def _blank_image(w=800, h=600) -> Image.Image:
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    return Image.fromarray(arr, "RGBA")


def test_save_room_crops_names_and_numbers_duplicates(tmp_path):
    img = _blank_image()
    rooms = [
        RoomRecord(id="room_1", bbox=(50, 50, 150, 150), name="Toilet"),
        RoomRecord(id="room_2", bbox=(200, 50, 300, 150), name="Toilet"),
        RoomRecord(id="room_3", bbox=(50, 200, 150, 300), name=None),
    ]
    out_dir = tmp_path / "rooms"
    filenames = save_room_crops(img, rooms, str(out_dir))

    assert filenames["room_1"] == "toilet_1.png"
    assert filenames["room_2"] == "toilet_2.png"
    assert filenames["room_3"] == "room_01.png"
    for fname in filenames.values():
        assert (out_dir / fname).exists()


def test_save_room_crops_applies_margin_and_clips_to_bounds(tmp_path):
    img = _blank_image(w=400, h=400)
    rooms = [RoomRecord(id="room_1", bbox=(10, 10, 60, 60), name="Hoek")]
    filenames = save_room_crops(img, rooms, str(tmp_path), margin_frac=0.5, min_margin_px=5)
    assert filenames["room_1"] == "hoek.png"


def test_write_room_log_reports_missing_names(tmp_path):
    rooms = [RoomRecord(id="room_1", bbox=(0, 0, 10, 10), name="Toilet")]
    filenames = {"room_1": "toilet.png"}
    anchor_log = [
        AnchorLogEntry(code="TL-1.01", name="Toilet", room_id="room_1", direct_hit=True),
        AnchorLogEntry(code="BG-2.02", name="Berging", room_id=None, direct_hit=False),
    ]
    log_path = tmp_path / "_log.txt"
    write_room_log(str(log_path), "input.pdf", rooms, filenames, anchor_log, mode_a=True)

    content = log_path.read_text(encoding="utf-8")
    assert "toilet.png  <-  Toilet" in content
    assert "Berging (code BG-2.02)" in content
    assert "could not be linked to a detected room area" in content
    assert "Toilet (code TL-1.01)" not in content  # kreeg wel een PNG, hoort niet in de lijst


def test_save_room_crops_suffixes_collision_between_named_and_fallback_room(tmp_path):
    # Eén ruimte heet al letterlijk "room_01" (bv. toegekend door
    # assign_placeholder_names bij de detectie), de andere is nog naamloos
    # (bv. een handmatig getekend vakje) en zou dezelfde terugvalnaam
    # krijgen. Beide moeten hun eigen bestand houden (met _1/_2-suffix),
    # niet dat de tweede de eerste stilzwijgend overschrijft.
    img = _blank_image()
    rooms = [
        RoomRecord(id="room_a", bbox=(50, 50, 150, 150), name="room_01"),
        RoomRecord(id="room_b", bbox=(200, 50, 300, 150), name=None),
    ]
    filenames = save_room_crops(img, rooms, str(tmp_path))
    assert filenames["room_a"] == "room_01_1.png"
    assert filenames["room_b"] == "room_01_2.png"
    assert (tmp_path / "room_01_1.png").exists()
    assert (tmp_path / "room_01_2.png").exists()


def test_save_room_crops_skips_room_entirely_outside_image(tmp_path):
    img = _blank_image(w=400, h=400)
    rooms = [
        RoomRecord(id="room_1", bbox=(-500, -500, -400, -450), name="Buiten beeld"),
        RoomRecord(id="room_2", bbox=(10, 10, 60, 60), name="Geldig"),
    ]
    filenames = save_room_crops(img, rooms, str(tmp_path))
    assert "room_1" not in filenames
    assert filenames["room_2"] == "geldig.png"


def test_write_room_log_reflects_user_deletion_after_correction(tmp_path):
    # Ruimte is door de gebruiker verwijderd in de correctie-UI: bestaat
    # niet meer in de finale 'rooms'-lijst, ook al stond 'm in het
    # oorspronkelijke anchor_log van de automatische detectie.
    rooms: list[RoomRecord] = []
    filenames: dict[str, str] = {}
    anchor_log = [
        AnchorLogEntry(code="TL-1.01", name="Toilet", room_id="room_1", direct_hit=True),
    ]
    log_path = tmp_path / "_log.txt"
    write_room_log(str(log_path), "input.pdf", rooms, filenames, anchor_log, mode_a=True)

    content = log_path.read_text(encoding="utf-8")
    assert "deleted or merged during manual correction" in content
