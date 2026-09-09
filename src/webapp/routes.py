"""Flask-routes: upload -> detecteren -> corrigeren (canvas) -> exporteren."""

import io
import math
import os
import shutil

import pymupdf as fitz
from flask import Blueprint, abort, jsonify, render_template, request, send_file

from src.core.constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from src.core.layers import apply_explicit_layer_selection, list_layers, recommend_layers
from src.core.pipeline import (
    erase_rect,
    export_rooms,
    rotate_by_angle,
    rotate_clockwise,
    run_clean,
    run_room_detection,
)
from src.core.raster import is_tesseract_available
from src.core.render import force_black_lines, image_to_png_bytes, render_page
from src.core.types import RoomRecord

from .state import cleanup_job, create_job, get_job

bp = Blueprint("floorplan", __name__)

# Streefbreedte (in pixels) voor de live laag-voorbeeldafbeelding op de
# uploadpagina - onafhankelijk van de door de gebruiker gekozen
# renderresolutie, puur om elke keer dat een vakje wordt aan/uitgevinkt
# snel te blijven renderen, ook bij een groot A0-bouwtekening-formaat.
PREVIEW_TARGET_WIDTH_PT = 900


def _room_to_dict(room: RoomRecord) -> dict:
    return {"id": room.id, "bbox": list(room.bbox), "name": room.name, "source": room.source}


def _room_from_dict(d: dict) -> RoomRecord:
    bbox = d.get("bbox") or [0, 0, 0, 0]
    return RoomRecord(
        id=str(d["id"]),
        bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        name=(d.get("name") or None),
        source=d.get("source") or "user-edited",
    )


@bp.route("/")
def index():
    return render_template(
        "index.html",
        tesseract_available=is_tesseract_available(),
    )


@bp.route("/upload", methods=["POST"])
def upload():
    """Stap 1: bestand ontvangen en CAD-lagen inventariseren (als die er zijn),
    zodat de gebruiker in de laag-kiezer kan zien/aanpassen wat er meegenomen
    wordt VOORDAT de daadwerkelijke verwerking (/jobs/<id>/process) start.
    Elke tekenaar noemt lagen anders - een keywoord-gok is hooguit een
    startpunt (zie recommended), nooit de enige waarheid."""
    file = request.files.get("pdf")
    if not file or not file.filename:
        abort(400, "No PDF selected.")

    job = create_job(file.read(), file.filename)
    doc = fitz.open(job.pdf_path)

    layers = list_layers(doc)
    recommended = recommend_layers(doc, DEFAULT_KEEP_KEYWORDS, DEFAULT_DROP_KEYWORDS)

    return jsonify({
        "job_id": job.job_id,
        "layers": [layer["name"] for layer in layers],
        "recommended_layers": sorted(recommended),
    })


@bp.route("/jobs/<job_id>/preview", methods=["POST"])
def preview(job_id):
    """Snel voorbeeld van de opgeschoonde plattegrond voor de HUIDIGE
    laagkeuze in de laag-kiezer - geen ruimtedetectie, lagere resolutie
    dan de uiteindelijke export (zie PREVIEW_TARGET_WIDTH_PT), puur zodat
    je meteen ziet wat een aan/uitgevinkte laag oplevert."""
    job = get_job(job_id)
    if job is None:
        abort(404, "Unknown or expired job.")

    page_no = int(request.form.get("page", 0) or 0)
    selected_layers = request.form.getlist("layers")

    doc = fitz.open(job.pdf_path)
    if page_no < 0 or page_no >= doc.page_count:
        abort(400, f"Invalid page number: {page_no} (document has {doc.page_count} pages).")
    if not list_layers(doc):
        abort(400, "This PDF has no layers to preview.")
    page = doc[page_no]

    apply_explicit_layer_selection(doc, selected_layers)
    preview_scale = max(0.3, min(2.0, PREVIEW_TARGET_WIDTH_PT / page.rect.width))
    img = force_black_lines(render_page(page, preview_scale, alpha=True))

    return send_file(io.BytesIO(image_to_png_bytes(img)), mimetype="image/png")


@bp.route("/jobs/<job_id>/process", methods=["POST"])
def process(job_id):
    """Stap 2: daadwerkelijk opschonen + ruimtes detecteren, met de laagkeuze
    (indien van toepassing) uit de laag-kiezer op de uploadpagina."""
    job = get_job(job_id)
    if job is None:
        abort(404, "Unknown or expired job.")

    page_no = int(request.form.get("page", 0) or 0)
    scale = float(request.form.get("scale", 4.0) or 4.0)
    force_raster = request.form.get("force_raster") == "on"
    remove_text = request.form.get("remove_text", "on") == "on"

    doc = fitz.open(job.pdf_path)
    if page_no < 0 or page_no >= doc.page_count:
        abort(400, f"Invalid page number: {page_no} (document has {doc.page_count} pages).")
    page = doc[page_no]

    # Alleen als 'meesturen wat je hebt aangevinkt' zin heeft: had deze PDF
    # uberhaupt lagen? Zo niet (bv. een platte/gescande PDF), dan is er nooit
    # een laag-kiezer getoond en valt run_clean vanzelf terug op MODE B.
    selected_layers = request.form.getlist("layers") if list_layers(doc) else None

    clean_result = run_clean(
        doc, page, scale=scale, force_raster=force_raster, selected_layers=selected_layers,
        remove_text=remove_text,
    )
    detection = run_room_detection(page, scale, clean_result)

    job.page_no = page_no
    job.scale = scale
    job.mode_a = clean_result.mode_a
    job.clean_image = clean_result.image
    job.rooms = detection.rooms
    job.anchor_log = detection.anchor_log

    return jsonify({"job_id": job.job_id, "redirect": f"/jobs/{job.job_id}/correct"})


@bp.route("/jobs/<job_id>/correct")
def correct(job_id):
    job = get_job(job_id)
    if job is None:
        abort(404, "Unknown or expired job.")
    return render_template("correct.html", job_id=job_id)


@bp.route("/jobs/<job_id>/detect")
def detect(job_id):
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")
    return jsonify({
        "job_id": job.job_id,
        "image_url": f"/jobs/{job.job_id}/image",
        "width": job.clean_image.width,
        "height": job.clean_image.height,
        "mode": "A" if job.mode_a else "B",
        "rooms": [_room_to_dict(r) for r in job.rooms],
    })


@bp.route("/jobs/<job_id>/image")
def image(job_id):
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")
    return send_file(
        io.BytesIO(image_to_png_bytes(job.clean_image)),
        mimetype="image/png",
    )


@bp.route("/jobs/<job_id>/rotate", methods=["POST"])
def rotate(job_id):
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")

    body = request.get_json(force=True, silent=True) or {}
    rooms_payload = body.get("rooms")
    if not isinstance(rooms_payload, list):
        abort(400, "Expected a 'rooms' list in the request body.")
    rooms = [_room_from_dict(r) for r in rooms_payload]

    job.clean_image, job.rooms = rotate_clockwise(job.clean_image, rooms)

    return jsonify({
        "width": job.clean_image.width,
        "height": job.clean_image.height,
        "rooms": [_room_to_dict(r) for r in job.rooms],
    })


@bp.route("/jobs/<job_id>/rotate-angle", methods=["POST"])
def rotate_angle(job_id):
    """Vrije-hoek-rotatie naast de exacte 90-graden-knop hierboven - zie
    rotate_by_angle() voor de (bewust geaccepteerde) precisie-afweging bij
    een hoek ver van een rechte hoek."""
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")

    body = request.get_json(force=True, silent=True) or {}
    rooms_payload = body.get("rooms")
    if not isinstance(rooms_payload, list):
        abort(400, "Expected a 'rooms' list in the request body.")
    try:
        degrees = float(body.get("degrees"))
    except (TypeError, ValueError):
        abort(400, "Expected a numeric 'degrees' in the request body.")
    if not math.isfinite(degrees):
        abort(400, "Invalid angle.")
    rooms = [_room_from_dict(r) for r in rooms_payload]

    job.clean_image, job.rooms = rotate_by_angle(job.clean_image, rooms, degrees)

    return jsonify({
        "width": job.clean_image.width,
        "height": job.clean_image.height,
        "rooms": [_room_to_dict(r) for r in job.rooms],
    })


@bp.route("/jobs/<job_id>/erase", methods=["POST"])
def erase(job_id):
    """Handmatige 'gum': vlakt een door de gebruiker aangewezen rechthoek op
    de afbeelding wit/transparant - voor restjes die de automatische
    opschoning laat staan. Raakt alleen de afbeelding, niet de ruimte-vakken."""
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")

    body = request.get_json(force=True, silent=True) or {}
    try:
        x0, y0, x1, y1 = (int(body[k]) for k in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError):
        abort(400, "Expected numeric x0, y0, x1, y1 in the request body.")

    job.clean_image = erase_rect(job.clean_image, x0, y0, x1, y1)

    return jsonify({"width": job.clean_image.width, "height": job.clean_image.height})


@bp.route("/jobs/<job_id>/export", methods=["POST"])
def export(job_id):
    job = get_job(job_id)
    if job is None or job.clean_image is None:
        abort(404, "Unknown or expired job.")

    body = request.get_json(force=True, silent=True) or {}
    rooms_payload = body.get("rooms")
    if not isinstance(rooms_payload, list):
        abort(400, "Expected a 'rooms' list in the request body.")
    rooms = [_room_from_dict(r) for r in rooms_payload]
    margin_frac = float(body.get("room_margin", 0.35) or 0.35)

    out_dir = job.tmp_dir / "export"
    result = export_rooms(
        job.clean_image, rooms, str(out_dir), job.pdf_original_name,
        job.anchor_log, job.mode_a, margin_frac=margin_frac,
    )

    # De totale opgeschoonde plattegrond hoort ook in de export te zitten
    # (zie PROJECT_SPEC.md sectie 1), niet alleen de losse ruimte-PNG's.
    base_name = os.path.splitext(job.pdf_original_name)[0] or "floorplan"
    job.clean_image.save(out_dir / f"{base_name}_clean.png")

    zip_base = job.tmp_dir / "export"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=str(out_dir))
    job.export_zip_path = zip_path

    return jsonify({
        "download_url": f"/jobs/{job.job_id}/download",
        "filenames": result.filenames,
        "log_path": result.log_path,
    })


@bp.route("/jobs/<job_id>/download")
def download(job_id):
    job = get_job(job_id)
    if job is None or job.export_zip_path is None:
        abort(404, "Nothing exported yet for this job.")
    return send_file(
        job.export_zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name="rooms.zip",
    )


@bp.route("/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    cleanup_job(job_id)
    return jsonify({"ok": True})
