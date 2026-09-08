import numpy as np
from PIL import Image

from src.core.rooms import detect_room_boxes


def _make_bordered_room_image(size=(400, 300), margin=100, wall=6) -> Image.Image:
    """RGBA-afbeelding met een zwarte rechthoekige ruimte-omtrek, klein
    t.o.v. het canvas (zoals een echte plattegrond met marge eromheen -
    zie tests/fixtures/generate_fixtures.py voor waarom dat nodig is)."""
    w, h = size
    arr = np.zeros((h, w, 4), dtype=np.uint8)  # alles transparant
    x0, y0, x1, y1 = margin, margin, w - margin, h - margin
    arr[y0 : y0 + wall, x0:x1, 3] = 255  # boven
    arr[y1 - wall : y1, x0:x1, 3] = 255  # onder
    arr[y0:y1, x0 : x0 + wall, 3] = 255  # links
    arr[y0:y1, x1 - wall : x1, 3] = 255  # rechts
    return Image.fromarray(arr, "RGBA")


def test_detect_single_enclosed_room():
    img = _make_bordered_room_image()
    boxes, labels = detect_room_boxes(img, dilate_iters=2, min_pixels=500)
    assert len(boxes) == 1
    (x0, y0, x1, y1) = next(iter(boxes.values()))
    # bbox moet binnen de muur-omtrek liggen, niet het hele canvas beslaan
    assert x0 > 0 and y0 > 0
    assert x1 < img.width and y1 < img.height


def test_detect_no_rooms_on_blank_image():
    arr = np.zeros((200, 200, 4), dtype=np.uint8)
    img = Image.fromarray(arr, "RGBA")
    boxes, labels = detect_room_boxes(img, dilate_iters=2, min_pixels=500)
    assert boxes == {}


def test_detect_room_ignores_tiny_specks_below_min_pixels():
    img = _make_bordered_room_image(size=(400, 300), margin=100)
    arr = np.array(img)
    # klein los vlekje ruis toevoegen, ver van de muren
    arr[20:23, 20:23, 3] = 255
    img2 = Image.fromarray(arr, "RGBA")
    boxes, labels = detect_room_boxes(img2, dilate_iters=2, min_pixels=500)
    assert len(boxes) == 1
