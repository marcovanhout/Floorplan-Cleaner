# Floorplan cleaner

Maakt van een (AutoCAD-geëxporteerde) PDF-plattegrond een schone PNG (alleen
muren/deuren/ramen/trappen, zwarte lijnen, transparante achtergrond) en
optioneel losse PNG's per ruimte. Draait volledig lokaal/offline als Windows
desktop-app — geen tekeningdata verlaat de pc. Zie [PROJECT_SPEC.md](PROJECT_SPEC.md)
voor de volledige achtergrond en scope.

## Gebruik (eindgebruiker)

Download `FloorplanCleaner.exe` van de [releases](../../releases) en dubbelklik
'm. Er verschijnt een consolevenster en de app opent in je browser op
`http://127.0.0.1:<poort>`. Laat het consolevenster openstaan zolang je de app
gebruikt; sluiten stopt de server.

**Windows kan bij het eerste starten een SmartScreen-melding tonen**
("Windows heeft de pc beschermd") omdat de .exe niet digitaal ondertekend is.
Kies "Meer info" → "Toch uitvoeren". Dit is een bekende beperking van
ongesigneerde .exe's, geen fout in de app.

**Tesseract-OCR** (optioneel) wordt niet meegeleverd. Die is alleen nodig voor
MODE B (platgeslagen/gescande PDF's zonder CAD-lagen) om automatisch tekst te
verwijderen; zonder Tesseract werkt MODE B nog steeds (kleurfilter +
ruimtedetectie), alleen moet je dan zelf ruimtenamen intypen in de
correctiestap. Installeren kan via de
[Tesseract-OCR Windows-installer](https://github.com/UB-Mannheim/tesseract/wiki).

## Ontwikkelen

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m src.launcher        # start de webapp lokaal
.venv\Scripts\pytest tests/                 # testsuite
```

Herbruikbare verwerkingslogica staat in `src/core/` (los van Flask/CLI), de
webapp in `src/webapp/`, en de dunne CLI-wrapper in `src/cli.py`
(`python -m src.cli input.pdf output.png --rooms`).

## De .exe zelf bouwen

```bash
.venv\Scripts\pyinstaller packaging\floorplan_cleaner.spec --noconfirm
```

Resultaat: `packaging\dist\FloorplanCleaner.exe`. Zie
`.github\workflows\build-exe.yml` voor de geautomatiseerde build bij een
GitHub-release.

## Belangrijk

- **Nooit echte klanttekeningen in deze repo committen** — ook al is de repo
  privé. Testbestanden in `tests/fixtures/` zijn uitsluitend synthetisch
  (zie `tests/fixtures/generate_fixtures.py`).
- Alles offline: geen netwerkcalls tijdens het verwerken van een PDF.
