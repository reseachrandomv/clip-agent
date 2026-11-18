# Clip Agent

Paste a YouTube link. Get back 3–5 vertical shorts, ready for YouTube Shorts.

Each clip is 15–35 seconds, 1080×1920, with the 16:9 picture centred on a blurred fill, burned-in captions, a short hook for the first two seconds, and the original audio. Clips stay under about 50MB.

**Only clip videos you have the rights to, or explicit permission to cut for a campaign.** Clip Agent is a self-hosted editor, not a service for downloading other people's work.

## How a clip is made

1. **Download** with [yt-dlp](https://github.com/yt-dlp/yt-dlp), preferring 720p–1080p. The container also includes Deno, which current yt-dlp needs for YouTube.
2. **Transcript** from YouTube captions (json3 or WebVTT) when they exist. Otherwise the audio is transcribed locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
3. **Moments** from YouTube's most-replayed heatmap when yt-dlp provides it (`heatmap` on the info dict: `start_time`, `end_time`, `value`), plus transcript cues for laughter, shouting, reactions, and punchlines. If `OPENAI_API_KEY` is set, an OpenAI-compatible chat API scores the candidate windows and writes the hook, description, and caption. With no key, the same fields come from the heuristics.
4. **Render** with ffmpeg: blurred background, centred source, ASS captions, hook text on screen from 0–2s, AAC audio, H.264, faststart.

The browser only talks to a small job queue. A background worker does the slow part, so a long video does not hold the HTTP request open.

GitHub Pages cannot run this. Pages serves static files only: no Python, no ffmpeg, no yt-dlp, and no worker for a multi-minute render.

## Run it with Docker

Docker is the intended way to run Clip Agent. The image contains ffmpeg, fonts, yt-dlp, Deno, and faster-whisper.

```bash
cp .env.example .env   # optional; heuristics run fine with the blanks
docker compose up --build
```

Open http://localhost:8000 and paste a link. Finished jobs and the whisper model live in the `clip-data` volume, mounted at `/data`.

API sketch:

```bash
curl -s -X POST localhost:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}'

curl -s localhost:8000/api/jobs/JOB_ID
```

Interactive docs are at http://localhost:8000/docs.

Videos longer than `MAX_DURATION_SECONDS` (default 30 minutes) are refused so a small host can finish.

## Run it without Docker

You need Python 3.12, ffmpeg on `PATH`, and the DejaVu fonts (the captions name `DejaVu Sans`).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The render test builds a local 16:9 sample with ffmpeg and checks the output is 1080×1920, has audio, stays under 50MB, and has the hook burned into the top of the frame. It does not call YouTube.

To fill the gallery with that same local pipeline (useful when YouTube refuses the server):

```bash
python -m app.demo
# prints a job id; open http://localhost:8000/?job=THAT_ID
```

## If YouTube blocks the download

yt-dlp breaks whenever YouTube changes its player. A datacenter IP is also more likely to get a bot check than a home connection. The job ends in an error and the message from yt-dlp is shown in the UI. Updating the image (`docker compose build --no-cache`) picks up a newer yt-dlp. Caption-less videos need the whisper model, which downloads on first use into `/data/models`.

From this project's build environment, a normal public video (`https://www.youtube.com/watch?v=jNQXAC9IVRw`, "Me at the zoo") never produced a file.

On the host, yt-dlp returned immediately:

```text
ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you’re not a bot.
```

Inside Docker, the same request hung on "Downloading webpage" and never reached an error. Clip Agent kills a metadata request that runs longer than 50 seconds and shows that in the job, instead of leaving the spinner up. Alternate player clients on the host returned the same bot check. There are no YouTube cookies here, and the app does not try to get around a bot check. On a residential connection the same URL can still download. The render path was checked with a generated 16:9 sample instead: `pytest` covers it, and `python -m app.demo` drops finished clips into the gallery.

## Deploy

Use any host that can run a Docker container with ffmpeg and a couple of gigabytes of RAM. Whisper on CPU wants about 2GB. Put a persistent disk on `/data` so finished clips and the model survive restarts. Keep the service off the public internet unless you are ready to police what gets submitted.

Set `OPENAI_API_KEY` only if you want the model pass. Leave it empty to stay on the heuristic picker.

### Render

New **Web Service**, environment **Docker**, root directory this repo. Instance with at least 2GB RAM. Add a disk mounted at `/data`. Health check path: `/api/health`. The free instance type is usually too small and it sleeps, which kills a render; a paid instance in the few-dollars-a-month range is the one that finishes jobs.

### Railway

New project from this repo. Railway reads the Dockerfile. Add a volume mounted at `/data`. Set the same variables as `.env.example`.

### Fly.io

A starter [`fly.toml`](fly.toml) is included. Change `app`, then:

```bash
fly launch --no-deploy
fly volumes create clip_data --size 5 --region iad
fly secrets set OPENAI_API_KEY=sk-...   # optional
fly deploy
```

`auto_stop_machines` is off so a job is not killed when the HTTP connection is idle.

### Hugging Face Spaces

Create a **Docker** Space and push this repo. In the Space README front matter:

```yaml
---
title: Clip Agent
emoji: "🎬"
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
---
```

Spaces disk is ephemeral unless you attach persistent storage. The free CPU tier can be tight for whisper; clips that already have YouTube captions skip that step. Set `WHISPER_MODEL=tiny` in the Space secrets if you do need local transcription there.

## Configuration

| Variable | Default | Role |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Turns on LLM scoring and copy. Empty uses heuristics. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible `/chat/completions` base URL. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name sent to that API. |
| `WHISPER_MODEL` | `base` | faster-whisper model. `tiny` is lighter. |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda`. |
| `WHISPER_COMPUTE_TYPE` | `int8` | Compute type passed to faster-whisper. |
| `DATA_DIR` | `./data` | Jobs, renders, and the model cache. |
| `MAX_DURATION_SECONDS` | `1800` | Longest source video accepted. |

## Layout

- `app/main.py` — FastAPI routes and the UI
- `app/worker.py` — one background job at a time
- `app/youtube.py` — yt-dlp download, heatmap, captions
- `app/moments.py` — window scoring
- `app/llm.py` — optional model pass
- `app/render.py` — the ffmpeg vertical cut
- `app/static/` — the page
