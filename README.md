# Floorplan cleaner

Turns an (AutoCAD-exported) PDF floorplan into a clean PNG (only
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
MODE B (flattened/scanned PDFs without CAD layers) to automatically remove
text; without Tesseract, MODE B still works (color filter +
room detection), you just have to type room names yourself in the
correction step. Install it via the
[Tesseract-OCR Windows installer](https://github.com/UB-Mannheim/tesseract/wiki).

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m src.launcher        # run the webapp locally
.venv\Scripts\pytest tests/                 # test suite
```

Reusable processing logic lives in `src/core/` (independent of Flask/CLI), the
webapp in `src/webapp/`, and the thin CLI wrapper in `src/cli.py`
(`python -m src.cli input.pdf output.png --rooms`).

## Building the .exe yourself

```bash
.venv\Scripts\pyinstaller packaging\floorplan_cleaner.spec --noconfirm
```

Result: `packaging\dist\FloorplanCleaner.exe`. See
`.github\workflows\build-exe.yml` for the automated build on a
GitHub release.

## Important

- **Never commit real customer drawings to this repo** — even though the repo
  is private. Test files in `tests/fixtures/` are exclusively synthetic
  (see `tests/fixtures/generate_fixtures.py`).
- Everything offline: no network calls while processing a PDF.
