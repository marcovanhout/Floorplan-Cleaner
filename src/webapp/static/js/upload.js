(function () {
  const form = document.getElementById("upload-form");
  const submitBtn = document.getElementById("upload-submit");
  const status = document.getElementById("upload-status");

  const forceRasterEl = document.getElementById("force_raster");
  const tesseractWarningEl = document.getElementById("tesseract-warning");
  const tesseractAvailable = forceRasterEl.dataset.tesseractAvailable === "true";

  // Alleen relevant zodra iemand MODE B daadwerkelijk afdwingt - voor de
  // normale AutoCAD-PDF's (MODE A, geen OCR nodig) is deze melding ruis.
  forceRasterEl.addEventListener("change", () => {
    tesseractWarningEl.hidden = !(forceRasterEl.checked && !tesseractAvailable);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    status.hidden = false;
    status.classList.remove("error");
    status.textContent = "Bezig met verwerken...";

    try {
      const formData = new FormData(form);
      const resp = await fetch("/upload", { method: "POST", body: formData });
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
