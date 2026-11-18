const form = document.querySelector("#form");
const urlInput = document.querySelector("#url");
const submitButton = document.querySelector("#submit");
const formError = document.querySelector("#form-error");
const statusBox = document.querySelector("#status");
const detail = document.querySelector("#detail");
const jobTitle = document.querySelector("#job-title");
const errorBox = document.querySelector("#error");
const gallery = document.querySelector("#gallery");
const stageItems = [...document.querySelectorAll(".stages li")];

const STAGES = ["download", "transcribe", "pick", "render"];
let timer = null;
let startedAt = 0;

function stamp(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const clock = `${minutes}:${String(secs).padStart(2, "0")}`;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : clock;
}

function show(node) {
  node.hidden = false;
}

function hide(node) {
  node.hidden = true;
}

function setStages(stage, status) {
  const active = STAGES.indexOf(stage);
  stageItems.forEach((item, index) => {
    item.classList.remove("active", "done", "failed");
    if (status === "done") {
      item.classList.add("done");
      return;
    }
    if (status === "error" && index === Math.max(active, 0)) {
      item.classList.add("failed");
      return;
    }
    if (active === -1) return;
    if (index < active) item.classList.add("done");
    if (index === active) item.classList.add("active");
  });
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const previous = button.textContent;
  button.textContent = "Copied";
  button.classList.add("copied");
  setTimeout(() => {
    button.textContent = previous;
    button.classList.remove("copied");
  }, 1200);
}

function renderClips(job) {
  gallery.replaceChildren();
  if (!job.clips || !job.clips.length) {
    hide(gallery);
    return;
  }
  job.clips.forEach((clip, position) => {
    const card = document.createElement("article");
    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.poster = clip.thumbnail_url;
    video.src = clip.video_url;
    const meta = document.createElement("div");
    meta.className = "meta";

    const time = document.createElement("p");
    time.className = "time";
    time.textContent = `${stamp(clip.start)} – ${stamp(clip.end)}  ·  clip ${position + 1}`;

    const hookLabel = document.createElement("h2");
    hookLabel.textContent = "Hook";
    const hook = document.createElement("p");
    hook.className = "hook-text";
    hook.textContent = clip.hook;

    const captionLabel = document.createElement("h3");
    captionLabel.textContent = "Caption";
    const caption = document.createElement("p");
    caption.className = "caption";
    caption.textContent = clip.caption;

    const description = document.createElement("p");
    description.className = "desc";
    description.textContent = clip.description;

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
    download.className = "download secondary";
    download.href = clip.video_url;
    download.download = `clip-${position + 1}.mp4`;
    download.textContent = "Download MP4";

    actions.append(copyHook, copyCaption, download);
    meta.append(time, hookLabel, hook, captionLabel, caption, description, actions);
    card.append(video, meta);
    gallery.append(card);
  });
  show(gallery);
}

function paint(job) {
  show(statusBox);
  jobTitle.textContent = job.title || "Working on your link";
  setStages(job.stage, job.status);
  const elapsed = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
  const extra = elapsed ? ` · ${elapsed}s` : "";
  if (job.status === "error") {
    show(errorBox);
    errorBox.textContent = job.error || "The job failed.";
    detail.textContent = "Stopped" + extra;
    hide(gallery);
    submitButton.disabled = false;
    return;
  }
  hide(errorBox);
  if (job.status === "done") {
    detail.textContent = `${job.clips.length} clip${job.clips.length === 1 ? "" : "s"} ready` + extra;
    renderClips(job);
    submitButton.disabled = false;
    return;
  }
  detail.textContent = (job.detail || "Working…") + extra;
}

async function poll(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error("The job could not be loaded.");
  }
  const job = await response.json();
  paint(job);
  if (job.status === "done" || job.status === "error") {
    window.clearInterval(timer);
    timer = null;
  }
}

function track(jobId) {
  if (timer) window.clearInterval(timer);
  startedAt = Date.now();
  sessionStorage.setItem("clip-agent-job", jobId);
  const next = new URL(window.location.href);
  next.searchParams.set("job", jobId);
  window.history.replaceState({}, "", next);
  hide(errorBox);
  gallery.replaceChildren();
  hide(gallery);
  submitButton.disabled = true;
  poll(jobId).catch((error) => {
    show(errorBox);
    errorBox.textContent = error.message;
    submitButton.disabled = false;
  });
  timer = window.setInterval(() => {
    poll(jobId).catch(() => window.clearInterval(timer));
  }, 1200);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(formError);
  const url = urlInput.value.trim();
  if (!url) return;
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const payload = await response.json();
    if (!response.ok) {
      formError.textContent = payload.detail || "That link was rejected.";
      show(formError);
      submitButton.disabled = false;
      return;
    }
    track(payload.id);
  } catch (_error) {
    formError.textContent = "The server did not respond.";
    show(formError);
    submitButton.disabled = false;
  }
});

const existing = new URLSearchParams(window.location.search).get("job") || sessionStorage.getItem("clip-agent-job");
if (existing) track(existing);
