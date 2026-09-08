"""Start de lokale webapp: kiest een vrije poort, start Flask via
waitress (niet de Flask dev-server - die breekt in een gefrozen exe,
zie packaging-stap in het implementatieplan), en opent de standaard-
browser.

GEBRUIK
-------
    python -m src.launcher
"""

import socket
import threading
import webbrowser

from waitress import serve

from .webapp.app import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    app = create_app()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    print("=" * 60)
    print("  Plattegrond Schoonmaker")
    print("=" * 60)
    print(f"  Server draait op: {url}")
    print("  Sluit dit venster om de server te stoppen.")
    print()

    threading.Timer(0.75, lambda: webbrowser.open(url)).start()
    serve(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
