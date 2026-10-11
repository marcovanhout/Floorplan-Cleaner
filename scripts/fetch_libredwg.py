"""Download the pinned LibreDWG release into vendor/libredwg/.

Used by CI before building the .exe and by developers once after cloning.
Binaries are never committed; they are fetched here and checked against a
fixed SHA-256 so a build can only ever contain this exact version.

    python scripts/fetch_libredwg.py
"""

import hashlib
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.14"
BIN_URL = f"https://github.com/LibreDWG/libredwg/releases/download/{VERSION}/libredwg-{VERSION}-win64.zip"
BIN_SHA256 = "1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8"
SRC_URL = f"https://ftp.gnu.org/gnu/libredwg/libredwg-{VERSION}.tar.xz"
SRC_SHA256 = "62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275"

# dwg2dxf.exe only imports libredwg-0.dll (plus Windows system DLLs).
# dxf2dwg.exe is only used to generate the test fixture, not shipped.
BIN_FILES = ("dwg2dxf.exe", "dxf2dwg.exe", "libredwg-0.dll")

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "vendor" / "libredwg"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected_sha: str) -> None:
    if dest.is_file() and sha256(dest) == expected_sha:
        print(f"  cached  {dest.name}")
        return
    print(f"  fetch   {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    actual = sha256(tmp)
    if actual != expected_sha:
        tmp.unlink()
        sys.exit(f"SHA-256 mismatch for {url}\n  expected {expected_sha}\n  got      {actual}")
    tmp.replace(dest)


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"LibreDWG {VERSION} -> {TARGET}")

    bin_zip = TARGET / f"libredwg-{VERSION}-win64.zip"
    src_tar = TARGET / f"libredwg-{VERSION}.tar.xz"
    download(BIN_URL, bin_zip, BIN_SHA256)
    download(SRC_URL, src_tar, SRC_SHA256)

    with zipfile.ZipFile(bin_zip) as zf:
        for name in BIN_FILES:
            with zf.open(name) as src, (TARGET / name).open("wb") as dst:
                shutil.copyfileobj(src, dst)

    with tarfile.open(src_tar, "r:xz") as tf:
        member = tf.getmember(f"libredwg-{VERSION}/COPYING")
        with tf.extractfile(member) as src, (TARGET / "LibreDWG-COPYING.txt").open("wb") as dst:
            shutil.copyfileobj(src, dst)

    print("  ok      " + ", ".join(BIN_FILES + ("LibreDWG-COPYING.txt",)))


if __name__ == "__main__":
    main()
