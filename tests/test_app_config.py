"""Instellingen die create_app() vastzet."""

from PIL import Image

from src.webapp.app import create_app


def test_pillow_pixel_limit_lifted_for_large_drawings():
    # Undo van een vrije-hoek-draai leest de eigen PNG-kopie terug met
    # Image.open - met Pillow's standaardgrens (~179 MP) brak dat bij bv.
    # een A0 op schaal 5.
    create_app()
    assert Image.MAX_IMAGE_PIXELS is None


def test_correct_page_shows_uploaded_file_name():
    from src.webapp.state import cleanup_job, create_job

    job = create_job(b"%PDF-1.4", "Plattegrond <BG>.pdf")
    try:
        html = create_app().test_client().get(f"/jobs/{job.job_id}/correct").get_data(as_text=True)
    finally:
        cleanup_job(job.job_id)
    # Zichtbaar in de kop én in de titel van het browsertabblad, en netjes
    # ge-escaped (een bestandsnaam mag nooit als HTML geïnterpreteerd worden).
    assert html.count("Plattegrond &lt;BG&gt;.pdf") >= 2
    assert "<BG>" not in html
