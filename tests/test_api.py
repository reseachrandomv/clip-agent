"""HTTP API: validate links, queue work, and serve finished clips."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        openai_api_key="",
        openai_base_url="https://example.invalid/v1",
        openai_model="gpt-test",
        whisper_model="tiny",
        max_duration_sec=1200,
        max_upload_mb=50,
        workers=1,
        render_preset="ultrafast",
    )


def test_rejects_non_youtube_urls(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.post("/api/jobs", json={"url": "https://example.com/video.mp4"})
    assert response.status_code == 400
    assert "YouTube" in response.json()["detail"]


def test_health(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/api/health").json()["ok"] is True


def test_job_runs_and_returns_clip_files(tmp_path: Path, monkeypatch):
    """The queue finishes a job and the media routes stream the files."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    def fake_download(url: str, dest: Path, **kwargs):
        from app.download import Download

        video = dest / "source.mp4"
        # A tiny valid mp4 is produced by the render test helper's sibling:
        # write a 2-second silent color clip so ffprobe accepts it.
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x180:d=12",
                "-f",
                "lavfi",
                "-i",
                "sine=f=440:d=12",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(video),
            ],
            check=True,
            capture_output=True,
        )
        vtt = """WEBVTT

00:00:00.000 --> 00:00:05.000
welcome to the show

00:00:05.000 --> 00:00:12.000
haha that was incredible wow what a moment
"""
        return Download(
            path=video,
            title="Sample",
            duration=12.0,
            heatmap=[],
            vtt_text=vtt,
        )

    monkeypatch.setattr("app.pipeline.download_youtube", fake_download)

    created = client.post(
        "/api/jobs",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
    )
    assert created.status_code == 200
    job_id = created.json()["id"]

    # The worker is a thread. Poll until it leaves the queue.
    import time

    payload = None
    for _ in range(240):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"done", "error"}:
            break
        time.sleep(0.5)
    assert payload is not None
    assert payload["status"] == "done", payload
    assert payload["clips"]
    clip = payload["clips"][0]
    assert clip["hook"]
    assert "#shorts" in clip["caption"]
    assert clip["start"] < clip["end"]
    video = client.get(clip["video_url"])
    thumb = client.get(clip["thumb_url"])
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/")
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/")


def test_unknown_job_is_404(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/api/jobs/not-a-real-job").status_code == 404
