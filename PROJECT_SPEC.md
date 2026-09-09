# Floorplan cleaner (v2) — Projectspecificatie

Dit document is een startpunt voor een Claude Code-sessie waarin deze tool
opnieuw wordt opgebouwd als een volwaardige, offline desktoptool met een
eigen GitHub-repo, i.p.v. losse scripts. Het vat samen wat er al is gebouwd
en getest, wat er nu bij moet, en welke open vragen eerst uitgezocht moeten
worden.

---

## 1. Wat de tool doet

Input: een PDF-plattegrond (meestal een AutoCAD-export, bv. vanuit een
Revit/AutoCAD-workflow, met reinheidsklasse/GMP-kleurvlakken, tekst,
maatvoering en een titelblok).

Output:
1. Eén schone PNG van de hele plattegrond: alleen muren, deuren, ramen en
   trappen, alle lijnen zuiver zwart, transparante achtergrond, géén
   kleurvlakken, tekst, maatvoering, legenda of titelblok.
2. Optioneel: een losse PNG per ruimte (met ruime marge, zodat de
   deuren/ramen in de omringende muur volledig zichtbaar zijn), genoemd
   naar de herkende ruimtenaam. Dubbele namen krijgen een volgnummer
   (`toilet_1.png`, `toilet_2.png`, ...).
3. Een leesbaar logbestand (`_log.txt`) naast de losse ruimte-PNG's, met:
   - welke PNG's zijn aangemaakt en met welke ruimtenaam,
   - welke ruimtenamen wél in de tekening zijn gevonden maar GEEN eigen
     PNG kregen, met reden (echte samenvoeging vs. onzekere gok).

Gebruikers: interne collega's, wisselende PDF-kwaliteit per klant
(sommige met nette CAD-lagen, sommige platgeslagen/gescand).

---

## 2. Wat er al gebouwd en getest is (v1, los script)

Bestaand werkend prototype: `floorplan_cleaner.py` (Python, PyMuPDF/fitz +
numpy + Pillow + scipy + pytesseract), plus een Windows `.bat`-launcher
met PowerShell-hulpscripts voor bestandskeuze en installatie. Dit werkt,
maar is bedoeld als vertrekpunt, niet als eindarchitectuur.

### 2.1 MODE A — PDF heeft nog CAD-lagen (OCG's)

De meeste AutoCAD-PDF-exports bevatten nog de originele tekenlagen
(bv. `A-WALL`, `A-DOOR`, `A-GLAZ`, `S-STRS-MBND`, maar ook
kleurvlak-lagen als `07_00-E RHK_Grade A_ISO-5` en teksten-lagen als
`A-AREA-IDEN`). Aanpak:
- Detecteer alle lagen via `doc.get_ocgs()` / `doc.layer_ui_configs()`.
- Zet alleen lagen aan die matchen met keywoorden voor muur/deur/raam/trap
  (`A-WALL`, `A-DOOR`, `A-GLAZ`, `S-STRS`, plus Nederlandse varianten
  MUUR/DEUR/RAAM/TRAP als vangnet); zet de rest uit
  (`set_layer_ui_config(naam, action=0|2)`).
- Render de pagina (PyMuPDF `get_pixmap`), forceer daarna alle
  overgebleven pixels naar zuiver zwart op basis van helderheid
  (composite op wit, invert naar alphakanaal) — dit verwijdert restjes
  gekleurde lijnen die op een "verkeerde" CAD-laagkleur stonden
  (bv. paarse binnenwanden).

Dit werkt betrouwbaar en scherp — dit deel hoeft niet opnieuw ontworpen
te worden, alleen overgenomen/verbeterd.

### 2.2 MODE B — geen bruikbare lagen (platgeslagen/gescande PDF)

Fallback: kleurvlakken wegfilteren op HSV-kleurverzadiging, tekst
detecteren en verwijderen met OCR (`pytesseract`). **Inmiddels getest en
gevalideerd op een echt "slecht" voorbeeldbestand** (platte PDF zonder
CAD-lagen, tijdens de v2-rebuild). Daarbij drie concrete verbeteringen
doorgevoerd t.o.v. het oorspronkelijke v1-prototype:
- Contrast van de opgeschoonde lijnen was te laag (anti-aliased randen
  kregen een bijna-transparante dekking) → nu een harde zwart/transparant-
  drempel i.p.v. een lineaire alphawaarde.
- Tesseract wordt ook gevonden als de Windows-installer zichzelf niet aan
  PATH heeft toegevoegd (bekende installer-eigenaardigheid) — valt terug op
  de gebruikelijke installatielocatie.
- Tekstherkenning gebeurt nu in alle 4 rotaties (0/90/180/270 graden),
  niet alleen horizontaal — ruimtenamen in een scheve/gedraaide plattegrond
  werden anders helemaal niet gevonden.

Blijvende, geaccepteerde beperking: OCR is en blijft minder betrouwbaar dan
echte PDF-tekst (zie 2.3) en mist soms losse woorden of leest ruis
(arcering e.d.) als tekst — vandaar geen "niet-gekoppelde naam"-waarschuwing
voor MODE B zoals MODE A die wel heeft (zie 3.3): dat zou vooral ruis
toevoegen. Stramienlijnen (bouwkundige rasterlijnen) worden bewust niet
automatisch verwijderd: bij een platte PDF is een stramienlijn niet te
onderscheiden van een muur, en het risico op per ongeluk weggehaalde muren
weegt zwaarder dan het cosmetische voordeel.

### 2.3 Ruimtedetectie (het onderdeel dat nog niet goed genoeg is)

Huidige aanpak: vloeivulling (flood-fill / connected components via
`scipy.ndimage`) op de schone lijntekening, met een gedilateerd
muur-masker om kleine hiaten (gestreepte lijnen, deurspleten) te
overbruggen. Ruimtenamen komen uit de echte PDF-tekstlaag (nauwkeuriger
dan OCR) en worden gekoppeld aan het dichtstbijzijnde gedetecteerde vlak
via een euclidische afstandstransformatie.

**Bekende beperking, expliciet besproken en geaccepteerd voor v1:**
ruimtes zonder volledige scheidingsmuur (open verbindingen, sommige
kleine ruimtes/deurspleten) vloeien samen tot één groter vlak, of vallen
onder de minimumgrootte-drempel. Op het geteste voorbeeldbestand werd
~13 van de ~30 fysieke ruimtes apart correct herkend. Zie sectie 4 voor
verbetersporen.

---

## 3. Scope voor v2 (deze rebuild)

### 3.1 Moet-haves
- Zelfde kernfunctionaliteit als v1 (secties 2.1–2.3), overgenomen/
  gerefactored, niet opnieuw uitgevonden.
- **Lokale, offline UI** — geen data verlaat de pc, geen API-calls naar
  externe diensten (bewust gekozen, zie gespreksverloop: privacy van
  klanttekeningen weegt zwaarder dan de mogelijke kwaliteitswinst van
  een taalmodel-in-de-loop).
- **Visuele controle- en correctiestap** vóór het exporteren van losse
  ruimte-PNG's (zie 3.3) — dit is de belangrijkste UX-toevoeging t.o.v.
  v1, en de meest realistische manier om een hoge effectieve
  nauwkeurigheid te halen zonder een 90%-garantie op de automatische
  detectie zelf te moeten waarmaken.
- **Eén-bestand Windows-installatie** (bv. via PyInstaller): geen
  Python/pip/tesseract-installatie meer nodig voor eindgebruikers.

### 3.2 Voorgestelde architectuur
- **Type applicatie:** lokale web-app (bv. Flask of Streamlit) die opent
  in de standaardbrowser op `localhost`, i.p.v. een los desktop-GUI-
  framework (tkinter/PySimpleGUI). Reden: sneller te bouwen, bekender
  voor gebruikers, en de benodigde interacties (slepen, klikken op
  vakken, tekst aanpassen) zijn in een browser prima te bouwen.
- **Verwerkingslogica:** blijft Python, hergebruik van de bestaande
  functies uit `floorplan_cleaner.py` (layer-filtering, black-line
  normalisatie, room-detectie, naam-matching, logging) — verplaatsen
  naar een nette module-structuur, niet herschrijven vanaf nul.
- **Packaging:** PyInstaller (of vergelijkbaar) naar een enkele `.exe`;
  GitHub Actions-workflow om deze automatisch te bouwen bij een release.

### 3.3 De controle-/correctiestap (kernonderdeel van de UX)
Voorgesteld interactiemodel na de automatische detectie:
1. Toon de schone plattegrond met alle gedetecteerde ruimte-vakken erover
   getekend (rechthoeken + herkende naam, zoals in de debug-visualisaties
   die tijdens de v1-ontwikkeling zijn gebruikt).
2. Gebruiker kan per vak:
   - de naam corrigeren/intypen,
   - het vak verslepen/vergroten/verkleinen,
   - twee vakken samenvoegen,
   - een gemist vak zelf intekenen,
   - een vak negeren/verwijderen.
3. Pas na akkoord: losse PNG's + logbestand exporteren.

Dit verschuift het probleem van "moet automatisch >90% kloppen" naar
"moet in een paar klikken te corrigeren zijn" — haalbaarder en sneller
voor gebruikers dan nu handmatig missende ruimtes zoeken/bijsnijden in
Paint.

### 3.4 Nice-to-haves / later
- Verbeterde automatische detectie (zie route's in sectie 4) — kan
  parallel of ná de UI-versie, vermindert het aantal handmatige correcties
  maar is geen blocker voor v2-lancering.
- Batchverwerking van meerdere PDF's achter elkaar.
- Optie om een eigen keyword-lijst voor lagen op te slaan per klant/project.

---

## 4. Open technisch spoor: betere automatische ruimtedetectie

Niet gebouwd, wel besproken — als losse vervolgstap, onafhankelijk van de
UI-rebuild:

**Route 1 (hoogste potentiële winst, eerst uitzoeken):** controleren of
de PDF al een exacte, onzichtbare ruimte-polygoon per kamer bevat (zoals
CAD-software vaak genereert voor oppervlakteberekening — in dit
testbestand heette de kandidaat-laag `A-AREA`, maar leverde bij een
eerste render geen zichtbare vulling op; dat sluit niet uit dat de
vlakdata er wél zit, alleen onzichtbaar getekend). Als dit werkt: geen
giswerk meer nodig voor de vlakgrenzen zelf.

**Route 2:** deur-bewuste vloeivulling — de exacte locatie/breedte van
elke deuropening (al bekend uit de deurenlaag) gebruiken om gericht de
muur virtueel te sluiten, i.p.v. een vaste dilatatie-marge overal
toe te passen. Werkt op elke tekening, geen afhankelijkheid van een
specifieke CAD-laag.

**Expliciet niet gekozen:** een taalmodel-API (Claude) laten meekijken
naar elke ruimte-uitsnede om de naam te herkennen. Zou waarschijnlijk de
naam-koppeling robuuster maken (minder gevoelig voor rare hoeken/kleine
tekst dan de huidige wiskundige dichtstbijzijnde-punt-matching), maar is
bewust afgewezen omdat het (a) een internetverbinding vereist, (b)
tekeninggegevens buiten de deur brengt, en (c) een API-sleutel + lopende
kosten met zich meebrengt — voor deze klantgevoelige tekeningen weegt dat
niet op tegen de kwaliteitswinst.

---

## 5. Niet-functionele eisen

- **Alles offline**: geen enkele netwerkcall tijdens verwerking.
- **Geen echte klanttekeningen in de repo**: gebruik voor tests
  bewerkte/nagemaakte voorbeeldbestanden, nooit echte Zuyderland- (of
  andere klant-) PDF's, voor het geval de repo ooit gedeeld wordt.
- **Repo privé** houden.
- Windows 10/11 als primair doelplatform; geen aannames over macOS/Linux
  nodig voor v1 van de rebuild.

---

## 6. Voorgestelde repo-structuur

```
/src
  /core           - herbruikte verwerkingslogica (layers, black-line
                    normalisatie, room-detectie, naam-matching, logging)
  /webapp         - lokale UI-laag (Flask/Streamlit), incl. de
                    controle-/correctiestap uit 3.3
/tests
  /fixtures       - alleen bewerkte/synthetische voorbeeld-PDF's
/packaging        - PyInstaller-config
/.github/workflows - build .exe bij release
README.md
PROJECT_SPEC.md   - dit document
```

---

## 7. Vragen om bij de start van de Claude Code-sessie te beantwoorden

1. Flask of Streamlit (of iets anders) voor de lokale UI-laag?
2. Hoe wordt de correctiestap precies bediend — canvas met sleepbare
   rechthoeken (bv. via een JS-canvaslaag), of eenvoudiger met een lijst
   + coördinaatvelden?
3. Welke minimale Windows-versie/Python-runtime-bundeling geeft de
   kleinste/robuustste `.exe`?
4. Wordt Route 1 (sectie 4) meteen meegenomen in v2, of pas na de eerste
   werkende UI-versie?
