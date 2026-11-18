import time

from app.youtube import is_youtube_url


def test_youtube_urls():
    accepted = [
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk",
        "https://m.youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://youtube.com/watch?v=abcdefghijk&t=3s",
        "https://www.youtube.com/embed/abcdefghijk",
    ]
    rejected = [
        "https://vimeo.com/123456",
        "not a url",
        "https://youtube.com.evil.com/watch?v=abcdefghijk",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch?v=ab",
    ]
    assert all(is_youtube_url(url) for url in accepted)
    assert not any(is_youtube_url(url) for url in rejected)


def test_health_and_homepage(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Clip Agent" in page.text
    assert "Cut the part people replay." in page.text


def test_rejects_a_non_youtube_link(client):
    response = client.post("/api/jobs", json={"url": "https://example.com/video"})
    assert response.status_code == 400


def test_missing_job(client):
    assert client.get("/api/jobs/missing").status_code == 404


def test_job_runs_in_the_background(client, monkeypatch):
    def fake_run(job_id, store, _settings):
        store.update(
            job_id,
            status="done",
            stage="render",
            detail="Ready",
            title="Sample",
            clips=[
                {
                    "index": 0,
                    "start": 1.0,
                    "end": 21.0,
                    "description": "Something happens.",
                    "hook": "Hello there",
                    "caption": "Hello\n\n#Shorts",
                    "video": "clip-1.mp4",
                    "thumbnail": "clip-1.jpg",
                }
            ],
        )

    monkeypatch.setattr("app.pipeline.run_job", fake_run)
    created = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    body = {}
    for _ in range(40):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert body["title"] == "Sample"
    assert body["clips"][0]["hook"] == "Hello there"
    assert body["clips"][0]["video_url"].endswith("/video")
    assert body["clips"][0]["thumbnail_url"].endswith("/thumbnail")


def test_clip_download(client):
    store = client.app.state.store
    job = store.create("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    folder = store.job_dir(job["id"])
    (folder / "clip-1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / "clip-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    store.update(
        job["id"],
        status="done",
        clips=[
            {
                "index": 0,
                "start": 0,
                "end": 20,
                "description": "Desc",
                "hook": "Hook",
                "caption": "Cap",
                "video": "clip-1.mp4",
                "thumbnail": "clip-1.jpg",
            }
        ],
    )
    video = client.get(f"/api/jobs/{job['id']}/clips/0/video")
    thumb = client.get(f"/api/jobs/{job['id']}/clips/0/thumbnail")
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")
    assert "inline" in video.headers["content-disposition"]
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/jpeg")
    assert client.get(f"/api/jobs/{job['id']}/clips/3/video").status_code == 404
