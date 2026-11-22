"""YouTube URLs are the only remote sources the downloader will touch."""

import pytest

from app.download import heatmap_from_info, validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://m.youtube.com/watch?v=abcdefghijk&t=12s",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://www.youtube.com/live/abcdefghijk",
    ],
)
def test_accepts_common_youtube_urls(url: str):
    assert validate_youtube_url(f"  {url}  ") == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=abcdefghijk",
        "https://www.youtube.com/watch?v=short",
        "file:///etc/passwd",
        "https://evil.youtube.com.attacker.test/watch?v=abcdefghijk",
        "https://youtu.be/",
    ],
)
def test_rejects_urls_that_are_not_a_video(url: str):
    with pytest.raises(ValueError):
        validate_youtube_url(url)


def test_a_stuck_download_gives_up(tmp_path, monkeypatch):
    import time

    from app.download import DownloadError, download_youtube

    def hang(url, dest):
        time.sleep(5)

    monkeypatch.setattr("app.download._download_blocking", hang)
    with pytest.raises(DownloadError, match="too long"):
        download_youtube("https://www.youtube.com/watch?v=abcdefghijk", tmp_path, timeout=0.2)


def test_heatmap_points_come_from_yt_dlp_info():
    info = {
        "heatmap": [
            {"start_time": 1.5, "end_time": 4.0, "value": 0.8},
            {"start_time": "nope", "end_time": 2, "value": 1},
            {"value": 1},
        ]
    }
    points = heatmap_from_info(info)
    assert len(points) == 1
    assert points[0].start == 1.5
    assert points[0].end == 4.0
    assert points[0].value == 0.8
