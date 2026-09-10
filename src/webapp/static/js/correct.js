(function () {
  const container = document.getElementById("stage-container");
  const jobId = document.querySelector(".correct-page").dataset.jobId;
  const loadingEl = document.getElementById("loading");
  const statusEl = document.getElementById("status-msg");

  const ROOM_COLOR = "#2f6f4f";
  const ROOM_COLOR_SELECTED = "#c9622a";
  const NEW_ID_PREFIX = "new-";

  /** @type {{id:string, bbox:[number,number,number,number], name:string|null, source:string}[]} */
  let rooms = [];
  let imageWidth = 0;
  let imageHeight = 0;
  let fitScale = 1;
  let zoom = 1;
  let tool = "select"; // "select" | "draw" | "erase"
  const ERASE_COLOR = "#b3413f"; // zelfde als --danger in app.css
  // Waarschuwt bij "Terug" als er nog niet-geëxporteerde wijzigingen zijn
  // (correcties leven alleen client-side totdat er geëxporteerd wordt).
  let hasUnsavedChanges = false;
  // Volgorde van selectie - onbeperkt aantal, zowel via los shift-klikken
  // als via een marquee-selectiekader (zie setupMarqueeSelect). "Samenvoegen"
  // en "Verwijderen" werken allebei voor elk aantal (2 of meer resp. 1 of
  // meer, zie updateToolbarState).
  let selectedIds = [];

  let stage, bgLayer, roomLayer, transformer;
  let bgImageNode = null; // Konva.Image met de plattegrond-achtergrond
  const nodesById = new Map(); // room.id -> {group, rect, label}

  // ---- undo (1 stap terug, geen redo) --------------------------------
  //
  // Ruimte-vak-bewerkingen leven alleen client-side (undo daarvan is dus
  // simpel: de oude 'rooms'-array terugzetten). Roteren/gummen passen de
  // afbeelding blijvend aan OP DE SERVER - om die ook terug te kunnen
  // draaien bewaart de client zelf de laatst geladen afbeelding als Blob
  // (zie loadBackgroundImage) en stuurt die bij undo terug naar een nieuwe
  // /restore-route. Bewust maar 1 stap diep: dekt de praktische zorg
  // ("oeps, verkeerd geveegd/gedraaid") zonder de complexiteit van een
  // volledige geschiedenis + redo.
  let currentImageBlob = null;
  let undoSnapshot = null; // {rooms, imageBlob} | null

  function captureUndoSnapshot(imageChanged) {
    if (!currentImageBlob) return; // nog niet geladen, kan niet gebeuren na init()
    // Bij een zuivere ruimte-vak-wijziging (slepen/hernoemen/samenvoegen/
    // verwijderen/nieuw tekenen) verandert de afbeelding niet - undo daarvan
    // hoeft dan de server niet in (zie undo() hieronder), alleen bij
    // roteren/gummen is er ook een afbeelding-versie om terug te zetten.
    undoSnapshot = { rooms: rooms.map((r) => ({ ...r })), imageBlob: imageChanged ? currentImageBlob : null };
    document.getElementById("btn-undo").disabled = false;
  }

  async function undo() {
    if (!undoSnapshot) return;
    clearStatus();
    const snap = undoSnapshot;
    undoSnapshot = null; // eenmalig: meteen "verbruikt", geen redo
    document.getElementById("btn-undo").disabled = true;
    transformer.nodes([]);
    selectedIds = [];

    if (!snap.imageBlob) {
      rooms = snap.rooms;
      redrawAll();
      hasUnsavedChanges = true;
      return;
    }
    const prevWidth = imageWidth;
    const prevHeight = imageHeight;
    try {
      const body = new FormData();
      body.append("image", snap.imageBlob, "image.png");
      body.append("rooms", JSON.stringify(snap.rooms));
      const resp = await fetch(`/jobs/${jobId}/restore`, { method: "POST", body });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Server error (${resp.status})`);
      }
      const data = await resp.json();
      imageWidth = data.width;
      imageHeight = data.height;
      rooms = data.rooms.map((r) => ({ ...r }));
      await loadBackgroundImage(`/jobs/${jobId}/image?t=${Date.now()}`);
      // Alleen als de afmetingen echt veranderd zijn (bv. undo van een
      // rotatie) is fitToContainer() nodig - het huidige zoomniveau/pan
      // klopt dan sowieso niet meer tegen de nieuwe afbeeldingsgrootte.
      // Bij een gum-undo (afmetingen ongewijzigd) blijft de gebruiker
      // gewoon op hetzelfde zoomniveau/dezelfde plek staan.
      if (imageWidth !== prevWidth || imageHeight !== prevHeight) {
        fitToContainer();
      }
      redrawAll();
      hasUnsavedChanges = true;
    } catch (err) {
      showStatus("Undo failed: " + err.message, true);
    }
  }

  function totalScale() {
    return fitScale * zoom;
  }

  function showStatus(text, isError) {
    statusEl.hidden = false;
    statusEl.textContent = text;
    statusEl.classList.toggle("error", !!isError);
  }

  function clearStatus() {
    statusEl.hidden = true;
  }

  // ---- data <-> canvas conversie -----------------------------------

  function imageBboxToStageRect(bbox) {
    const [x0, y0, x1, y1] = bbox;
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  }

  function newRoomId() {
    return NEW_ID_PREFIX + Math.random().toString(36).slice(2, 10);
  }

  // ---- rendering ------------------------------------------------------

  function buildRoomNode(room) {
    const r = imageBboxToStageRect(room.bbox);
    const group = new Konva.Group({ x: r.x, y: r.y, draggable: false, id: room.id });

    const rect = new Konva.Rect({
      width: r.width,
      height: r.height,
      stroke: ROOM_COLOR,
      strokeWidth: 2 / totalScale(),
      fill: "rgba(47,111,79,0.08)",
      name: "room-rect",
    });

    const label = new Konva.Text({
      text: room.name || "(no name)",
      fontSize: 14 / totalScale(),
      fill: "#1f2320",
      padding: 2,
      x: 2,
      y: 2,
      // Breedte vastzetten op de vakbreedte (met ellipsis i.p.v. wrappen):
      // zonder dit wordt een lange naam op een smal vak breder dan het vak
      // zelf, en omdat de Transformer zich baseert op de omvattende
      // GROUP (vak + label samen) ging de selectie-/resize-rand dan verder
      // dan het echte vak.
      width: r.width,
      wrap: "none",
      ellipsis: true,
      name: "room-label",
    });

    group.add(rect);
    group.add(label);
    roomLayer.add(group);
    // De Transformer moet altijd boven-op alle ruimte-vakken blijven staan,
    // anders ligt een net toegevoegd vak overheen en vang je alle klikken
    // af met de gewone (versleep-)rect in plaats van met de resize-grepen
    // eronder - dan lijkt het net of er alleen verslepen mogelijk is.
    transformer.moveToTop();
    nodesById.set(room.id, { group, rect, label });

    group.on("click tap", (e) => {
      if (tool !== "select") return;
      e.cancelBubble = true;
      selectRoom(room.id, e.evt && e.evt.shiftKey);
    });
    group.on("dblclick dbltap", (e) => {
      e.cancelBubble = true;
      startRename(room.id);
    });
    group.on("dragend", () => onTransformOrDragEnd(room));

    return group;
  }

  function redrawAll() {
    // transformer.remove() (NIET destroy) haalt 'm los van roomLayer VOORDAT
    // destroyChildren() de rest opruimt - anders wordt de transformer zelf
    // ook vernietigd, inclusief zijn eigen interne resize-greep-vormen. Die
    // greep-vormen worden maar één keer aangemaakt (bij het aanmaken van de
    // Transformer) en komen na destroy() nooit meer terug, ook niet als je
    // 'm daarna weer toevoegt met roomLayer.add(transformer) - dan lijkt de
    // Transformer normaal te werken (selecteren/verslepen), maar heeft hij
    // in werkelijkheid geen enkele klikbare resize-greep meer.
    transformer.remove();
    roomLayer.destroyChildren();
    roomLayer.add(transformer);
    nodesById.clear();
    rooms.forEach(buildRoomNode);
    applySelection();
  }

  function syncNodeToRoom(room) {
    const nodes = nodesById.get(room.id);
    if (!nodes) return;
    const r = imageBboxToStageRect(room.bbox);
    nodes.group.position({ x: r.x, y: r.y });
    nodes.rect.size({ width: r.width, height: r.height });
    nodes.label.width(r.width);
    nodes.label.text(room.name || "(no name)");
  }

  // ---- selectie ---------------------------------------------------------

  function applySelectionStyles() {
    rooms.forEach((room) => {
      const nodes = nodesById.get(room.id);
      if (!nodes) return;
      const isSelected = selectedIds.includes(room.id);
      nodes.rect.stroke(isSelected ? ROOM_COLOR_SELECTED : ROOM_COLOR);
      nodes.rect.fill(isSelected ? "rgba(201,98,42,0.12)" : "rgba(47,111,79,0.08)");
    });
    roomLayer.draw();
    updateToolbarState();
  }

  function selectRoom(id, additive) {
    if (additive) {
      if (selectedIds.includes(id)) {
        selectedIds = selectedIds.filter((x) => x !== id);
      } else {
        selectedIds.push(id);
      }
    } else {
      selectedIds = [id];
    }
    applySelection();
  }

  function clearSelection() {
    selectedIds = [];
    applySelection();
  }

  // Transformer loskoppelen en draggable her-instellen moeten in deze
  // volgorde (eerst transformer.nodes([]) op ALLE nodes) - anders kan
  // Konva's Transformer intern een 'setAttrs on undefined'-fout geven
  // wanneer draggable() verandert op een node die de Transformer nog
  // vasthoudt (geraakt tijdens handmatig testen van multi-select).
  // Konva's Transformer raakt intern in de war (dezelfde 'setAttrs on
  // undefined'-crash) zodra de laag waar hij een afstammeling van is van
  // schaal of positie verandert terwijl hij aan een node gekoppeld is -
  // dus ook tijdens zoomen/pannen met een geselecteerd vak. Gebruik dit
  // overal waar bgLayer/roomLayer schaal of positie wijzigt: loskoppelen,
  // wijzigen, weer aankoppelen.
  function withTransformerDetached(fn) {
    const prevNodes = transformer.nodes();
    if (prevNodes.length > 0) transformer.nodes([]);
    fn();
    if (prevNodes.length > 0) transformer.nodes(prevNodes);
  }

  function applySelection() {
    transformer.nodes([]);
    nodesById.forEach((nodes) => nodes.group.draggable(false));
    if (selectedIds.length === 1) {
      const nodes = nodesById.get(selectedIds[0]);
      if (nodes) {
        nodes.group.draggable(tool === "select");
        transformer.nodes([nodes.group]);
      }
    }
    applySelectionStyles();
    roomLayer.draw();
  }

  function updateToolbarState() {
    document.getElementById("btn-delete").disabled = selectedIds.length === 0;
    document.getElementById("btn-merge").disabled = selectedIds.length < 2;
  }

  // ---- drag/resize -> state terugschrijven -------------------------------

  function onTransformOrDragEnd(room) {
    const nodes = nodesById.get(room.id);
    if (!nodes) return;
    captureUndoSnapshot(false);
    const group = nodes.group;
    const rect = nodes.rect;
    const scaleX = group.scaleX();
    const scaleY = group.scaleY();
    const width = rect.width() * scaleX;
    const height = rect.height() * scaleY;
    const x0 = group.x();
    const y0 = group.y();

    group.scaleX(1);
    group.scaleY(1);
    rect.size({ width, height });
    nodes.label.width(width); // zie toelichting in buildRoomNode

    // Zonder dit blijven de resize-grepen nog even op hun OUDE plek staan
    // (ze volgen alleen automatisch tijdens het slepen zelf, niet een
    // programmatische scale/size-aanpassing hierboven erna) - ze
    // "verspringen" dan pas bij de eerstvolgende interactie. forceUpdate()
    // rekent de grepen meteen opnieuw uit tegen de nieuwe afmetingen.
    transformer.forceUpdate();
    roomLayer.draw();

    room.bbox = [Math.round(x0), Math.round(y0), Math.round(x0 + width), Math.round(y0 + height)];
    room.source = room.source === "auto" ? "user-edited" : room.source;
    hasUnsavedChanges = true;
  }

  // ---- hernoemen (HTML input overlay op Konva.Text) ----------------------

  function startRename(id) {
    const room = rooms.find((r) => r.id === id);
    const nodes = nodesById.get(id);
    if (!room || !nodes) return;

    // Geen relativeTo hier: sinds zoom op de STAGE zelf zit (niet meer op
    // bgLayer/roomLayer), geeft relativeTo:stage juist de coördinaten VAN
    // VOOR die schaal (te klein/verkeerd) - zonder relativeTo krijg je de
    // volledige, al-getransformeerde canvas-pixelpositie die we hier nodig
    // hebben om de input op het scherm te plaatsen.
    const box = nodes.label.getClientRect();
    const stageBox = stage.container().getBoundingClientRect();

    const input = document.createElement("input");
    input.type = "text";
    input.value = room.name || "";
    input.className = "room-name-input";
    input.style.left = stageBox.left + box.x + "px";
    input.style.top = stageBox.top + box.y + "px";
    input.style.width = Math.max(80, box.width + 40) + "px";
    document.body.appendChild(input);
    input.focus();
    input.select();

    function commit() {
      captureUndoSnapshot(false);
      room.name = input.value.trim() || null;
      if (room.source === "auto") room.source = "user-edited";
      syncNodeToRoom(room);
      document.body.removeChild(input);
      hasUnsavedChanges = true;
    }
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") {
        input.removeEventListener("blur", commit);
        document.body.removeChild(input);
      }
    });
  }

  // ---- verwijderen / samenvoegen ------------------------------------------

  function deleteSelected() {
    if (selectedIds.length === 0) return;
    captureUndoSnapshot(false);
    transformer.nodes([]); // eerst loskoppelen, anders crasht Konva bij destroy() van een vastgehouden node
    rooms = rooms.filter((r) => !selectedIds.includes(r.id));
    selectedIds.forEach((id) => {
      const nodes = nodesById.get(id);
      if (nodes) nodes.group.destroy();
      nodesById.delete(id);
    });
    selectedIds = [];
    applySelection();
    hasUnsavedChanges = true;
  }

  // Samenvoegen van 2 of meer vakken (bv. een kamer + de deurvakjes die er
  // per ongeluk los van gedetecteerd zijn) tot één omvattende rechthoek -
  // handig omdat losse vakjes anders één voor één met "Verwijderen"
  // opgeruimd zouden moeten worden terwijl ze eigenlijk gewoon bij de kamer
  // horen.
  function mergeSelected() {
    if (selectedIds.length < 2) return;
    const selected = selectedIds.map((id) => rooms.find((r) => r.id === id)).filter(Boolean);
    if (selected.length < 2) return;

    const x0 = Math.min(...selected.map((r) => r.bbox[0]));
    const y0 = Math.min(...selected.map((r) => r.bbox[1]));
    const x1 = Math.max(...selected.map((r) => r.bbox[2]));
    const y1 = Math.max(...selected.map((r) => r.bbox[3]));

    const suggestedName = selected.find((r) => r.name)?.name || "";
    const name = window.prompt("Name for the merged room:", suggestedName);
    if (name === null) return; // geannuleerd
    captureUndoSnapshot(false);

    const merged = {
      id: newRoomId(),
      bbox: [x0, y0, x1, y1],
      name: name.trim() || null,
      source: "user-merged",
    };

    transformer.nodes([]); // eerst loskoppelen, anders crasht Konva bij destroy() van een vastgehouden node
    const mergedIds = new Set(selected.map((r) => r.id));
    rooms = rooms.filter((r) => !mergedIds.has(r.id));
    selected.forEach((r) => {
      const nodes = nodesById.get(r.id);
      if (nodes) nodes.group.destroy();
      nodesById.delete(r.id);
    });
    rooms.push(merged);
    buildRoomNode(merged);
    selectedIds = [];
    applySelection();
    hasUnsavedChanges = true;
  }

  // ---- nieuw vak tekenen -----------------------------------------------

  let drawRect = null;
  let drawStart = null;
  let suppressNextBackgroundClick = false;

  function setTool(next) {
    tool = next;
    document.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tool === tool);
    });
    if (tool !== "select") {
      clearSelection();
    }
    stage.container().style.cursor = tool === "draw" || tool === "erase" ? "crosshair" : "grab";
  }

  // Konva's eigen helper: loopt de VOLLEDIGE oudertransformatie-keten af
  // (stage-schaal/positie + bgLayer's eigen, altijd identiteits-transform)
  // om de aanwijzerpositie in afbeeldingspixels te geven - geen handmatige
  // omrekening meer nodig (zie ook waarom hieronder bij fitToContainer/
  // applyStageTransform: de STAGE zelf schaalt nu, niet de lagen).
  function stagePointerToImagePoint() {
    return bgLayer.getRelativePointerPosition();
  }

  function setupDrawing() {
    // drawRect is een kind van roomLayer, die zelf altijd op identiteits-
    // schaal blijft (de STAGE zelf schaalt/verschuift voor zoom/pan) - dus
    // x/y/width/height hier gewoon in AFBEELDINGSPIXELS zetten.
    stage.on("mousedown touchstart", (e) => {
      if (tool !== "draw") return;
      if (e.target !== stage && !e.target.hasName("bg-image")) return;
      drawStart = stagePointerToImagePoint();
      drawRect = new Konva.Rect({
        x: drawStart.x,
        y: drawStart.y,
        width: 0,
        height: 0,
        stroke: ROOM_COLOR_SELECTED,
        dash: [4 / totalScale(), 4 / totalScale()],
        strokeWidth: 2 / totalScale(),
      });
      roomLayer.add(drawRect);
    });

    stage.on("mousemove touchmove", () => {
      if (tool !== "draw" || !drawRect || !drawStart) return;
      const cur = stagePointerToImagePoint();
      const x0 = Math.min(drawStart.x, cur.x);
      const y0 = Math.min(drawStart.y, cur.y);
      const w = Math.abs(cur.x - drawStart.x);
      const h = Math.abs(cur.y - drawStart.y);
      drawRect.setAttrs({ x: x0, y: y0, width: w, height: h });
      roomLayer.batchDraw();
    });

    stage.on("mouseup touchend", () => {
      if (tool !== "draw" || !drawRect) return;
      const x0 = drawRect.x();
      const y0 = drawRect.y();
      const w = drawRect.width();
      const h = drawRect.height();
      drawRect.destroy();
      drawRect = null;
      drawStart = null;
      roomLayer.draw();

      const minSizeImgPx = 8 / totalScale(); // 8 schermpixels, omgerekend
      if (w < minSizeImgPx || h < minSizeImgPx) return;

      captureUndoSnapshot(false);
      const room = {
        id: newRoomId(),
        bbox: [Math.round(x0), Math.round(y0), Math.round(x0 + w), Math.round(y0 + h)],
        name: null,
        source: "user-new",
      };
      rooms.push(room);
      buildRoomNode(room);
      roomLayer.draw();
      setTool("select");
      selectRoom(room.id, false);
      startRename(room.id);
      hasUnsavedChanges = true;
      // mousedown EN mouseup van deze teken-actie vonden beide plaats op de
      // achtergrond, dus Konva vuurt hierna nog een synthetische "click" op
      // diezelfde achtergrond af - zonder deze vlag zou de stage-click-
      // handler hieronder de zojuist gezette selectie (en dus de
      // resize-handvatten) meteen weer opheffen.
      suppressNextBackgroundClick = true;
    });
  }

  // ---- gum (rechthoek slepen om permanent uit te vlakken) ---------------
  //
  // Anders dan alle andere correcties raakt dit de AFBEELDING zelf (niet
  // een ruimte-vak) - voor restjes die de automatische opschoning laat
  // staan (bv. tekst die OCR miste). Zelfde sleep-interactie als
  // setupDrawing() hierboven, maar het resultaat gaat naar de server i.p.v.
  // een nieuw ruimte-vak aan te maken. Met "Undo" (zie hierboven) 1 stap
  // terug te draaien.

  let eraseRectPreview = null;
  let eraseStart = null;

  async function eraseRect(x0, y0, x1, y1) {
    clearStatus();
    captureUndoSnapshot(true);
    try {
      const resp = await fetch(`/jobs/${jobId}/erase`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x0, y0, x1, y1 }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Server error (${resp.status})`);
      }
      // Afmetingen en ruimte-vakken veranderen niet door een gum-actie -
      // alleen de achtergrondafbeelding opnieuw laden volstaat (geen
      // fitToContainer/redrawAll nodig, die zijn voor roteren waar de
      // afbeeldingsgrootte wel kan wijzigen).
      await loadBackgroundImage(`/jobs/${jobId}/image?t=${Date.now()}`);
      hasUnsavedChanges = true;
    } catch (err) {
      showStatus("Erase failed: " + err.message, true);
    }
  }

  function setupErasing() {
    stage.on("mousedown touchstart", (e) => {
      if (tool !== "erase") return;
      // Anders dan setupDrawing/setupPanning hierboven GEEN restrictie tot
      // de lege achtergrond: rommelige tekst die je wilt wegvegen zit vaak
      // juist BINNEN een al gedetecteerd (naamloos) ruimte-vak - de gum moet
      // dus overal kunnen starten, ook bovenop een bestaand vak. Veilig
      // (geen conflict met het verslepen van dat vak): ruimte-vakken zijn
      // nooit draggable zolang tool !== "select" (zie applySelection).
      eraseStart = stagePointerToImagePoint();
      eraseRectPreview = new Konva.Rect({
        x: eraseStart.x,
        y: eraseStart.y,
        width: 0,
        height: 0,
        stroke: ERASE_COLOR,
        dash: [4 / totalScale(), 4 / totalScale()],
        strokeWidth: 2 / totalScale(),
        fill: "rgba(179,65,63,0.15)",
      });
      roomLayer.add(eraseRectPreview);
    });

    stage.on("mousemove touchmove", () => {
      if (tool !== "erase" || !eraseRectPreview || !eraseStart) return;
      const cur = stagePointerToImagePoint();
      const x0 = Math.min(eraseStart.x, cur.x);
      const y0 = Math.min(eraseStart.y, cur.y);
      const w = Math.abs(cur.x - eraseStart.x);
      const h = Math.abs(cur.y - eraseStart.y);
      eraseRectPreview.setAttrs({ x: x0, y: y0, width: w, height: h });
      roomLayer.batchDraw();
    });

    stage.on("mouseup touchend", () => {
      if (tool !== "erase" || !eraseRectPreview) return;
      const x0 = eraseRectPreview.x();
      const y0 = eraseRectPreview.y();
      const w = eraseRectPreview.width();
      const h = eraseRectPreview.height();
      eraseRectPreview.destroy();
      eraseRectPreview = null;
      eraseStart = null;
      roomLayer.draw();

      const minSizeImgPx = 8 / totalScale(); // zelfde ondergrens als bij "+ Draw box"
      if (w < minSizeImgPx || h < minSizeImgPx) return;

      eraseRect(Math.round(x0), Math.round(y0), Math.round(x0 + w), Math.round(y0 + h));
      // zelfde reden als bij setupDrawing/setupMarqueeSelect: onderdrukt de
      // synthetische achtergrond-klik die anders meteen hierna volgt.
      suppressNextBackgroundClick = true;
    });
  }

  // ---- pannen (achtergrond slepen) ---------------------------------------
  //
  // Nodig zodra je inzoomt: de tekening kan dan gedeeltelijk buiten het
  // zichtbare vlak vallen. Pannen verschuift de STAGE zelf (niet de lagen -
  // zie fitToContainer/applyStageTransform hieronder voor waarom), dus
  // bgLayer/roomLayer/de vakjes bewegen daar automatisch in mee.

  let panStart = null;
  let didPan = false;

  let panDetachedNodes = [];

  function setupPanning() {
    stage.on("mousedown touchstart", (e) => {
      if (tool !== "select") return;
      if (e.evt && e.evt.shiftKey) return; // Shift+slepen is marquee-selectie, zie setupMarqueeSelect()
      if (e.target !== stage && !e.target.hasName("bg-image")) return;
      panStart = { pointer: stage.getPointerPosition(), stagePos: stage.position() };
      didPan = false;
      stage.container().style.cursor = "grabbing";
      // Transformer loskoppelen vóór de stage-positie verandert (zie
      // withTransformerDetached) - puur defensief, zelfde voorzorg als bij
      // applyStageTransform.
      panDetachedNodes = transformer.nodes();
      if (panDetachedNodes.length > 0) transformer.nodes([]);
    });

    stage.on("mousemove touchmove", () => {
      if (!panStart) return;
      const pos = stage.getPointerPosition();
      const dx = pos.x - panStart.pointer.x;
      const dy = pos.y - panStart.pointer.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) didPan = true;
      stage.position({ x: panStart.stagePos.x + dx, y: panStart.stagePos.y + dy });
      stage.batchDraw();
    });

    stage.on("mouseup touchend", () => {
      if (!panStart) return;
      panStart = null;
      stage.container().style.cursor = tool === "draw" || tool === "erase" ? "crosshair" : "grab";
      if (panDetachedNodes.length > 0) {
        transformer.nodes(panDetachedNodes);
        panDetachedNodes = [];
        roomLayer.draw();
      }
    });
  }

  // ---- marquee-selectie (Shift + slepen over meerdere vakken) -----------
  //
  // Bij een detectie met veel foutieve losse mini-vakjes (typisch bij een
  // platte/OCR-gebaseerde plattegrond) is 1-voor-1 aanklikken omslachtig -
  // Shift+slepen tekent een selectiekader en selecteert in één keer alle
  // vakken die het raakt, waarna "Verwijderen" (of de Delete-toets) ze
  // allemaal ineens weghaalt. Gewone (niet-Shift) sleep blijft pannen, zie
  // setupPanning() hierboven.

  let marqueeStart = null;
  let marqueeRect = null;

  function setupMarqueeSelect() {
    stage.on("mousedown touchstart", (e) => {
      if (tool !== "select" || !(e.evt && e.evt.shiftKey)) return;
      if (e.target !== stage && !e.target.hasName("bg-image")) return;
      marqueeStart = stagePointerToImagePoint();
      marqueeRect = new Konva.Rect({
        x: marqueeStart.x,
        y: marqueeStart.y,
        width: 0,
        height: 0,
        stroke: ROOM_COLOR_SELECTED,
        dash: [4 / totalScale(), 4 / totalScale()],
        strokeWidth: 2 / totalScale(),
        fill: "rgba(201,98,42,0.08)",
      });
      roomLayer.add(marqueeRect);
    });

    stage.on("mousemove touchmove", () => {
      if (!marqueeStart || !marqueeRect) return;
      const cur = stagePointerToImagePoint();
      const x0 = Math.min(marqueeStart.x, cur.x);
      const y0 = Math.min(marqueeStart.y, cur.y);
      const w = Math.abs(cur.x - marqueeStart.x);
      const h = Math.abs(cur.y - marqueeStart.y);
      marqueeRect.setAttrs({ x: x0, y: y0, width: w, height: h });
      roomLayer.batchDraw();
    });

    stage.on("mouseup touchend", () => {
      if (!marqueeStart || !marqueeRect) return;
      const x0 = marqueeRect.x();
      const y0 = marqueeRect.y();
      const x1 = x0 + marqueeRect.width();
      const y1 = y0 + marqueeRect.height();
      marqueeRect.destroy();
      marqueeRect = null;
      marqueeStart = null;
      roomLayer.draw();

      // Elk vak dat het selectiekader RAAKT (overlap), niet alleen vakken
      // die er volledig binnen vallen - vergevingsgezinder bij een kader
      // dat niet exact om een cluster kleine vakjes heen past.
      const hit = rooms.filter((r) => {
        const [rx0, ry0, rx1, ry1] = r.bbox;
        return rx0 < x1 && rx1 > x0 && ry0 < y1 && ry1 > y0;
      });
      if (hit.length === 0) return;
      selectedIds = hit.map((r) => r.id);
      applySelection();
      // Zelfde reden als bij het tekenen van een nieuw vak: mousedown EN
      // mouseup vonden beide op de achtergrond plaats, dus Konva vuurt
      // hierna nog een synthetische "click" af die de selectie anders
      // meteen weer zou opheffen.
      suppressNextBackgroundClick = true;
    });
  }

  // ---- zoom / fit --------------------------------------------------------

  function applyStageTransform() {
    const t = totalScale();
    // De STAGE zelf schaalt voor zoom (niet bgLayer/roomLayer, die blijven
    // altijd op identiteits-transform) - dit is het standaard Konva-patroon
    // waar de Transformer/resize-handvatten correct mee samenwerken. Eerder
    // schaalden we de lagen zelf, wat de Transformer intern liet crashen
    // zodra hij aan een geselecteerd vak gekoppeld was (zie git-historie).
    // Loskoppelen vóór de schaal verandert blijft hier puur defensief.
    withTransformerDetached(() => {
      stage.scale({ x: t, y: t });
    });
    // strokeWidth/fontSize zijn absoluut ingesteld op basis van totalScale()
    // bij aanmaak; bij zoom herrekenen we ze zodat lijnen niet te dik worden.
    nodesById.forEach(({ rect, label }) => {
      rect.strokeWidth(2 / t);
      label.fontSize(14 / t);
    });
    // Konva houdt de Transformer-handvatten zelf al op een vaste
    // schermgrootte, ongeacht de stage-schaal - eerder hier ook nog met /t
    // compenseren telde dus dubbel en maakte de grepen juist reusachtig
    // groot. Gewone vaste waarden, geen herberekening nodig.
    transformer.anchorSize(10);
    transformer.anchorStrokeWidth(1.5);
    transformer.borderStrokeWidth(1.5);
    // Direct (synchroon) tekenen i.p.v. stage.batchDraw(): batchDraw plant de
    // herteken-beurt via requestAnimationFrame, wat bij snel achter elkaar
    // klikken op +/- kan blijven "hangen" op een oud beeld totdat er iets
    // anders een hertekening forceert (zoals de Fit-knop) - voor een
    // klik-gestuurde zoom (geen animatie) is synchroon tekenen prima.
    stage.draw();
  }

  function fitToContainer() {
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (!imageWidth || !imageHeight) return;
    fitScale = Math.min(cw / imageWidth, ch / imageHeight) * 0.95;
    zoom = 1;
    stage.size({ width: cw, height: ch });
    withTransformerDetached(() => {
      stage.position({ x: (cw - imageWidth * fitScale) / 2, y: (ch - imageHeight * fitScale) / 2 });
    });
    applyStageTransform();
  }

  function zoomBy(factor) {
    zoom = Math.max(0.2, Math.min(6, zoom * factor));
    applyStageTransform();
  }

  // Inzoomen op een vast punt op het scherm (bv. de muispositie) i.p.v. de
  // hoek van de stage: reken uit welk afbeeldingspunt daar nu onder ligt,
  // pas de zoom toe, en verschuif de stage zodat datzelfde punt onder de
  // muis blijft liggen (zelfde gevoel als bv. Google Maps).
  function zoomAtPoint(factor, point) {
    const oldScale = totalScale();
    const pointTo = {
      x: (point.x - stage.x()) / oldScale,
      y: (point.y - stage.y()) / oldScale,
    };
    zoom = Math.max(0.2, Math.min(6, zoom * factor));
    const newScale = totalScale();
    withTransformerDetached(() => {
      stage.position({
        x: point.x - pointTo.x * newScale,
        y: point.y - pointTo.y * newScale,
      });
    });
    applyStageTransform();
  }

  function setupWheelZoom() {
    stage.on("wheel", (e) => {
      e.evt.preventDefault();
      const pointer = stage.getPointerPosition();
      if (!pointer) return;
      const factor = e.evt.deltaY > 0 ? 1 / 1.08 : 1.08;
      zoomAtPoint(factor, pointer);
    });
  }

  // ---- roteren -----------------------------------------------------------

  // Gedeeld door de exacte 90-graden-knop en de vrije-hoek-invoer: beide
  // roepen server-side een rotate-endpoint aan met de huidige rooms, en
  // verwerken het antwoord (nieuwe afbeelding + omgerekende vakken) op
  // dezelfde manier.
  async function applyRotateResponse(fetchPromise, errorPrefix) {
    clearStatus();
    captureUndoSnapshot(true);
    transformer.nodes([]); // loskoppelen: rooms/afbeelding worden zo vervangen
    selectedIds = [];
    try {
      const resp = await fetchPromise;
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Server error (${resp.status})`);
      }
      const data = await resp.json();
      imageWidth = data.width;
      imageHeight = data.height;
      rooms = data.rooms.map((r) => ({ ...r }));
      // Zelfde URL als altijd, maar de inhoud op de server is net veranderd -
      // cache-buster nodig zodat de browser niet de oude (ongedraaide)
      // afbeelding uit de cache hergebruikt.
      await loadBackgroundImage(`/jobs/${jobId}/image?t=${Date.now()}`);
      fitToContainer();
      redrawAll();
      hasUnsavedChanges = true;
    } catch (err) {
      showStatus(errorPrefix + err.message, true);
    }
  }

  function rotateClockwise() {
    return applyRotateResponse(
      fetch(`/jobs/${jobId}/rotate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rooms }),
      }),
      "Rotate failed: "
    );
  }

  function rotateByAngle(degrees) {
    return applyRotateResponse(
      fetch(`/jobs/${jobId}/rotate-angle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rooms, degrees }),
      }),
      "Rotate failed: "
    );
  }

  // Laadt (of vervangt) de achtergrondafbeelding. Gebruikt zowel bij het
  // eerste laden als na het roteren (dan verandert alleen de servercontent
  // achter dezelfde/nieuwe url, niet de Konva-Image-node zelf).
  async function loadBackgroundImage(url) {
    // Als Blob ophalen (i.p.v. de <img> rechtstreeks op de url te zetten) om
    // 'm ook te kunnen bewaren als undo-snapshot (zie captureUndoSnapshot) -
    // zonder aparte fetch zou een undo de afbeelding opnieuw van de server
    // moeten terugvragen, die op dat moment alweer overschreven is.
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Failed to load the image.");
    const blob = await resp.blob();
    currentImageBlob = blob;
    const objectUrl = URL.createObjectURL(blob);
    try {
      await new Promise((resolve, reject) => {
        const imgObj = new Image();
        imgObj.onload = () => {
          if (bgImageNode) {
            bgImageNode.image(imgObj);
          } else {
            bgImageNode = new Konva.Image({ image: imgObj, name: "bg-image" });
            bgLayer.add(bgImageNode);
          }
          // Expliciet zetten i.p.v. op Konva's eigen default (= de natuurlijke
          // afmeting van de <img>) vertrouwen: na roteren staan imageWidth/
          // imageHeight (uit de server-respons) al vast VOORDAT deze functie
          // wordt aangeroepen, dus dit is de betrouwbare bron.
          bgImageNode.width(imageWidth);
          bgImageNode.height(imageHeight);
          bgLayer.draw();
          resolve();
        };
        imgObj.onerror = () => reject(new Error("Failed to load the image."));
        imgObj.src = objectUrl;
      });
    } finally {
      // Veilig meteen vrijgeven: de <img> heeft de data al gedecodeerd zodra
      // onload vuurt, de object-url zelf hoeft daarna niet meer te bestaan.
      URL.revokeObjectURL(objectUrl);
    }
  }

  // ---- init ----------------------------------------------------------------

  async function init() {
    stage = new Konva.Stage({
      container: "stage-container",
      width: container.clientWidth,
      height: container.clientHeight,
    });
    bgLayer = new Konva.Layer();
    roomLayer = new Konva.Layer();
    stage.add(bgLayer);
    stage.add(roomLayer);
    transformer = new Konva.Transformer({
      rotateEnabled: false,
      keepRatio: false,
      boundBoxFunc: (oldBox, newBox) => (newBox.width < 10 || newBox.height < 10 ? oldBox : newBox),
    });
    roomLayer.add(transformer);

    stage.on("click tap", (e) => {
      if (didPan) return; // dit was een sleep om te pannen, geen klik-om-te-deselecteren
      if (suppressNextBackgroundClick) {
        suppressNextBackgroundClick = false;
        return; // synthetische klik na het tekenen van een nieuw vak, niet echt een deselectie-klik
      }
      if (tool === "select" && (e.target === stage || e.target.hasName("bg-image"))) {
        clearSelection();
      }
    });

    setupDrawing();
    setupErasing();
    setupPanning();
    setupMarqueeSelect();
    setupWheelZoom();

    let resp;
    try {
      resp = await fetch(`/jobs/${jobId}/detect`);
      if (!resp.ok) throw new Error(`Server error (${resp.status})`);
    } catch (err) {
      loadingEl.textContent = "Failed to load: " + err.message;
      return;
    }
    const data = await resp.json();
    imageWidth = data.width;
    imageHeight = data.height;
    rooms = data.rooms.map((r) => ({ ...r }));
    loadingEl.hidden = true;

    try {
      await loadBackgroundImage(data.image_url);
    } catch (err) {
      loadingEl.hidden = false;
      loadingEl.textContent = "Failed to load: " + err.message;
      return;
    }
    fitToContainer();
    redrawAll();

    window.addEventListener("resize", () => {
      fitToContainer();
      roomLayer.draw();
    });

    document.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTool(btn.dataset.tool));
    });
    document.getElementById("btn-delete").addEventListener("click", deleteSelected);
    document.getElementById("btn-merge").addEventListener("click", mergeSelected);
    document.getElementById("btn-undo").addEventListener("click", undo);
    document.getElementById("btn-zoom-in").addEventListener("click", () => zoomBy(1.25));
    document.getElementById("btn-zoom-out").addEventListener("click", () => zoomBy(0.8));
    document.getElementById("btn-zoom-fit").addEventListener("click", () => {
      fitToContainer();
      roomLayer.draw();
    });
    document.getElementById("btn-rotate").addEventListener("click", rotateClockwise);
    document.getElementById("btn-rotate-angle").addEventListener("click", () => {
      const degrees = parseFloat(document.getElementById("rotate-angle-input").value);
      if (!Number.isFinite(degrees) || degrees === 0) return;
      rotateByAngle(degrees);
    });
    document.addEventListener("keydown", (e) => {
      if ((e.key === "Delete" || e.key === "Backspace") && selectedIds.length && document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        deleteSelected();
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        undo();
      }
    });

    transformer.on("transformend", () => {
      selectedIds.forEach((id) => {
        const room = rooms.find((r) => r.id === id);
        if (room) onTransformOrDragEnd(room);
      });
    });

    document.getElementById("btn-export").addEventListener("click", doExport);

    document.getElementById("btn-back").addEventListener("click", (e) => {
      if (hasUnsavedChanges && !window.confirm("Any changes you haven't exported yet will be lost. Go back to the start page anyway?")) {
        e.preventDefault();
      }
    });
  }

  async function doExport() {
    clearStatus();
    showStatus("Exporting...");
    try {
      const resp = await fetch(`/jobs/${jobId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rooms }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Server error (${resp.status})`);
      }
      const data = await resp.json();
      clearStatus();
      hasUnsavedChanges = false;
      const resultEl = document.getElementById("export-result");
      const link = document.getElementById("download-link");
      link.href = data.download_url;
      resultEl.hidden = false;
      resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      showStatus("Export failed: " + err.message, true);
    }
  }

  init();
})();
