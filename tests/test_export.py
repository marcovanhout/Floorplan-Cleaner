import numpy as np
from PIL import Image

from src.core.export import _estimate_door_area_threshold, save_room_crops, write_room_log
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
    filenames = save_room_crops(img, rooms, str(tmp_path), scale=1.0, margin_frac=0.5)
    assert filenames["room_1"] == "hoek.png"
    # bbox is 50x50; margin_frac=0.5 zou 25px marge geven, maar de vaste
    # basismarge (30px op scale=1.0) is hier groter en wint dus - marge
    # links/boven klipt bovendien tegen de rand van de afbeelding (10-30<0).
    with Image.open(tmp_path / "hoek.png") as crop:
        assert crop.size == (90, 90)


def test_estimate_door_area_threshold_finds_gap_between_door_and_room_cluster():
    # 44 deur-vakjes (33489-46872) vs 17 echte ruimtes (126994+) - zelfde
    # verhouding als het echte testbestand (W-WR-68-011) waarop de simpele
    # mediaan-aanpak faalde, omdat er dan meer deur- dan kamer-vakjes zijn.
    door_areas = [33489, 33672, 33672, 39204, 39402, 39402, 39600, 39601, 46440, 46872] * 4
    door_areas = door_areas[:44]
    room_areas = [126994, 127380, 179600, 385440, 452693, 474144, 802648, 1354203]
    threshold = _estimate_door_area_threshold(door_areas + room_areas)
    assert max(door_areas) < threshold < min(room_areas)


def test_estimate_door_area_threshold_returns_zero_without_clear_gap():
    # Alle vakken ongeveer even groot - geen zinnige "deur vs. kamer"-knip
    # te maken, dus geen aanname doen (drempel 0 => nooit deur-achtig).
    similar_areas = [10000, 10500, 9800, 10200, 9900, 10100, 10300]
    assert _estimate_door_area_threshold(similar_areas) == 0.0


def test_save_room_crops_extends_crop_toward_adjacent_doorlike_box(tmp_path):
    # Kamer (400x400) met een klein, deur-achtig vak dat direct tegen de
    # bovenkant aan ligt en verder naar boven uitsteekt dan de gewone
    # basismarge alleen zou reiken - de uitsnede moet specifiek op die
    # kant uitgebreid worden tot voorbij het deur-vakje (plus buffer).
    # Een paar losstaande, normaal-grote "vulruimtes" erbij zodat de
    # grootte-clustering (zie _estimate_door_area_threshold) genoeg data
    # heeft om het deur-vakje betrouwbaar als klein te herkennen - met
    # te weinig ruimtes in totaal durft die functie geen aanname te doen.
    img = _blank_image(w=2000, h=2000)
    room = RoomRecord(id="room_1", bbox=(300, 300, 700, 700), name="Kamer")
    door = RoomRecord(id="room_2", bbox=(450, 150, 550, 300), name=None)  # raakt de bovenkant
    fillers = [
        RoomRecord(id=f"filler_{i}", bbox=(1200 + i * 400, 1200, 1580 + i * 400, 1580), name=f"Vulruimte {i}")
        for i in range(3)
    ]
    save_room_crops(img, [room, door, *fillers], str(tmp_path), scale=1.0)

    with Image.open(tmp_path / "kamer.png") as crop:
        # Basismarge alleen (0.15 * 400 = 60) zou bij y=300-60=240 stoppen;
        # het deur-vakje steekt door tot y=150, dus de bovenkant van de
        # uitsnede moet ruim voorbij dat punt liggen (150 - buffer), en
        # zeker niet bij de kale basismarge (240) blijven steken.
        assert crop.size == (520, 630)


def test_save_room_crops_ignores_doorlike_box_that_is_not_adjacent(tmp_path):
    img = _blank_image(w=2000, h=2000)
    room = RoomRecord(id="room_1", bbox=(300, 300, 700, 700), name="Kamer")
    far_away_small_box = RoomRecord(id="room_2", bbox=(10, 10, 60, 60), name=None)
    fillers = [
        RoomRecord(id=f"filler_{i}", bbox=(1200 + i * 400, 1200, 1580 + i * 400, 1580), name=f"Vulruimte {i}")
        for i in range(3)
    ]
    save_room_crops(img, [room, far_away_small_box, *fillers], str(tmp_path), scale=1.0)

    with Image.open(tmp_path / "kamer.png") as crop:
        # Geen enkel aangrenzend deur-vakje - alleen de kale basismarge
        # (0.15 * 400 = 60 op elke kant) hoort toegepast te worden.
        assert crop.size == (520, 520)


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
