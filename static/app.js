const form = document.querySelector("#forge-form");
const fileInput = document.querySelector("#files");
const dropZone = document.querySelector("#drop-zone");
const previews = document.querySelector("#preview-strip");
const workspace = document.querySelector("#workspace");
const progressPanel = document.querySelector("#progress-panel");
const progressMessage = document.querySelector("#progress-message");
const progressNumber = document.querySelector("#progress-number");
const progressBar = document.querySelector("#progress-bar");
const results = document.querySelector("#results");
const dialog = document.querySelector("#image-dialog");

const escapeHtml = (value = "") => value.replace(/[&<>'"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[character]);

function previewFiles(files) {
  previews.innerHTML = "";
  [...files].slice(0, 15).forEach(file => {
    const image = document.createElement("img");
    image.alt = file.name;
    image.src = URL.createObjectURL(file);
    image.onload = () => URL.revokeObjectURL(image.src);
    previews.appendChild(image);
  });
}

fileInput.addEventListener("change", () => previewFiles(fileInput.files));
["dragenter", "dragover"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", event => {
  fileInput.files = event.dataTransfer.files;
  previewFiles(fileInput.files);
});

function updateProgress(message, value) {
  progressMessage.textContent = message;
  progressNumber.textContent = `${value}%`;
  progressBar.style.width = `${value}%`;
}

async function poll(projectId) {
  while (true) {
    const response = await fetch(`/api/projects/${projectId}`);
    const job = await response.json();
    updateProgress(job.message || "Processing", job.progress || 0);
    if (job.status === "complete") return job.result;
    if (job.status === "failed") throw new Error(job.message || "Processing failed");
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!fileInput.files.length) return;
  const body = new FormData(form);
  workspace.classList.add("hidden");
  results.classList.add("hidden");
  progressPanel.classList.remove("hidden");
  updateProgress("Uploading visual evidence", 1);
  try {
    const response = await fetch("/api/projects", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Upload failed");
    const result = await poll(payload.project_id);
    renderResult(result);
  } catch (error) {
    workspace.classList.remove("hidden");
    progressPanel.classList.add("hidden");
    alert(error.message);
  }
});

function renderActions(name, actions) {
  return `<section class="plan-column"><h3>${name}</h3>${actions.map(action => `
    <div class="action-card">
      <strong>${escapeHtml(action.title)}</strong>
      <p>${escapeHtml(action.description)}</p>
      <span class="support ${action.support}">${action.support}</span>
    </div>`).join("") || "<p>No action required.</p>"}</section>`;
}

function renderResult(result) {
  progressPanel.classList.add("hidden");
  results.classList.remove("hidden");
  document.querySelector("#result-headline").textContent = result.plan.headline;
  document.querySelector("#result-summary").textContent = result.plan.summary;
  const retained = result.images.filter(image => !image.duplicate_of).length;
  const corrected = result.images.filter(image => image.corrected_url).length;
  document.querySelector("#stats").innerHTML = `
    <span>${result.images.length} images</span><span>${retained} retained</span>
    <span>${result.duplicate_count} duplicates</span><span>${corrected} corrected</span>
    ${result.demo_mode ? "<span>Demo mode</span>" : "<span>Grounded by Muse</span>"}`;
  document.querySelector("#plan-grid").innerHTML = [
    renderActions("Now", result.plan.now), renderActions("Next", result.plan.next), renderActions("Later", result.plan.later)
  ].join("");
  document.querySelector("#evidence-grid").innerHTML = result.images.map(image => `
    <button class="evidence-card ${image.duplicate_of ? "duplicate" : ""}" data-image-id="${image.image_id}">
      <img src="${image.corrected_url || image.original_url}" alt="${escapeHtml(image.filename)}" />
      <div><strong>${escapeHtml(image.analysis?.title || image.filename)}</strong>
      <span>${image.duplicate_of ? `Duplicate of ${image.duplicate_of}` : image.correction_status.replace("_", " ")}</span></div>
    </button>`).join("");
  document.querySelectorAll(".evidence-card").forEach(button => button.addEventListener("click", () => {
    const image = result.images.find(item => item.image_id === button.dataset.imageId);
    showImage(image);
  }));
  document.querySelector("#missing-list").innerHTML = (result.plan.missing.length ? result.plan.missing : ["Nothing reported."]).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  document.querySelector("#conflict-list").innerHTML = (result.plan.conflicts.length ? result.plan.conflicts.map(item => item.description) : ["No conflicts detected."]).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  results.scrollIntoView({ behavior: "smooth" });
}

function showImage(image) {
  const corrected = image.corrected_url ? `<div><h4>Corrected</h4><img src="${image.corrected_url}" alt="Corrected slide" /></div>` : "";
  document.querySelector("#dialog-content").innerHTML = `<h2>${escapeHtml(image.analysis?.title || image.filename)}</h2>
    <div class="compare-grid"><div><h4>Original</h4><img src="${image.original_url}" alt="Original photo" /></div>${corrected}</div>`;
  dialog.showModal();
}

document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#new-project").addEventListener("click", () => window.location.reload());
