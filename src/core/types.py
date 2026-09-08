"""Gedeelde datastructuren tussen core-pipeline, CLI en webapp."""

from dataclasses import dataclass, field
from typing import Literal

from PIL import Image

RoomSource = Literal["auto", "user-edited", "user-new", "user-merged"]


@dataclass
class CleanResult:
    """Resultaat van het opschonen van een plattegrond-pagina."""

    image: Image.Image  # RGBA, transparante achtergrond, zwarte lijnen
    mode_a: bool  # True = CAD-lagen gebruikt, False = raster/OCR-fallback
    kept_layers: list[str] = field(default_factory=list)
    dropped_layers: list[str] = field(default_factory=list)
    ocr_boxes: list[tuple[int, int, int, int, str]] = field(default_factory=list)


@dataclass
class RoomRecord:
    """Eén ruimte-vak, in afbeeldingspixel-coördinaten.

    Dit is de vaste vorm die tussen detectie -> correctie-canvas (JSON) ->
    export gaat. Losgekoppeld van de interne scipy-ndimage-label-ids, zodat
    door de gebruiker samengevoegde/nieuw getekende/verwijderde vakken na
    correctie probleemloos naar export kunnen.
    """

    id: str
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1)
    name: str | None
    source: RoomSource = "auto"


@dataclass
class AnchorLogEntry:
    """Eén ruimtecode/naam zoals gevonden in de PDF-tekst, met koppelinfo.

    Gebruikt om na afloop te rapporteren welke in de tekening gevonden
    ruimtenamen GEEN eigen vak/PNG kregen, en waarom.
    """

    code: str
    name: str | None
    room_id: str | None
    direct_hit: bool = False
    suppressed: bool = False


@dataclass
class DetectionResult:
    """Resultaat van automatische ruimtedetectie op een CleanResult."""

    rooms: list[RoomRecord]
    anchor_log: list[AnchorLogEntry] = field(default_factory=list)
    mode_a: bool = True


@dataclass
class ExportResult:
    """Resultaat van het exporteren van losse ruimte-PNG's + logbestand."""

    out_dir: str
    filenames: dict[str, str]  # room.id -> bestandsnaam
    log_path: str
