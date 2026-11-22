# Clip Agent

Paste a YouTube link. Get back 3–5 vertical clips framed for YouTube Shorts: 1080×1920, original audio, a blurred fill behind the 16:9 picture, a short hook for the first two seconds, and burned-in captions.

**Only clip videos you have the rights to, or explicit permission to cut for a campaign.** Clip Agent does not grant any rights to the source.

GitHub Pages cannot run this app. Pages only hosts static files. There is no Python process, no ffmpeg, and no yt-dlp. Use Docker on a machine or a host that can run a container (Render, Railway, Fly.io, or a Hugging Face Docker Space).

## What it does

1. **Download** the video with yt-dlp, preferring 720p–1080p mp4.
2. **Transcribe** from YouTube captions when they exist. Otherwise transcribe locally with faster-whisper.
3. **Pick moments** from YouTube’s “most replayed” heatmap (when yt-dlp provides it) and from transcript signals: laughter, shouting, strong reactions, punchlines. If `OPENAI_API_KEY` is set, an OpenAI-compatible chat model scores windows and writes the hook, description, and caption. With no key, the heuristic scorer does that work.
4. **Render** each clip with ffmpeg. Clips are 15–35 seconds (shorter only when the source itself is shorter than 15 seconds), under about 50MB, with the original audio.

Each finished clip includes the mp4, a thumbnail jpg, the source start and end, a description of what happens, a hook under 8 words, and a caption with hashtags.

Long videos run on a background queue so the request does not time out. The page polls until the clips are ready. Videos longer than `MAX_DURATION_SEC` (default 20 minutes) are refused, so a small host can finish.

YouTube often blocks downloads from cloud IPs. The page also accepts an upload of a video you already have the rights to use. Uploads skip the heatmap (YouTube does not send it) and use the transcript signals instead.

## Run with Docker

ffmpeg, yt-dlp, and faster-whisper are in the image.

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000.

Jobs are stored in the `clip-data` volume, mounted at `/data`.

## Run without Docker

You need Python 3.11+, ffmpeg on `PATH`, and a fontconfig install that includes DejaVu Sans (the caption font).

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

The tests build a short local video with ffmpeg and run it through moment picking, caption burn-in, and the HTTP queue. They do not call YouTube.

## Configuration

See `.env.example`.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Optional. Leave empty to use heuristics only. |
| `OPENAI_BASE_URL` | Any OpenAI-compatible `/v1` base URL. |
| `OPENAI_MODEL` | Chat model name. Default `gpt-4o-mini`. |
| `WHISPER_MODEL` | faster-whisper model when captions are missing. Use `tiny` on a 1GB host, `base` otherwise. |
| `MAX_DURATION_SEC` | Longest source video accepted. Default `1200`. |
| `MAX_UPLOAD_MB` | Upload limit. Default `500`. |
| `DATA_DIR` | Job files. Docker uses `/data`. |
| `RENDER_PRESET` | x264 preset. Default `veryfast`. |
| `CLIP_WORKERS` | Jobs rendered at once. Keep `1` on a small VPS. |
| `DOWNLOAD_TIMEOUT_SEC` | Give up on a YouTube download that never finishes. Default `300`. |
| `PORT` | HTTP port. Default `8000`. |

## Deploy

The container listens on `PORT` (8000 by default) and needs enough RAM for ffmpeg. Budget about 1GB. The image already includes the `base` whisper model, so a video with no captions can be transcribed without another download. If you set `WHISPER_MODEL` to something else (`tiny`, `small`), that model is downloaded on first use.

### Render

Create a **Web Service** using the Docker runtime (not the static site type). Set the env vars above. The free instance has little RAM and an ephemeral disk: finished clips disappear when the instance restarts, and a long render can be killed. A paid instance with a persistent disk mounted at `/data` is the reliable option.

### Railway

Create a project from this repo. Railway detects the Dockerfile. Set the env vars. Attach a volume mounted at `/data` if jobs should survive deploys. Railway sets `PORT`; the image already honors it.

### Fly.io

```bash
fly launch --no-deploy
fly deploy
```

In `fly.toml`, set `internal_port` to the port the process listens on (`8000`, unless you set `PORT`). Give the machine at least 1GB of RAM (`fly scale memory 2048` is safer with whisper `base`).

### Hugging Face Spaces

Create a **Docker** Space and push this repo. Static Spaces will not work. Spaces expect port **7860**, so set the Space variable `PORT=7860`. Pick a CPU instance with at least 2GB of RAM if you leave `WHISPER_MODEL=base`, or set `WHISPER_MODEL=tiny` on a smaller one. The Space disk is ephemeral.

### Not GitHub Pages

GitHub Pages serves the files in a branch. It will not build this Dockerfile, run FastAPI, or invoke ffmpeg. Do not point a Pages site at this repo and expect it to clip video.

## YouTube from a server

Datacenter IP addresses are often blocked by YouTube. From this project’s build environment, yt-dlp 2026.10.26 failed on a public video (`https://www.youtube.com/watch?v=jNQXAC9IVRw`) with:

> Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies.

The job surfaces that as a failed download and tells you to upload the file instead. Upload works without YouTube: `docker compose up` on this project processed a generated 96-second video into four 1080×1920 clips, and a second upload with no captions was transcribed by the baked-in whisper model. A home connection, or cookies you are allowed to use, is more reliable for yt-dlp. Do not commit cookies or API keys.

When YouTube is reachable, the same pipeline downloads 720p–1080p, reads captions (or runs faster-whisper), reads the most-replayed heatmap when yt-dlp includes it, and renders the clips.
