(function () {
  const container = document.getElementById("stage-container");
  const jobId = document.querySelector(".correct-page").dataset.jobId;
  const loadingEl = document.getElementById("loading");
  const statusEl = document.getElementById("status-msg");
  const warningsEl = document.getElementById("warnings");

  const ROOM_COLOR = "#2f6f4f";
  const ROOM_COLOR_SELECTED = "#c9622a";
  const NEW_ID_PREFIX = "new-";

  /** @type {{id:string, bbox:[number,number,number,number], name:string|null, source:string}[]} */
  let rooms = [];
  let imageWidth = 0;
  let imageHeight = 0;
  let fitScale = 1;
  let zoom = 1;
  let tool = "select"; // "select" | "draw"
  let selectedIds = []; // volgorde van selectie, max 2 (voor samenvoegen)

  let stage, bgLayer, roomLayer, transformer;
  const nodesById = new Map(); // room.id -> {group, rect, label}

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

  function showWarnings(list) {
    if (!list || list.length === 0) {
      warningsEl.hidden = true;
      return;
    }
    warningsEl.hidden = false;
    warningsEl.textContent = list.join("\n");
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
      text: room.name || "(geen naam)",
      fontSize: 14 / totalScale(),
      fill: "#1f2320",
      padding: 2,
      x: 2,
      y: 2,
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
    nodes.label.text(room.name || "(geen naam)");
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
      } else if (selectedIds.length < 2) {
        selectedIds.push(id);
      } else {
        selectedIds = [selectedIds[1], id];
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
    document.getElementById("btn-merge").disabled = selectedIds.length !== 2;
  }

  // ---- drag/resize -> state terugschrijven -------------------------------

  function onTransformOrDragEnd(room) {
    const nodes = nodesById.get(room.id);
    if (!nodes) return;
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

    room.bbox = [Math.round(x0), Math.round(y0), Math.round(x0 + width), Math.round(y0 + height)];
    room.source = room.source === "auto" ? "user-edited" : room.source;
  }

  // ---- hernoemen (HTML input overlay op Konva.Text) ----------------------

  function startRename(id) {
    const room = rooms.find((r) => r.id === id);
    const nodes = nodesById.get(id);
    if (!room || !nodes) return;

    const box = nodes.label.getClientRect({ relativeTo: stage });
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
      room.name = input.value.trim() || null;
      if (room.source === "auto") room.source = "user-edited";
      syncNodeToRoom(room);
      document.body.removeChild(input);
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
    transformer.nodes([]); // eerst loskoppelen, anders crasht Konva bij destroy() van een vastgehouden node
    rooms = rooms.filter((r) => !selectedIds.includes(r.id));
    selectedIds.forEach((id) => {
      const nodes = nodesById.get(id);
      if (nodes) nodes.group.destroy();
      nodesById.delete(id);
    });
    selectedIds = [];
    applySelection();
  }

  function mergeSelected() {
    if (selectedIds.length !== 2) return;
    const [a, b] = selectedIds.map((id) => rooms.find((r) => r.id === id));
    if (!a || !b) return;

    const x0 = Math.min(a.bbox[0], b.bbox[0]);
    const y0 = Math.min(a.bbox[1], b.bbox[1]);
    const x1 = Math.max(a.bbox[2], b.bbox[2]);
    const y1 = Math.max(a.bbox[3], b.bbox[3]);

    const suggestedName = a.name || b.name || "";
    const name = window.prompt("Naam voor de samengevoegde ruimte:", suggestedName);
    if (name === null) return; // geannuleerd

    const merged = {
      id: newRoomId(),
      bbox: [x0, y0, x1, y1],
      name: name.trim() || null,
      source: "user-merged",
    };

    transformer.nodes([]); // eerst loskoppelen, anders crasht Konva bij destroy() van een vastgehouden node
    rooms = rooms.filter((r) => r.id !== a.id && r.id !== b.id);
    [a, b].forEach((r) => {
      const nodes = nodesById.get(r.id);
      if (nodes) nodes.group.destroy();
      nodesById.delete(r.id);
    });
    rooms.push(merged);
    buildRoomNode(merged);
    selectedIds = [];
    applySelection();
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
    stage.container().style.cursor = tool === "draw" ? "crosshair" : "grab";
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
      // mousedown EN mouseup van deze teken-actie vonden beide plaats op de
      // achtergrond, dus Konva vuurt hierna nog een synthetische "click" op
      // diezelfde achtergrond af - zonder deze vlag zou de stage-click-
      // handler hieronder de zojuist gezette selectie (en dus de
      // resize-handvatten) meteen weer opheffen.
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
      stage.container().style.cursor = tool === "draw" ? "crosshair" : "grab";
      if (panDetachedNodes.length > 0) {
        transformer.nodes(panDetachedNodes);
        panDetachedNodes = [];
        roomLayer.draw();
      }
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
    setupPanning();

    let resp;
    try {
      resp = await fetch(`/jobs/${jobId}/detect`);
      if (!resp.ok) throw new Error(`Serverfout (${resp.status})`);
    } catch (err) {
      loadingEl.textContent = "Laden mislukt: " + err.message;
      return;
    }
    const data = await resp.json();
    imageWidth = data.width;
    imageHeight = data.height;
    rooms = data.rooms.map((r) => ({ ...r }));
    showWarnings(data.warnings);
    loadingEl.hidden = true;

    const imgObj = new Image();
    imgObj.onload = () => {
      const konvaImg = new Konva.Image({ image: imgObj, name: "bg-image" });
      bgLayer.add(konvaImg);
      fitToContainer();
      redrawAll();
    };
    imgObj.src = data.image_url;

    window.addEventListener("resize", () => {
      fitToContainer();
      roomLayer.draw();
    });

    document.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTool(btn.dataset.tool));
    });
    document.getElementById("btn-delete").addEventListener("click", deleteSelected);
    document.getElementById("btn-merge").addEventListener("click", mergeSelected);
    document.getElementById("btn-zoom-in").addEventListener("click", () => zoomBy(1.25));
    document.getElementById("btn-zoom-out").addEventListener("click", () => zoomBy(0.8));
    document.getElementById("btn-zoom-fit").addEventListener("click", () => {
      fitToContainer();
      roomLayer.draw();
    });
    document.addEventListener("keydown", (e) => {
      if ((e.key === "Delete" || e.key === "Backspace") && selectedIds.length && document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        deleteSelected();
      }
    });

    transformer.on("transformend", () => {
      selectedIds.forEach((id) => {
        const room = rooms.find((r) => r.id === id);
        if (room) onTransformOrDragEnd(room);
      });
    });

    document.getElementById("btn-export").addEventListener("click", doExport);
  }

  async function doExport() {
    clearStatus();
    showStatus("Bezig met exporteren...");
    try {
      const resp = await fetch(`/jobs/${jobId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rooms }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Serverfout (${resp.status})`);
      }
      const data = await resp.json();
      clearStatus();
      const resultEl = document.getElementById("export-result");
      const link = document.getElementById("download-link");
      link.href = data.download_url;
      resultEl.hidden = false;
      resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      showStatus("Export mislukt: " + err.message, true);
    }
  }

  init();
})();
