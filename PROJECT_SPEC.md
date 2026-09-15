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

**Nadien gecorrigeerd:** het alphakanaal werd aanvankelijk geleidelijk
gezet op basis van helderheid (een lichtgrijze/anti-aliased pixel werd
een bijna-doorzichtige pixel) i.p.v. hard aan/uit. In de correctiestap
(tegen een witte achtergrond getoond) viel dat niet op, maar in de
geëxporteerde PNG (echte transparantie) waren dunne CAD-lijnen daardoor
nauwelijks zichtbaar — pas gevonden nadat een gebruiker dit zelf moest
oplossen door in een beeldbewerkingsprogramma de transparantiedrempel te
verlagen. Opgelost door dezelfde harde zwart/transparant-drempel te
gebruiken die MODE B (zie 2.2) al had: elke zichtbare pixel wordt nu
volledig ondoorzichtig zwart, of volledig transparant, geen
tussenwaarden meer.

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

**Inmiddels gebouwd** (breder dan hier oorspronkelijk gepland): naast
slepen/vergroten/verkleinen/samenvoegen/intekenen/verwijderen van losse
vakken kan de gebruiker nu ook met Ctrl ingedrukt een selectievak over
meerdere vakken tegelijk slepen om ze in één keer te verwijderen
("spookvakjes" bij een rommelige detectie zijn zo snel op te ruimen). De
plattegrond kan zowel per 90 graden als op een volledig vrije hoek
gedraaid worden (rechtzetten van een scheef ingescande tekening); bij een
vrije hoek blijven ruimte-vakken zelf axis-aligned (een iets ruimere
uitsnede dan de werkelijke ruimte, bewust geaccepteerd i.p.v. overal
schuine rechthoeken te ondersteunen). Er is een terug-knop naar de
startpagina (met bevestiging bij niet-geëxporteerde wijzigingen). De hele
tool (UI, foutmeldingen, logbestand, CLI) is inmiddels in het Engels
vertaald, zodat ook niet-Nederlandstalige collega's de tool kunnen
gebruiken.

**Verder uitgebreid (na de eerste versie van de correctiestap):** een
"Erase"-knop waarmee je een rechthoek over de tekening sleept om een
stukje (bv. tekst die de automatische opschoning liet staan) handmatig
permanent weg te vlakken - er was voorheen geen manier om de
onderliggende afbeelding zelf te corrigeren, alleen de ruimte-vakken
erover. Daarnaast een "Undo"-knop die de allerlaatste wijziging
terugdraait (bewust maar 1 stap diep, geen verdere geschiedenis of
redo - dekt de praktische "oeps"-situatie zonder de complexiteit van een
volledige undo/redo-geschiedenis); bij ruimte-vak-wijzigingen gebeurt dit
direct client-side, bij roteren/gummen (die de afbeelding zelf aanpassen)
via een korte serverronde, met behoud van het huidige zoomniveau tenzij
de afbeeldingsafmetingen ook echt veranderd zijn.

Ook is een bug in de opschoning van platte/gescande PDF's (MODE B)
gevonden en verholpen: dunne lijnen (zoals een deurzwaai) die over een
gekleurd classificatievlak (bv. een GMP-kleurcode) getekend staan, werden
per ongeluk meegeveegd met de kleurverwijdering, waardoor complete deuren
uit het eindresultaat konden verdwijnen. Opgelost door elke pixel te
vergelijken met de mediaan-helderheid van zijn directe omgeving in plaats
van een vaste helderheidsgrens te gebruiken (zie de toelichting in
`src/core/raster.py` voor de precieze onderbouwing) — een vaste grens
bleek niet betrouwbaar genoeg, omdat lijngewicht en vlakkleur te veel
verschillen per klantbestand.

Verder kan automatische tekstverwijdering (OCR) nu per verwerking
aan/uitgezet worden (alleen zichtbaar als Tesseract geïnstalleerd is) -
kost tijd en is niet altijd gewenst. En de eerder gebruikte, nergens
toegelichte labels "MODE A"/"MODE B" zijn overal waar de gebruiker ze kon
zien vervangen door een duidelijke omschrijving van wat er daadwerkelijk
gebeurt (CAD-lagen vs. beeldherkenning).

Ook een tweede, verwante bug in MODE B verholpen: platte PDF's die
classificatiezones (temperatuur-, drukzones e.d.) aanduiden via een
gekleurde ARCERING (streeppatroon) i.p.v. een vlakke kleur leverden een
zwarte lijnenbrij op, omdat diezelfde deur-beschermingslogica hierboven
arceringslijnen ten onrechte als echte lijntekening zag (een arceringslijn
kan in zijn dunne kern net zo donker renderen als een deurlijn). Opgelost
door een donkere pixel alleen nog als beschermde lijn te tellen als zijn
kleurzweem overeenkomt met die van zijn omgeving — een deurlijn neemt de
kleur van het vlak eronder over, een arceringslijn heeft een eigen kleur
die niet bij zijn (meestal witte) omgeving hoort. Zie de toelichting in
`src/core/raster.py` (`_colored_mask`) voor de volledige onderbouwing,
inclusief twee vervolgfixes op ditzelfde probleem (kruispunten in een
dichte kruisarcering, en het anti-aliasing-randje van een arceringslijn).

**Bekende, geaccepteerde beperking hierbij:** voor dit soort platte
classificatieschema's (geen echte plattegrond, dus zonder betekenisvolle
"kamers") vindt de ruimtedetectie (zie 2.3) soms tientallen valse
ruimtes — elk klein, door arceringslijnen omsloten vlak binnen zo'n zone
telt technisch mee als "omsloten wit gebied". Bewust niet opgelost met een
grotere afmetingsdrempel: dat zou het risico vergroten dat een echt klein
kamertje in een NORMALE plattegrond stilzwijgend gemist wordt, en dat
weegt zwaarder dan wat extra, goed zichtbare (en dus makkelijk handmatig
te verwijderen) ruis bij dit randgeval. Voor dit bestandstype is vooral de
opgeschoonde totaalplaat (die exporteert de tool sowieso altijd mee)
bruikbaar, niet de automatische opsplitsing in losse kamers.

**Nog drie correctiestap-verbeteringen:** "Samenvoegen" werkte tot nu toe
alleen voor precies 2 vakken tegelijk; dat werkt nu voor 2 of meer. Direct
bruikbaar voor de bekende beperking hierboven: een deur die per ongeluk
als eigen "ruimte" gedetecteerd wordt, kun je nu in één keer samen met de
bijbehorende kamer (en eventuele andere losse deurvakjes) selecteren en
samenvoegen, zonder automatisch te hoeven raden welke vlakken "eigenlijk"
bij elkaar horen. Losse vakjes aanklikken/selecteren voor multi-select
gebeurt nu met Ctrl ingedrukt i.p.v. Shift (zowel bij los aanklikken als
bij het selectiekader slepen) - sluit aan bij de Windows-conventie
(Verkenner e.d.) waar de gebruiker al aan gewend is. Tot slot toont de
statustekst tijdens het verwerken nu een oplopende tijdsduur ("Processing...
(Ns)") - bij een groot/gescand bestand kan dat meer dan een minuut duren,
en zonder teken van leven leek de pagina dan vastgelopen.

**Naamloze ruimtes krijgen nu al bij detectie een oplopende naam**
("room_01", "room_02", enz.) in plaats van "(no name)" te tonen totdat pas
bij export een volgnummer verzonnen werd - onmogelijk om in de correctie-
stap te zien welk vakje straks welk bestand zou worden. Bewust geen "raad
de naam uit de dichtstbijzijnde tekst"-terugval toegevoegd (bv. bij een
PDF met CAD-lagen maar zonder de gebruikelijke ruimtecode-conventie, zie
2.3): op zo'n bestand staat vaak net zoveel niet-naam-tekst (druk-/
ventilatiewaarden, GMP-classificaties, maatvoering) als echte namen, en
een verkeerd geraden naam is misleidender dan een neutraal volgnummer.
"room_01" is nu een ECHTE naam (geen speciaal geval meer) - komt dus
vanaf het begin al overeen met de uiteindelijke bestandsnaam, ook zonder
dat de gebruiker er iets aan hoeft te doen. Exportlogica in export.py
tegelijk aangepast: een botsing tussen zo'n al-toegekende naam en de
terugvalnaam van een later nog naamloos vak (bv. een handmatig getekend
vakje) krijgt nu netjes de bestaande "_1/_2"-suffix i.p.v. dat het ene
bestand het andere stilzwijgend overschrijft.

**Marge bij export: per aangrenzende deur i.p.v. één vaste waarde voor de
hele ruimte.** Eerst geprobeerd met een vaste marge (als percentage van
de ruimte-afmeting, later als vaste schaal-bewuste ondergrens) groot
genoeg voor de breedst uitstekende deur op het hele bestand — bleek altijd
een verkeerde afweging: groot genoeg voor de lastigste deur is overdreven
ruim voor de meeste andere kanten (ook lege), klein genoeg om er strak
uit te zien sneed elders weer deuren af. Nu wordt per kant van een ruimte
gekeken of er een echt deur-vormig vakje aangrenzend ligt, en alleen díe
kant wordt uitgebreid tot voorbij dat vakje — een lege kant blijft strak.
"Deur-vormig" wordt per tekening opnieuw bepaald (niet een vast getal):
gezocht wordt naar de natuurlijke kloof in de gevonden vakgroottes van
díe specifieke tekening. Een simpelere aanpak (kleiner dan een vast
percentage van de MEDIAAN-vakgrootte) bleek te falen zodra een tekening
meer deur- dan kamer-vakken heeft (bv. een gang met veel kleine kamers) —
dan valt de mediaan zelf al middenin de deur-vakjes.

Bewust geen automatische oplossing gebouwd voor een deur die tussen twee
ruimtes in ligt en dus bij beide zou moeten horen (zie 2.3-achtige
afweging): elke geopperde automatische aanpak (grootste/kleinste vak
als kamer/deur aannemen, kleine vakjes automatisch meezuigen bij een
grotere buur) had een reëel risico om het verkeerd te doen op een net
iets ander bestand (bv. een wc-formaat ruimte, of meerdere kleine
ruimtes naast een grote die er NIET bij horen). Blijft dus een
handmatige stap via "Merge" (zie hierboven).

**Export en downloadknop staan niet meer in de werkbalk maar op hun
eigen regel direct onder het correctievenster.** Ze stonden eerst in de
(smalle, met veel knoppen al gevulde) werkbalk; zodra de downloadknop na
de eerste export verscheen werd de werkbalk net te breed en sprongen de
knoppen naar een tweede regel. Op hun eigen regel onder het canvas is
nooit ruimtegebrek. De downloadknop dimt bovendien zodra er ná de laatste
export nog iets gewijzigd is (hergebruikt de bestaande "niet-opgeslagen
wijzigingen"-registratie die ook de "Terug"-waarschuwing al gebruikte) -
blijft wel gewoon klikbaar, maar zo is in één oogopslag te zien of het
gedownloade bestand nog actueel is.

### 3.4 Nice-to-haves / later
- Verbeterde automatische detectie (zie route's in sectie 4) — kan
  parallel of ná de UI-versie, vermindert het aantal handmatige correcties
  maar is geen blocker voor v2-lancering.
- Batchverwerking van meerdere PDF's achter elkaar.

**Inmiddels gebouwd (was hier oorspronkelijk als idee genoteerd, maar
anders opgelost dan gepland):** een eigen, op te slaan keyword-lijst per
klant/project bleek niet nodig — elke tekenaar noemt lagen anders, dus een
lijst zou toch nooit compleet zijn. In plaats daarvan kiest de gebruiker nu
zelf, per upload, welke CAD-lagen meegenomen worden (met de laagnamen zelf
zichtbaar, een op keywoorden gebaseerd voorstel vooraf aangevinkt, en een
live, zoombaar/panbaar voorbeeld) — preciezer dan een keyword-lijst en
zonder dat de gebruiker technische zoektermen hoeft te begrijpen.

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

**Inmiddels allemaal beantwoord tijdens de bouw:**

1. Flask of Streamlit (of iets anders) voor de lokale UI-laag?
   → **Flask**, met een gevendorde Konva.js-canvaslaag voor de
   correctiestap (geen CDN, alles offline).
2. Hoe wordt de correctiestap precies bediend — canvas met sleepbare
   rechthoeken (bv. via een JS-canvaslaag), of eenvoudiger met een lijst
   + coördinaatvelden?
   → Canvas met sleepbare/resizebare rechthoeken (`Konva.Transformer`),
   incl. Shift+slepen om meerdere vakken tegelijk te selecteren, zie 3.3.
3. Welke minimale Windows-versie/Python-runtime-bundeling geeft de
   kleinste/robuustste `.exe`?
   → Python 3.11, PyInstaller `--onefile`, gebouwd via GitHub Actions op
   `windows-latest` bij elke release; werkt op Windows 10/11 64-bit.
4. Wordt Route 1 (sectie 4) meteen meegenomen in v2, of pas na de eerste
   werkende UI-versie?
   → Route 1-spike is los uitgevoerd en heeft niets opgeleverd voor het
   geteste brontype (zie `scripts/spikes/ROUTE1_FINDINGS.md`) — flood-fill
   blijft de aanpak voor ruimtedetectie.
