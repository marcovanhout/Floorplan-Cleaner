# Route 1-spike: bevindingen

Zie `PROJECT_SPEC.md` sectie 4 en `route1_area_layer_spike.py` voor achtergrond/methode.
Gedraaid tegen één lokaal testbestand (nooit gecommit); onderstaande bevat geen
ruimtegeometrie of andere klantspecifieke inhoud, alleen de generieke conclusie.

## Conclusie: Route 1 levert hier niets op — gesloten

De kandidaat-laag (AutoCAD-exportpatroon `A-AREA`, met een aparte `A-AREA-IDEN`
labellaag) bleek bij onderzoek **geen bruikbare per-ruimte polygoondata** te
bevatten:

- `A-AREA` bevat slechts een handvol (~7) losse, gedegenereerde lijnfragmentjes
  (geen gesloten polygonen, geen rechthoek-primitieven) — vermoedelijk restjes/
  snap-markeringen, geen ruimte-omtrekken.
- `A-AREA-IDEN` bevat alleen vector-getekende glyph-lijnen van labeltekst
  (ruimtecodes/namen als tekentekens, niet als polygoongeometrie).
- Zowel de per-laag gefilterde `page.get_drawings()`-analyse als de geïsoleerde
  force-render (±1% zichtbare pixels, 1 unieke kleur) bevestigen dit.

**Besluit conform het plan (decision gate):** flood-fill (`src/core/rooms.py`)
blijft de aanpak voor ruimtedetectie. Route 1 wordt niet verder opgevolgd voor
dit brontype/deze CAD-exportstijl. Route 2 (deur-bewuste vloeivulling, zie
spec sectie 4) blijft zoals gepland uitgesteld.

Deze conclusie is specifiek voor het geteste bestand/de geteste CAD-export-
workflow; bij een heel andere klant-/CAD-bron kan het analysescript opnieuw
gedraaid worden (`python scripts/spikes/route1_area_layer_spike.py <pdf>`).
