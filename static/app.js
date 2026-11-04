const form = document.querySelector("#forge-form");
const fileInput = document.querySelector("#files");
const dropZone = document.querySelector("#drop-zone");
const previews = document.querySelector("#preview-strip");
const fileCount = document.querySelector("#file-count");
const formError = document.querySelector("#form-error");
const submitButton = form.querySelector(".forge-button");
const goalInput = document.querySelector("#goal");
const notesInput = document.querySelector("#context-notes");
const goalCount = document.querySelector("#goal-count");
const notesCount = document.querySelector("#notes-count");
const workspace = document.querySelector("#workspace");
const progressPanel = document.querySelector("#progress-panel");
const progressMessage = document.querySelector("#progress-message");
const progressNumber = document.querySelector("#progress-number");
const progressTrack = document.querySelector("#progress-track");
const progressBar = document.querySelector("#progress-bar");
const results = document.querySelector("#results");
const dialog = document.querySelector("#image-dialog");

const maxImages = Number(form.dataset.maxImages || 15);
const SUPPORTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]);
const MAX_BYTES = 20 * 1024 * 1024;
const POLL_INTERVAL_MS = 1200;
const POLL_ATTEMPTS = 400;

const escapeHtml = (value = "") => String(value).replace(/[&<>'">]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[character]);

function showError(message) {
  formError.textContent = message;
  formError.classList.remove("hidden");
}

function clearError() {
  formError.textContent = "";
  formError.classList.add("hidden");
}

function previewFiles() {
  previews.innerHTML = "";
  const files = [...fileInput.files];
  fileCount.textContent = files.length
    ? `${files.length} of ${maxImages} image${files.length === 1 ? "" : "s"} selected`
    : "No images selected";
  files.forEach((file, index) => {
    const item = document.createElement("span");
    item.className = "preview-item";
    const image = document.createElement("img");
    image.alt = file.name;
    image.title = file.name;
    image.src = URL.createObjectURL(file);
    image.onload = () => URL.revokeObjectURL(image.src);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "preview-remove";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      const kept = new DataTransfer();
      [...fileInput.files].forEach((candidate, candidateIndex) => {
        if (candidateIndex !== index) kept.items.add(candidate);
      });
      fileInput.files = kept.files;
      clearError();
      previewFiles();
    });
    item.append(image, remove);
    previews.appendChild(item);
  });
}

function validateFiles(files) {
  if (!files.length) return "Choose at least one image to continue.";
  if (files.length > maxImages) return `Choose no more than ${maxImages} images.`;
  const badType = [...files].find(file => file.type && !SUPPORTED_TYPES.has(file.type));
  if (badType) return `${badType.name} is not supported. Use JPG, PNG, WebP, or HEIC.`;
  const tooBig = [...files].find(file => file.size > MAX_BYTES);
  if (tooBig) return `${tooBig.name} is larger than 20 MB.`;
  return null;
}

function updateCount(input, target) {
  const max = Number(input.maxLength) > 0 ? Number(input.maxLength).toLocaleString() : "∞";
  target.textContent = `${input.value.length.toLocaleString()} / ${max}`;
}

fileInput.addEventListener("change", () => { clearError(); previewFiles(); });
["dragenter", "dragover"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", event => {
  clearError();
  const dropped = new DataTransfer();
  [...event.dataTransfer.files].slice(0, maxImages).forEach(file => dropped.items.add(file));
  fileInput.files = dropped.files;
  previewFiles();
});

goalInput.addEventListener("input", () => updateCount(goalInput, goalCount));
notesInput.addEventListener("input", () => updateCount(notesInput, notesCount));
updateCount(goalInput, goalCount);
updateCount(notesInput, notesCount);

function updateProgress(message, value) {
  progressMessage.textContent = message;
  progressNumber.textContent = `${value}%`;
  progressBar.style.width = `${value}%`;
  progressTrack.setAttribute("aria-valuenow", String(value));
}

async function poll(projectId) {
  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    const response = await fetch(`/api/projects/${projectId}`);
    if (!response.ok) throw new Error("Lost contact with the project. Please try again.");
    const job = await response.json();
    updateProgress(job.message || "Processing", job.progress || 0);
    if (job.status === "complete") return job.result;
    if (job.status === "failed") throw new Error(job.message || "Processing failed");
    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error("Processing timed out. Please try again.");
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  clearError();
  const error = validateFiles(fileInput.files);
  if (error) { showError(error); return; }
  const body = new FormData(form);
  submitButton.disabled = true;
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
  } catch (requestError) {
    workspace.classList.remove("hidden");
    progressPanel.classList.add("hidden");
    showError(requestError.message);
  } finally {
    submitButton.disabled = false;
  }
});

function renderActions(name, actions) {
  return `<section class="plan-column"><h3>${escapeHtml(name)}</h3>${actions.map(action => `
    <div class="action-card">
      <strong>${escapeHtml(action.title)}</strong>
      <p>${escapeHtml(action.description)}</p>
      <span class="support ${escapeHtml(action.support)}">${escapeHtml(action.support)}</span>
    </div>`).join("") || "<p>No action required.</p>"}</section>`;
}

function renderList(items, emptyMessage) {
  const values = Array.isArray(items) ? items : [];
  return (values.length ? values : [emptyMessage]).map(item => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderCompactAction(action) {
  if (!action) return "<p class=\"empty-copy\">Muse did not propose a task.</p>";
  const sources = (action.evidence_ids || []).map(id => `<span>${escapeHtml(id)}</span>`).join("");
  return `<div class="compact-action">
    <strong>${escapeHtml(action.title)}</strong>
    <p>${escapeHtml(action.description)}</p>
    <div class="action-meta"><span class="support ${escapeHtml(action.support)}">${escapeHtml(action.support)}</span>${sources}</div>
  </div>`;
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
  document.querySelector("#evidence-grid").innerHTML = result.images.map((image, index) => `
    <button class="evidence-card ${index === 0 ? "feature" : ""} ${image.duplicate_of ? "duplicate" : ""}" data-image-id="${image.image_id}">
      <img src="${image.corrected_url || image.original_url}" alt="${escapeHtml(image.filename)}" />
      <div class="evidence-copy"><span class="folio">${String(index + 1).padStart(2, "0")} · ${escapeHtml(image.image_id)}</span>
      <strong>${escapeHtml(image.analysis?.title || image.filename)}</strong>
      <p>${escapeHtml(image.analysis?.key_points?.[0] || image.analysis?.topic || "Visual source")}</p>
      <span>${image.duplicate_of ? `Duplicate of ${escapeHtml(image.duplicate_of)}` : escapeHtml(String(image.correction_status || "processed").replace(/_/g, " "))}</span></div>
    </button>`).join("");
  document.querySelectorAll(".evidence-card").forEach(button => button.addEventListener("click", () => {
    const image = result.images.find(item => item.image_id === button.dataset.imageId);
    showImage(image);
  }));

  const themes = result.plan.themes || [];
  document.querySelector("#theme-grid").innerHTML = themes.length ? themes.map(theme => `
    <article class="theme-item">
      <span class="support ${escapeHtml(theme.support)}">${escapeHtml(theme.support)}</span>
      <h5>${escapeHtml(theme.title)}</h5>
      <p>${escapeHtml(theme.insight)}</p>
      <div class="source-ids">${(theme.evidence_ids || []).map(id => `<span>${escapeHtml(id)}</span>`).join("")}</div>
    </article>`).join("") : "<p class=\"empty-copy\">No cross-image theme was reported.</p>";

  document.querySelector("#notes-list").innerHTML = renderList(
    result.plan.notes_takeaways,
    result.context_notes ? "No separate transcript takeaway was reported." : "No notes or transcript were supplied."
  );

  const blueprint = result.plan.blueprint || {};
  document.querySelector("#blueprint-problem").textContent = blueprint.problem_statement || "Not established by the supplied evidence.";
  document.querySelector("#blueprint-user").textContent = blueprint.target_user || "Not established by the supplied evidence.";
  document.querySelector("#scope-list").innerHTML = renderList(blueprint.mvp_scope, "No MVP scope was proposed.");
  document.querySelector("#architecture-list").innerHTML = renderList(blueprint.architecture, "No architecture was proposed.");
  document.querySelector("#backlog-list").innerHTML = (blueprint.backlog || []).map(renderCompactAction).join("") || "<p class=\"empty-copy\">No backlog item was proposed.</p>";
  document.querySelector("#first-task").innerHTML = `<span>START HERE</span>${renderCompactAction(blueprint.first_task)}`;

  document.querySelector("#missing-list").innerHTML = (result.plan.missing.length ? result.plan.missing : ["Nothing reported."]).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  document.querySelector("#conflict-list").innerHTML = (result.plan.conflicts.length ? result.plan.conflicts.map(item => item.description) : ["No conflicts detected."]).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  results.scrollIntoView({ behavior: "smooth" });
}

function showImage(image) {
  const corrected = image.corrected_url ? `<div><h4>Corrected</h4><img src="${image.corrected_url}" alt="Corrected slide" /></div>` : "";
  const analysis = image.analysis;
  const analysisCopy = analysis ? `<div class="analysis-copy">
      <p class="analysis-topic">${escapeHtml(analysis.topic)}</p>
      <h3>What Muse found</h3>
      <ul>${renderList(analysis.key_points, "No key point reported.")}</ul>
      <h3>Evidence note</h3>
      <p>${escapeHtml(analysis.evidence_note)}</p>
      ${analysis.missing_context?.length ? `<h3>Missing context</h3><ul>${renderList(analysis.missing_context, "")}</ul>` : ""}
    </div>` : "";
  document.querySelector("#dialog-content").innerHTML = `<h2>${escapeHtml(image.analysis?.title || image.filename)}</h2>
    <div class="compare-grid"><div><h4>Original</h4><img src="${image.original_url}" alt="Original photo" /></div>${corrected}</div>${analysisCopy}`;
  dialog.showModal();
}

document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
document.querySelector("#new-project").addEventListener("click", () => window.location.reload());

const themeToggle = document.querySelector("#theme-toggle");

function applyTheme(theme) {
  const light = theme === "light";
  if (light) document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
  themeToggle.setAttribute("aria-pressed", String(light));
  themeToggle.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
  try {
    localStorage.setItem("signalforge-theme", light ? "light" : "dark");
  } catch {
    /* Private mode: the theme applies for this visit without persisting. */
  }
}

themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});
applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");

const existingProject = new URLSearchParams(window.location.search).get("project");
if (existingProject) {
  workspace.classList.add("hidden");
  progressPanel.classList.remove("hidden");
  updateProgress("Loading compiled report", 5);
  poll(existingProject).then(renderResult).catch(error => {
    progressPanel.classList.add("hidden");
    workspace.classList.remove("hidden");
    alert(error.message);
  });
}
