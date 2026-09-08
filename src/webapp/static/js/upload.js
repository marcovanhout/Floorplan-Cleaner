(function () {
  const form = document.getElementById("upload-form");
  const submitBtn = document.getElementById("upload-submit");
  const status = document.getElementById("upload-status");

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
