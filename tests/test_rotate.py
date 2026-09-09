"""Tests voor het 90-graden roteren van de opgeschoonde plattegrond +
ruimte-vakken (correctiestap 'Roteren'-knop)."""

from PIL import Image

from src.core.pipeline import rotate_clockwise
from src.core.types import RoomRecord


def _blank(width, height):
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def test_rotate_clockwise_swaps_dimensions_and_room_bbox():
    image = _blank(100, 60)
    room = RoomRecord(id="r1", bbox=(10, 5, 30, 15), name="Toilet", source="auto")

    rotated_image, rotated_rooms = rotate_clockwise(image, [room])

    assert rotated_image.size == (60, 100)
    assert rotated_rooms[0].bbox == (45, 10, 55, 30)
    # id/naam/source moeten ongewijzigd blijven, alleen de bbox verandert
    assert rotated_rooms[0].id == "r1"
    assert rotated_rooms[0].name == "Toilet"
    assert rotated_rooms[0].source == "auto"


def test_rotate_clockwise_four_times_returns_to_original():
    image = _blank(100, 60)
    room = RoomRecord(id="r1", bbox=(10, 5, 30, 15), name=None, source="auto")

    rooms = [room]
    for _ in range(4):
        image, rooms = rotate_clockwise(image, rooms)

    assert image.size == (100, 60)
    assert rooms[0].bbox == (10, 5, 30, 15)
