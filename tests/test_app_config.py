"""Instellingen die create_app() vastzet."""

from PIL import Image

from src.webapp.app import create_app


def test_pillow_pixel_limit_lifted_for_large_drawings():
    # Undo (/restore) opent de eigen afbeelding opnieuw met Image.open - met
    # Pillow's standaardgrens (~179 MP) brak dat bij bv. een A0 op schaal 5.
    create_app()
    assert Image.MAX_IMAGE_PIXELS is None
