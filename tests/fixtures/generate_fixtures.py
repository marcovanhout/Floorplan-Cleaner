"""Genereert de synthetische test-PDF('s) in tests/fixtures/.

Losstaand hulpscript, NIET onderdeel van de pytest-suite zelf - de
gegenereerde PDF wordt gecommit, dit script hoeft dus niet bij elke
testrun te draaien. Herdraaien met:

    python tests/fixtures/generate_fixtures.py

Bevat uitsluitend synthetische data (geen echte klanttekening), veilig
om te committen conform PROJECT_SPEC.md sectie 5.
"""

import os

import pymupdf as fitz


def make_simple_floorplan(path: str) -> None:
    doc = fitz.open()
    # Grote pagina t.o.v. de ruimte zelf, zoals een echte plattegrond met
    # marge/titelblok eromheen - anders wordt het buiten-gebied (de
    # heuristiek "grootste vlak = buitenwereld" in detect_room_boxes) niet
    # de grootste connected component en klopt de ruimtedetectie niet.
    page = doc.new_page(width=2000, height=1500)

    ocg_wall = doc.add_ocg("A-WALL", on=True)
    ocg_door = doc.add_ocg("A-DOOR", on=True)
    ocg_area = doc.add_ocg("AREA-FILL", on=True)  # matcht geen keep-keyword -> hoort UIT te gaan

    # Muren: rechthoekige ruimte-omtrek, klein t.o.v. de pagina.
    room = fitz.Rect(200, 200, 600, 500)
    shape = page.new_shape()
    shape.draw_rect(room)
    shape.finish(color=(0, 0, 0), width=6, fill=None, oc=ocg_wall)
    shape.commit()

    # Deur: klein blokje in de wand (visueel, telt niet mee voor detectie-logica hier).
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(380, 494, 420, 506))
    shape.finish(color=(0.2, 0.2, 0.8), width=2, fill=(0.2, 0.2, 0.8), oc=ocg_door)
    shape.commit()

    # Kleurvlak + ruimtecode/naam-tekst, op een laag die NIET behouden moet blijven.
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(210, 210, 590, 490))
    shape.finish(color=None, fill=(1, 0, 0), fill_opacity=0.3, oc=ocg_area)
    shape.commit()
    # Geen oc= hier: ruimtecode/naam-tekst in echte CAD-exports is niet
    # gekoppeld aan de kleurvlak-laag die wordt uitgezet, en get_text()
    # respecteert OCG-zichtbaarheid (tekst op een uitgezette laag wordt
    # niet geretourneerd) - dus blijft hier bewust ongetagd.
    page.insert_text((350, 330), "TL-1.01", fontsize=10)
    page.insert_text((350, 350), "Toilet", fontsize=10)

    doc.save(path)
    doc.close()

    # Layer-UI-configuratie van MuPDF wordt pas volledig opgebouwd na een
    # verse document-open (zie onderzoek tijdens de v2-poort) - heropenen
    # en overschrijven zodat de fixture meteen bruikbaar is zonder die stap
    # telkens opnieuw te hoeven doen.
    doc2 = fitz.open(path)
    assert len(doc2.layer_ui_configs()) == 3, "fixture: layer UI config niet volledig opgebouwd"
    doc2.close()


if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    make_simple_floorplan(os.path.join(out_dir, "simple_floorplan.pdf"))
    print("Fixture(s) gegenereerd in", out_dir)
