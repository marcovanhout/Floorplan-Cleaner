"""Tests voor de handmatige 'gum'-tool (correctiestap 'Erase'-knop): een
door de gebruiker aangewezen rechthoek permanent transparant maken."""

import numpy as np
from PIL import Image, ImageDraw

from src.core.pipeline import erase_rect


def _marked(width, height, mark_bbox):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    ImageDraw.Draw(img).rectangle(mark_bbox, fill=(0, 0, 0, 255))
    return img


def test_erase_rect_clears_only_the_given_area():
    image = Image.new("RGBA", (100, 60), (0, 0, 0, 255))

    erased = erase_rect(image, 10, 5, 40, 25)

    arr = np.array(erased)
    inside = arr[5:25, 10:40]
    assert (inside[:, :, 3] == 0).all(), "het opgegeven gebied moet volledig transparant zijn"

    outside_left = arr[:, :10]
    outside_below = arr[25:, :]
    assert (outside_left[:, :, 3] == 255).all()
    assert (outside_below[:, :, 3] == 255).all()


def test_erase_rect_clips_to_image_bounds():
    image = Image.new("RGBA", (100, 60), (0, 0, 0, 255))

    # Deels buiten de afbeelding - mag niet crashen, en moet alleen het
    # binnen-de-afbeelding-gedeelte wissen.
    erased = erase_rect(image, -20, -20, 20, 20)

    assert erased.size == (100, 60)
    arr = np.array(erased)
    assert (arr[:20, :20, 3] == 0).all()
    assert (arr[20:, 20:, 3] == 255).all()


def test_erase_rect_handles_swapped_coordinates():
    # x0/y0 hoeven niet per se de linkerbovenhoek te zijn (bv. van
    # rechtsonder naar linksboven gesleept).
    image = Image.new("RGBA", (100, 60), (0, 0, 0, 255))

    erased = erase_rect(image, 40, 25, 10, 5)

    arr = np.array(erased)
    assert (arr[5:25, 10:40, 3] == 0).all()


def test_erase_rect_leaves_the_rest_of_the_drawing_untouched():
    image = _marked(100, 60, [50, 5, 70, 15])

    erased = erase_rect(image, 0, 0, 20, 20)

    arr = np.array(erased)
    # De marker buiten het gum-gebied moet ongewijzigd (ondoorzichtig) blijven.
    assert (arr[5:15, 50:70, 3] == 255).all()
