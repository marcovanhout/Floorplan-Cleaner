# Floorplan cleaner

Turns a floorplan — an (AutoCAD-exported) PDF or a DWG file — into a clean PNG (only
walls/doors/windows/stairs, pure black lines, transparent background) and
optionally separate PNGs per room. Runs entirely locally/offline as a Windows
desktop app — no drawing data leaves the PC. See [PROJECT_SPEC.md](PROJECT_SPEC.md)
for the full background and scope.

## Usage (end user)

Download `FloorplanCleaner.exe` from the [releases](../../releases) and double-click
it. A console window appears and the app opens in your browser at
`http://127.0.0.1:<port>`. Leave the console window open while you use the app;
closing it stops the server.

**Windows may show a SmartScreen warning on first launch**
("Windows protected your PC") because the .exe isn't digitally signed.
Choose "More info" → "Run anyway". This is a known limitation of
unsigned .exe's, not a bug in the app.

**Tesseract-OCR** (optional) is not bundled. It's only needed for
image-based cleaning (flattened/scanned PDFs without CAD layers) to
automatically remove text; without Tesseract, image-based cleaning still
works (color filter + room detection), you just have to type room names
yourself in the correction step. Install it via the
[Tesseract-OCR Windows installer](https://github.com/UB-Mannheim/tesseract/wiki).
When Tesseract is installed, the upload page shows a checkbox to turn
automatic text removal off (e.g. for faster processing).

**DWG files** can be uploaded directly. The app converts them to a PDF with
their CAD layers (using the bundled [LibreDWG](https://www.gnu.org/software/libredwg/)),
after which everything works as for a PDF. A large drawing can take up to
half a minute to convert. Drawings that refer to other drawing files
(external references) miss those parts — upload a drawing with the references
bound, or export it to PDF instead.

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python scriptsetch_libredwg.py   # LibreDWG for DWG support (not committed)
.venv\Scripts\python -m src.launcher        # run the webapp locally
.venv\Scripts\pytest tests/                 # test suite
```

Reusable processing logic lives in `src/core/` (independent of Flask/CLI), the
webapp in `src/webapp/`, and the thin CLI wrapper in `src/cli.py`
(`python -m src.cli input.pdf output.png --rooms`; a `.dwg` works too).
DWG conversion lives in `src/core/dwg.py` and `src/core/dwg_pdf_backend.py`.

## Building the .exe yourself

```bash
.venv\Scripts\pyinstaller packaging\floorplan_cleaner.spec --noconfirm
```

Requires `scriptsetch_libredwg.py` to have run first (the build stops if
LibreDWG is missing). Result: `packaging\dist\FloorplanCleaner.exe`. See
`.github\workflows\build-exe.yml` for the automated build on a
GitHub release.

## Important

- **Never commit real customer drawings to this repo** — the repo is public.
  Also keep customer, project and employer names and drawing numbers out of
  code, tests and docs. Test files in `tests/fixtures/` are exclusively synthetic
  (see `tests/fixtures/generate_fixtures.py`).
- Everything offline: no network calls while processing a PDF or DWG.

## License

[MIT](LICENSE). The .exe also bundles third-party components under their own
licenses, including LibreDWG (GPL-3.0-or-later) — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the *Licenses* link in the app.
