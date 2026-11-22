"""ffmpeg render: 9:16 frame, centred source, original audio, small file."""

import json
import subprocess
from pathlib import Path

from app.render import probe, render_clip
from app.subs import write_ass
from app.transcript import Segment


def _source(path: Path, duration: float = 6.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=30:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_render_makes_vertical_clip_with_audio_and_thumbnail(tmp_path: Path):
    source = tmp_path / "source.mp4"
    _source(source, 6)
    ass = tmp_path / "captions.ass"
    write_ass(
        ass,
        segments=[Segment(0.2, 3.5, "look at this finish")],
        hook="Look at this",
        clip_start=0.0,
        clip_end=5.0,
    )
    video = tmp_path / "clip.mp4"
    thumb = tmp_path / "clip.jpg"
    render_clip(source, 0.0, 5.0, ass, video, thumb, preset="ultrafast")

    meta = probe(video)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.has_audio
    assert 4.5 <= meta.duration <= 5.5
    assert video.stat().st_size < 50 * 1024 * 1024
    assert thumb.exists()
    assert thumb.stat().st_size > 1000

    # The thumbnail is a jpeg frame, not an empty file.
    info = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height,codec_name",
                "-of",
                "json",
                str(thumb),
            ]
        )
    )
    stream = info["streams"][0]
    assert stream["codec_name"] == "mjpeg"
    assert stream["width"] == 1080
    assert stream["height"] == 1920
