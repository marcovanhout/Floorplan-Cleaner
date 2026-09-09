(function () {
  const form = document.getElementById("upload-form");
  const pdfInput = document.getElementById("pdf");
  const pageInput = document.getElementById("page");
  const scaleInput = document.getElementById("scale");
  const submitBtn = document.getElementById("upload-submit");
  const status = document.getElementById("upload-status");

  const forceRasterEl = document.getElementById("force_raster");
  const tesseractWarningEl = document.getElementById("tesseract-warning");
  const tesseractAvailable = forceRasterEl.dataset.tesseractAvailable === "true";

  const layersLoadingEl = document.getElementById("layers-loading");
  const layersSectionEl = document.getElementById("layers-section");
  const layersListEl = document.getElementById("layers-list");
  const selectAllLink = document.getElementById("layers-select-all");
  const selectNoneLink = document.getElementById("layers-select-none");

  const previewBoxEl = document.getElementById("layers-preview-box");
  const previewImgEl = document.getElementById("layers-preview-img");
  const previewPlaceholderEl = document.getElementById("layers-preview-placeholder");

  // Pas gezet zodra /upload (stap 1: bestand inlezen + lagen inventariseren)
  // is geslaagd - de daadwerkelijke verwerking (submit) heeft dit nodig.
  let currentJobId = null;
  let previewDebounceTimer = null;
  let previewRequestSeq = 0; // negeert trage/oude responses die na een nieuwere aankomen

  // Alleen relevant zodra iemand MODE B daadwerkelijk afdwingt - voor de
  // normale AutoCAD-PDF's (MODE A, geen OCR nodig) is deze melding ruis.
  forceRasterEl.addEventListener("change", () => {
    tesseractWarningEl.hidden = !(forceRasterEl.checked && !tesseractAvailable);
  });

  function renderLayerCheckboxes(layers, recommendedLayers) {
    const recommended = new Set(recommendedLayers);
    layersListEl.innerHTML = "";
    layers.forEach((name) => {
      const label = document.createElement("label");
      label.className = "layer-checkbox";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "layers";
      input.value = name;
      input.checked = recommended.has(name);
      label.appendChild(input);
      label.appendChild(document.createTextNode(" " + name));
      layersListEl.appendChild(label);
    });
  }

  selectAllLink.addEventListener("click", (e) => {
    e.preventDefault();
    layersListEl.querySelectorAll("input[type=checkbox]").forEach((cb) => (cb.checked = true));
    schedulePreview();
  });
  selectNoneLink.addEventListener("click", (e) => {
    e.preventDefault();
    layersListEl.querySelectorAll("input[type=checkbox]").forEach((cb) => (cb.checked = false));
    schedulePreview();
  });

  // ---- laag-voorbeeld (live bijgewerkt bij elke aan/uitgevinkte laag) -----

  function schedulePreview() {
    if (!currentJobId) return;
    clearTimeout(previewDebounceTimer);
    // Kort debounced: bij snel achter elkaar aanklikken van meerdere vakjes
    // hoeft niet elke tussenstap gerenderd te worden, alleen de laatste.
    previewDebounceTimer = setTimeout(updatePreview, 350);
  }

  async function updatePreview() {
    const mySeq = ++previewRequestSeq;
    const checked = Array.from(layersListEl.querySelectorAll("input[type=checkbox]:checked")).map(
      (cb) => cb.value
    );
    previewBoxEl.classList.add("loading");
    try {
      const body = new FormData();
      body.append("page", pageInput.value);
      checked.forEach((name) => body.append("layers", name));
      const resp = await fetch(`/jobs/${currentJobId}/preview`, { method: "POST", body });
      if (mySeq !== previewRequestSeq) return; // ondertussen een nieuwere aanvraag onderweg
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const oldUrl = previewImgEl.src;
      previewImgEl.src = URL.createObjectURL(blob);
      previewImgEl.hidden = false;
      previewPlaceholderEl.hidden = true;
      if (oldUrl && oldUrl.startsWith("blob:")) URL.revokeObjectURL(oldUrl);
    } catch (err) {
      // Een mislukt voorbeeld mag de rest van de flow niet blokkeren - het
      // vorige voorbeeld (indien er een was) blijft gewoon staan.
      console.warn("Voorbeeld renderen mislukt:", err);
    } finally {
      if (mySeq === previewRequestSeq) previewBoxEl.classList.remove("loading");
    }
  }

  layersListEl.addEventListener("change", schedulePreview);
  pageInput.addEventListener("change", schedulePreview);

  async function inspectSelectedFile() {
    currentJobId = null;
    previewRequestSeq++; // eventuele nog lopende preview-aanvraag van een vorig bestand negeren
    submitBtn.disabled = true;
    layersSectionEl.hidden = true;
    layersListEl.innerHTML = "";
    previewImgEl.hidden = true;
    previewPlaceholderEl.hidden = false;
    status.hidden = true;

    const file = pdfInput.files[0];
    if (!file) return;

    layersLoadingEl.hidden = false;
    try {
      const body = new FormData();
      body.append("pdf", file);
      const resp = await fetch("/upload", { method: "POST", body });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Serverfout (${resp.status})`);
      }
      const data = await resp.json();
      currentJobId = data.job_id;
      if (data.layers && data.layers.length > 0) {
        renderLayerCheckboxes(data.layers, data.recommended_layers);
        layersSectionEl.hidden = false;
        updatePreview();
      }
      submitBtn.disabled = false;
    } catch (err) {
      status.hidden = false;
      status.classList.add("error");
      status.textContent = "Bestand inlezen mislukt: " + err.message;
    } finally {
      layersLoadingEl.hidden = true;
    }
  }

  pdfInput.addEventListener("change", inspectSelectedFile);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentJobId) return;
    submitBtn.disabled = true;
    status.hidden = false;
    status.classList.remove("error");
    status.textContent = "Bezig met verwerken...";

    try {
      // Het bestand zelf is al bij /upload verstuurd - hier alleen de
      // instellingen + laagkeuze meesturen, niet nogmaals het hele bestand.
      const body = new FormData();
      body.append("page", pageInput.value);
      body.append("scale", scaleInput.value);
      if (forceRasterEl.checked) body.append("force_raster", "on");
      layersListEl.querySelectorAll("input[type=checkbox]:checked").forEach((cb) => {
        body.append("layers", cb.value);
      });

      const resp = await fetch(`/jobs/${currentJobId}/process`, { method: "POST", body });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Serverfout (${resp.status})`);
      }
      const data = await resp.json();
      window.location.href = data.redirect;
    } catch (err) {
      status.classList.add("error");
      status.textContent = "Mislukt: " + err.message;
      submitBtn.disabled = false;
    }
  });
})();
