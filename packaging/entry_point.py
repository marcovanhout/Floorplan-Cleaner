"""PyInstaller-startpunt: los bestand i.p.v. `python -m src.launcher`, zodat
PyInstaller's analyse een gewoon top-level script heeft om te volgen."""

from src.launcher import main

if __name__ == "__main__":
    main()
