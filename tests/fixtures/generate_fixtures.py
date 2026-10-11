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


def make_simple_floorplan_dwg(path: str) -> None:
    """Synthetische DWG (R2000, mm): twee ruimtes naast elkaar. Ruimte 1 heeft
    een gewone TEXT-code/naam, ruimte 2 een blok met ATTRIB's (zoals een
    ruimte-label in echte tekeningen). Via ezdxf als DXF geschreven en met
    LibreDWG's dxf2dwg.exe (uit vendor/, zie scripts/fetch_libredwg.py) omgezet."""
    import subprocess
    import tempfile
    from pathlib import Path

    import ezdxf

    dxf2dwg = Path(__file__).resolve().parents[2] / "vendor" / "libredwg" / "dxf2dwg.exe"
    doc = ezdxf.new("R2000", units=4)  # 4 = mm
    for name, color in (("A-WALL", 7), ("A-DOOR", 5), ("A-ANNO-TEXT", 3), ("AREA-FILL", 1)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    # Twee ruimtes van 6 x 5 m met een gedeelde tussenwand.
    for pts in ([(0, 0), (12000, 0), (12000, 5000), (0, 5000)], [(6000, 0), (6000, 5000)]):
        msp.add_lwpolyline(pts, close=len(pts) > 2, dxfattribs={"layer": "A-WALL", "const_width": 200})
    msp.add_arc((2000, 0), radius=900, start_angle=0, end_angle=90, dxfattribs={"layer": "A-DOOR"})

    hatch = msp.add_hatch(color=1, dxfattribs={"layer": "AREA-FILL"})
    hatch.paths.add_polyline_path([(200, 200), (5800, 200), (5800, 4800), (200, 4800)], is_closed=True)

    msp.add_text("TL-1.01", height=250, dxfattribs={"layer": "A-ANNO-TEXT", "insert": (2500, 2800)})
    msp.add_text("Toilet", height=250, dxfattribs={"layer": "A-ANNO-TEXT", "insert": (2500, 2300)})

    tag = doc.blocks.new("ROOMTAG")
    tag.add_attdef("CODE", insert=(0, 250), height=250, dxfattribs={"layer": "A-ANNO-TEXT"})
    tag.add_attdef("NAME", insert=(0, -250), height=250, dxfattribs={"layer": "A-ANNO-TEXT"})
    msp.add_blockref("ROOMTAG", (8500, 2500), dxfattribs={"layer": "A-ANNO-TEXT"}).add_auto_attribs(
        {"CODE": "TL-1.02", "NAME": "Berging"}
    )

    with tempfile.TemporaryDirectory() as tmp:
        dxf = Path(tmp) / "simple_floorplan.dxf"
        doc.saveas(dxf)
        subprocess.run([str(dxf2dwg), "-y", "-o", str(Path(path).resolve()), str(dxf)], check=True,
                       capture_output=True)


if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    make_simple_floorplan(os.path.join(out_dir, "simple_floorplan.pdf"))
    make_simple_floorplan_dwg(os.path.join(out_dir, "simple_floorplan.dwg"))
    print("Fixture(s) gegenereerd in", out_dir)
