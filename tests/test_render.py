import json
import subprocess
from pathlib import Path

from app.captions import build_ass, cues_for_clip
from app.models import Word
from app.render import next_crf, render_clip


def test_crf_climbs_only_when_the_file_is_over_budget():
    assert next_crf(22, 10_000_000) is None
    assert next_crf(22, 60_000_000) == 30
    assert next_crf(30, 60_000_000) == 36
    assert next_crf(36, 60_000_000) is None


def _make_source(path: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x1a3a8a:s=1280x720:r=15:d={duration},drawbox=x=320:y=160:w=640:h=400:color=white:t=fill",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:d={duration}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
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


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _frame(path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.8",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _pixel(frame: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    index = (y * width + x) * 3
    return tuple(frame[index : index + 3])


def test_render_makes_a_vertical_clip_with_hook_and_audio(tmp_path):
    source = tmp_path / "source.mp4"
    _make_source(source, 8)
    words = [Word(5.2, 5.8, "hello"), Word(5.8, 6.4, "world")]
    ass = tmp_path / "clip.ass"
    ass.write_text(build_ass(cues_for_clip(words, 5, 8), "YELLOW HOOK"), encoding="utf-8")
    video = tmp_path / "clip.mp4"
    thumb = tmp_path / "clip.jpg"
    # Start well into the file so a bad seek would drop the two-second hook.
    render_clip(source, 5, 8, ass, video, thumb, preset="ultrafast", crf=30)

    info = _probe(video)
    video_stream = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    assert any(stream["codec_type"] == "audio" for stream in info["streams"])
    assert video.stat().st_size < 50 * 1024 * 1024
    assert thumb.is_file() and thumb.stat().st_size > 1000

    frame = _frame(video)
    width = 1080
    corner = _pixel(frame, width, 20, 20)
    center = _pixel(frame, width, 540, 960)
    assert corner != center

    yellow = False
    for y in range(120, 320, 3):
        for x in range(180, 900, 6):
            red, green, blue = _pixel(frame, width, x, y)
            if red > 180 and green > 140 and blue < 140 and red > blue + 60:
                yellow = True
                break
        if yellow:
            break
    assert yellow, "hook text was not burned into the top of the frame"
