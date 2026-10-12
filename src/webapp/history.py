"""Undo/redo-geschiedenis van de AFBEELDING in het correctiescherm.

Alleen roteren en gummen veranderen de afbeelding op de server; wijzigingen
aan ruimte-vakken leven tot het exporteren client-side, en die houdt de
browser zelf bij (zie correct.js). De browser houdt één gezamenlijke rij
stappen bij en roept /undo en /redo hier alleen aan voor een
afbeeldingsstap - beide lijsten lopen dus in dezelfde volgorde, en elke
stap heeft een id waarmee de server controleert dat dat zo blijft.

Per soort stap wordt zo ZUINIG mogelijk opgeslagen - een volledige kopie
van een grote tekening is in het geheugen al gauw een halve gigabyte:
- erase: alleen de pixels van het gewiste gebied van vóór het wissen;
- rotate90: niets - een 90-graden-draai is exact terug te draaien;
- rotate_angle: een PNG-kopie van vóór (en na een undo ook van ná) de
  draai. Vrij draaien interpoleert pixels en is dus niet exact
  omkeerbaar; een opgeschoonde tekening is zwart-op-transparant en comprimeert
  daardoor sterk (een A0 op schaal 4 is ~0,6 MB).
"""

import io
import uuid
from dataclasses import dataclass

from PIL import Image

from src.core.pipeline import clip_rect, erase_rect

HISTORY_LIMIT = 20


@dataclass
class ImageStep:
    kind: str  # "erase" | "rotate90" | "rotate_angle"
    id: str
    rect: tuple[int, int, int, int] | None = None  # erase: bijgesneden gebied
    patch: Image.Image | None = None  # erase: pixels van vóór het wissen
    before_png: bytes | None = None  # rotate_angle
    after_png: bytes | None = None  # rotate_angle, pas gevuld bij de eerste undo


class HistoryMismatch(Exception):
    """De browser vraagt om een andere stap dan de server bovenop heeft."""


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # compress_level=1: veel sneller dan de standaard (6), en bij deze
    # zwart/transparante tekeningen nauwelijks groter.
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _from_png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _record(job, step: ImageStep) -> ImageStep:
    job.undo_stack.append(step)
    del job.undo_stack[:-HISTORY_LIMIT]
    # Een nieuwe wijziging na een undo maakt "opnieuw doen" zinloos.
    job.redo_stack.clear()
    return step


def clear(job) -> None:
    job.undo_stack.clear()
    job.redo_stack.clear()


def apply_erase(job, x0: int, y0: int, x1: int, y1: int) -> ImageStep:
    rect = clip_rect(job.clean_image, x0, y0, x1, y1)
    # Ook een leeg (helemaal buiten de tekening gevallen) gebied wordt als
    # stap vastgelegd: de browser telt het ook als stap, en beide rijen
    # moeten gelijk blijven lopen.
    patch = job.clean_image.crop(rect) if rect[2] > rect[0] and rect[3] > rect[1] else None
    job.clean_image = erase_rect(job.clean_image, *rect)
    return _record(job, ImageStep(kind="erase", id=_new_id(), rect=rect, patch=patch))


def record_rotate90(job) -> ImageStep:
    """Aanroepen NADAT job.clean_image 90 graden met de klok mee gedraaid is."""
    return _record(job, ImageStep(kind="rotate90", id=_new_id()))


def snapshot_for_rotate_angle(job) -> bytes:
    """Aanroepen VÓÓR een vrije-hoek-draai; geef het resultaat daarna aan
    record_rotate_angle."""
    return _png(job.clean_image)


def record_rotate_angle(job, before_png: bytes) -> ImageStep:
    return _record(job, ImageStep(kind="rotate_angle", id=_new_id(), before_png=before_png))


def _check_top(stack: list[ImageStep], step_id: str) -> ImageStep:
    if not stack or stack[-1].id != step_id:
        raise HistoryMismatch()
    return stack[-1]


def undo(job, step_id: str) -> ImageStep:
    step = _check_top(job.undo_stack, step_id)
    if step.kind == "erase":
        if step.patch is not None:
            job.clean_image.paste(step.patch, step.rect[:2])
    elif step.kind == "rotate90":
        # Exact omgekeerde van ROTATE_270 in rotate_clockwise().
        job.clean_image = job.clean_image.transpose(Image.Transpose.ROTATE_90)
    else:
        if step.after_png is None:
            step.after_png = _png(job.clean_image)
        job.clean_image = _from_png(step.before_png)
    job.redo_stack.append(job.undo_stack.pop())
    return step


def redo(job, step_id: str) -> ImageStep:
    step = _check_top(job.redo_stack, step_id)
    if step.kind == "erase":
        job.clean_image = erase_rect(job.clean_image, *step.rect)
    elif step.kind == "rotate90":
        job.clean_image = job.clean_image.transpose(Image.Transpose.ROTATE_270)
    else:
        job.clean_image = _from_png(step.after_png)
    job.undo_stack.append(job.redo_stack.pop())
    return step
