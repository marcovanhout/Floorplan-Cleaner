"""In-memory job-state voor de lokale, single-user Flask-app.

Geen database/auth/queue nodig: één proces, één gebruiker, tijdelijke
mappen per upload. State leeft zolang het serverproces draait.
"""

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from src.core.types import AnchorLogEntry, RoomRecord
from PIL import Image


@dataclass
class JobState:
    job_id: str
    tmp_dir: Path
    pdf_path: Path
    pdf_original_name: str
    page_no: int = 0
    scale: float = 4.0
    mode_a: bool = True
    clean_image: Image.Image | None = None
    rooms: list[RoomRecord] = field(default_factory=list)
    anchor_log: list[AnchorLogEntry] = field(default_factory=list)
    export_zip_path: Path | None = None


JOBS: dict[str, JobState] = {}


def create_job(pdf_bytes: bytes, original_name: str) -> JobState:
    tmp_dir = Path(tempfile.mkdtemp(prefix="floorplan_"))
    job_id = uuid.uuid4().hex
    pdf_path = tmp_dir / "input.pdf"
    pdf_path.write_bytes(pdf_bytes)
    job = JobState(job_id=job_id, tmp_dir=tmp_dir, pdf_path=pdf_path, pdf_original_name=original_name)
    JOBS[job_id] = job
    return job


def get_job(job_id: str) -> JobState | None:
    return JOBS.get(job_id)


def cleanup_job(job_id: str) -> None:
    job = JOBS.pop(job_id, None)
    if job is not None:
        shutil.rmtree(job.tmp_dir, ignore_errors=True)
