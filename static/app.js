const form = document.querySelector("#url-form");
const fileForm = document.querySelector("#file-form");
const urlInput = document.querySelector("#url");
const fileInput = document.querySelector("#file");
const submit = document.querySelector("#submit");
const formError = document.querySelector("#form-error");
const statusEl = document.querySelector("#status");
const steps = [...document.querySelectorAll(".steps li")];
const messageEl = document.querySelector("#message");
const bar = document.querySelector("#bar");
const titleEl = document.querySelector("#job-title");
const results = document.querySelector("#results");
const grid = document.querySelector("#grid");
const resultsMeta = document.querySelector("#results-meta");

const order = ["download", "transcribe", "pick", "render", "done"];
let timer = null;

function showError(text) {
  formError.hidden = !text;
  formError.textContent = text || "";
}

function setBusy(busy) {
  submit.disabled = busy;
  urlInput.disabled = busy;
  fileInput.disabled = busy;
}

function stamp(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const remain = String(total % 60).padStart(2, "0");
  return `${minutes}:${remain}`;
}

function paintStatus(job) {
  statusEl.hidden = false;
  titleEl.textContent = job.title || "Working";
  messageEl.textContent = job.message || "";
  messageEl.classList.toggle("error", job.status === "error");
  bar.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
  const current = order.indexOf(job.stage);
  steps.forEach((step) => {
    const at = order.indexOf(step.dataset.stage);
    step.classList.remove("active", "done", "failed");
    if (job.status === "error" && at === Math.max(current, 0)) step.classList.add("failed");
    else if (job.stage === "done" || (current > at && current !== -1)) step.classList.add("done");
    else if (step.dataset.stage === job.stage) step.classList.add("active");
  });
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_err) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const previous = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => {
    button.textContent = previous;
  }, 1200);
}

function paintClips(job) {
  if (!job.clips || !job.clips.length) {
    results.hidden = true;
    return;
  }
  results.hidden = false;
  const count = job.clips.length;
  resultsMeta.textContent = `${count} clip${count === 1 ? "" : "s"}`;
  grid.innerHTML = "";
  job.clips.forEach((clip, position) => {
    const card = document.createElement("article");
    card.className = "card";
    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.poster = clip.thumb_url;
    video.src = clip.video_url;
    const body = document.createElement("div");
    body.className = "card-body";
    const time = document.createElement("div");
    time.className = "time";
    time.textContent = `${stamp(clip.start)} – ${stamp(clip.end)}`;
    const hook = document.createElement("h3");
    hook.className = "hook";
    hook.textContent = clip.hook;
    const description = document.createElement("p");
    description.className = "description";
    description.textContent = clip.description;
    const caption = document.createElement("p");
    caption.className = "caption";
    caption.textContent = clip.caption;
    const actions = document.createElement("div");
    actions.className = "actions";
    const copyHook = document.createElement("button");
    copyHook.type = "button";
    copyHook.className = "copy";
    copyHook.textContent = "Copy hook";
    copyHook.addEventListener("click", () => copyText(clip.hook, copyHook));
    const copyCaption = document.createElement("button");
    copyCaption.type = "button";
    copyCaption.className = "copy";
    copyCaption.textContent = "Copy caption";
    copyCaption.addEventListener("click", () => copyText(clip.caption, copyCaption));
    const download = document.createElement("a");
    download.className = "download";
    download.href = clip.video_url;
    download.download = `clip-${position + 1}.mp4`;
    download.textContent = "Download";
    actions.append(copyHook, copyCaption, download);
    body.append(time, hook, description, caption, actions);
    card.append(video, body);
    grid.append(card);
  });
}

async function poll(id) {
  const response = await fetch(`/api/jobs/${id}`);
  if (!response.ok) throw new Error("The job disappeared.");
  const job = await response.json();
  paintStatus(job);
  if (job.status === "done") {
    setBusy(false);
    paintClips(job);
    return;
  }
  if (job.status === "error") {
    setBusy(false);
    showError(job.error || job.message);
    return;
  }
  timer = setTimeout(() => {
    poll(id).catch((error) => {
      setBusy(false);
      showError(error.message);
    });
  }, 1000);
}

async function start(response) {
  if (!response.ok) {
    let detail = "Could not start that job.";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_err) {
      /* keep the fallback */
    }
    throw new Error(detail);
  }
  const job = await response.json();
  location.hash = `job=${job.id}`;
  results.hidden = true;
  grid.innerHTML = "";
  showError("");
  setBusy(true);
  paintStatus(job);
  if (timer) clearTimeout(timer);
  poll(job.id).catch((error) => {
    setBusy(false);
    showError(error.message);
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  showError("");
  setBusy(true);
  fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: urlInput.value.trim() }),
  })
    .then(start)
    .catch((error) => {
      setBusy(false);
      showError(error.message);
    });
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;
  showError("");
  setBusy(true);
  const body = new FormData();
  body.append("file", file);
  fetch("/api/jobs/upload", { method: "POST", body })
    .then(start)
    .catch((error) => {
      setBusy(false);
      showError(error.message);
    });
});

const existing = new URLSearchParams(location.hash.replace(/^#/, "")).get("job");
if (existing) {
  setBusy(true);
  poll(existing).catch((error) => {
    setBusy(false);
    showError(error.message);
  });
}
