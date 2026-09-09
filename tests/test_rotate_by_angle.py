"""Tests voor de vrije-hoek-rotatie (naast de exacte 90-graden-knop).

Ruimte-vakken blijven rechte rechthoeken; bij een hoek ver van een
rechte hoek wordt de rechte omtrek om een dan schuinstaande ruimte
noodzakelijkerwijs ruimer dan de ruimte zelf (bewust geaccepteerd, zie
docstring van rotate_by_angle). Deze tests controleren dat de berekende
ruimte-bbox daadwerkelijk overeenkomt met waar de content in de
gedraaide afbeelding is beland."""

import numpy as np
from PIL import Image, ImageDraw

from src.core.pipeline import rotate_by_angle
from src.core.types import RoomRecord


def _blank(width, height):
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def _opaque_bbox(image):
    """Bounding box van alle niet-transparante pixels."""
    arr = np.array(image)
    mask = arr[:, :, 3] > 0
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def test_rotate_by_angle_preserves_other_room_fields():
    image = _blank(200, 120)
    room = RoomRecord(id="r1", bbox=(20, 10, 60, 30), name="Toilet", source="auto")

    _, rotated_rooms = rotate_by_angle(image, [room], 30)

    assert rotated_rooms[0].id == "r1"
    assert rotated_rooms[0].name == "Toilet"
    assert rotated_rooms[0].source == "auto"


def test_rotate_by_angle_zero_degrees_is_a_near_no_op():
    image = _blank(200, 120)
    room = RoomRecord(id="r1", bbox=(20, 10, 60, 30), name=None, source="auto")

    rotated_image, rotated_rooms = rotate_by_angle(image, [room], 0)

    # expand=True bij 0 graden kan het canvas met een paar pixels laten
    # groeien door afrondingen in PIL - geen exacte gelijkheid verwachten,
    # wel vrijwel identiek.
    assert abs(rotated_image.width - 200) <= 2
    assert abs(rotated_image.height - 120) <= 2
    x0, y0, x1, y1 = rotated_rooms[0].bbox
    assert abs(x0 - 20) <= 2 and abs(y0 - 10) <= 2
    assert abs(x1 - 60) <= 2 and abs(y1 - 30) <= 2


def test_rotate_by_angle_room_bbox_matches_actual_content_position():
    image = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    bbox = (20, 10, 60, 30)
    # Ondoorzichtig zwart tekenen (net als een echte "muur"-render), zodat
    # de content zelf ook meedraait en we kunnen vergelijken.
    ImageDraw.Draw(image).rectangle(bbox, fill=(0, 0, 0, 255))
    room = RoomRecord(id="r1", bbox=bbox, name=None, source="auto")

    rotated_image, rotated_rooms = rotate_by_angle(image, [room], 30)

    actual = _opaque_bbox(rotated_image)
    predicted = rotated_rooms[0].bbox

    # De voorspelde (rechte) bbox moet de daadwerkelijke (schuine) content
    # ruim omvatten - en niet gek veel groter zijn dan nodig. Marge van een
    # paar pixels voor afronding en de zachte rand die bicubic-resampling
    # geeft (een enkel zwak anti-aliased randpixel telt al mee als "opaque").
    margin = 5
    assert predicted[0] <= actual[0] + margin
    assert predicted[1] <= actual[1] + margin
    assert predicted[2] >= actual[2] - margin
    assert predicted[3] >= actual[3] - margin
    assert (predicted[2] - predicted[0]) <= (actual[2] - actual[0]) + 2 * margin
    assert (predicted[3] - predicted[1]) <= (actual[3] - actual[1]) + 2 * margin
