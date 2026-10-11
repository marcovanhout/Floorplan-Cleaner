# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-spec voor Floorplan cleaner: bundelt de Flask-webapp +
core-verwerkingslogica tot één Windows .exe.

GEBRUIK
-------
    .venv\\Scripts\\pyinstaller.exe packaging\\floorplan_cleaner.spec --noconfirm

Bekende valkuilen die deze spec afdekt (zie het implementatieplan):
  - PyMuPDF en scipy hebben submodules/binaries die PyInstaller's
    automatische analyse kan missen -> expliciet collect_all/
    collect_submodules.
  - Flask's templates/static zijn geen Python-imports, dus worden niet
    automatisch meegenomen -> expliciete `datas`-entries, opgehaald via
    dezelfde sys._MEIPASS-structuur die create_app() verwacht
    (zie src/webapp/app.py: _webapp_dir()).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH: PyInstaller-global)

# LibreDWG (DWG-ondersteuning) wordt niet gecommit maar opgehaald door
# scripts/fetch_libredwg.py. Zonder die map zou de .exe stilletjes geen DWG
# meer kunnen lezen - dan liever een mislukte build.
LIBREDWG_DIR = PROJECT_ROOT / "vendor" / "libredwg"
for required in ("dwg2dxf.exe", "libredwg-0.dll", "LibreDWG-COPYING.txt"):
    if not (LIBREDWG_DIR / required).is_file():
        raise SystemExit(f"{LIBREDWG_DIR / required} missing - run: python scripts/fetch_libredwg.py")

pymupdf_datas, pymupdf_binaries, pymupdf_hidden = collect_all("pymupdf")
# scipy's OWN test suites (scipy.*.tests.*) komen mee via collect_submodules
# maar zijn nooit nodig at runtime - dat scheelt tientallen MB's aan een
# .exe die toch al numpy/scipy/PyMuPDF meesleept.
scipy_hidden = [m for m in collect_submodules("scipy") if ".tests." not in m and not m.endswith(".tests")]

datas = [
    (str(PROJECT_ROOT / "src" / "webapp" / "templates"), "src/webapp/templates"),
    (str(PROJECT_ROOT / "src" / "webapp" / "static"), "src/webapp/static"),
    (str(PROJECT_ROOT / "VERSION"), "."),
    *pymupdf_datas,
    # Als datas (niet binaries): zo blijven exe + dll samen in één map, waar
    # src/core/dwg.py ze zoekt, i.p.v. door PyInstaller verspreid te worden.
    (str(LIBREDWG_DIR / "dwg2dxf.exe"), "libredwg"),
    (str(LIBREDWG_DIR / "libredwg-0.dll"), "libredwg"),
    (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "licenses"),
    (str(LIBREDWG_DIR / "LibreDWG-COPYING.txt"), "licenses"),
    # ezdxf: lettertype-/lijnstijl-resources.
    *collect_data_files("ezdxf"),
]

hiddenimports = [
    *pymupdf_hidden,
    *scipy_hidden,
    "waitress",
    # ezdxf laadt zijn versnelde (C-)modules en fontTools-tabellen dynamisch.
    *collect_submodules("ezdxf.acc"),
    *collect_submodules("fontTools.ttLib.tables"),
]

a = Analysis(  # noqa: F821
    [str(PROJECT_ROOT / "packaging" / "entry_point.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=pymupdf_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    excludes=["matplotlib", "tkinter", "pytest", "numpy.tests", "scipy.tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FloorplanCleaner",
    console=True,  # zichtbaar consolevenster - geen tray-icon/graceful shutdown in v1
    onefile=True,
    icon=None,
)
