"""Leest het versienummer van de app (VERSION-bestand in de repo-root, of
naast de exe wanneer gefrozen), zodat de gebruiker in de UI kan zien met
welke build hij werkt - handig om aan te geven welke .exe-release je hebt."""

import sys
from pathlib import Path


def get_version() -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "onbekend"
