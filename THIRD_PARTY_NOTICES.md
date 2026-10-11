# Third-party notices

Floorplan Cleaner itself is MIT-licensed (see `LICENSE`). The Windows `.exe`
also contains the third-party components below, each under its own license.

## LibreDWG 0.14 — GPL-3.0-or-later

Used to read DWG files. The `.exe` contains the unmodified programs
`dwg2dxf.exe` and `libredwg-0.dll` from the official LibreDWG 0.14 Windows
build (<https://github.com/LibreDWG/libredwg/releases/tag/0.14>). They run as a
separate program that Floorplan Cleaner starts; they are not linked into it.

- Copyright: Free Software Foundation, Inc. and the LibreDWG contributors
- License: GNU General Public License v3.0 or later — full text below this
  notice in the app's *Licenses* page, and as `LibreDWG-COPYING.txt` with each
  release
- Corresponding source: <https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz>,
  also attached to every Floorplan Cleaner release on GitHub

## Python packages and libraries

| Component | License |
|---|---|
| ezdxf | MIT |
| fontTools | MIT |
| pyparsing | MIT |
| PyMuPDF / MuPDF | AGPL-3.0 |
| Flask, Werkzeug, Jinja2, itsdangerous, click, MarkupSafe | BSD-3-Clause |
| waitress | ZPL-2.1 |
| NumPy, SciPy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| pytesseract | Apache-2.0 |
| typing_extensions | PSF-2.0 |
| Konva.js (browser library) | MIT |
