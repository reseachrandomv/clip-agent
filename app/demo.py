"""Build a finished job from a generated sample, for local checks when YouTube is blocked."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.captions import build_ass, cues_for_clip
from app.config import Settings
from app.models import Word
from app.moments import select_moments
from app.render import render_clip
from app.store import JobStore


def generate_source(path: Path, duration: float = 90) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
            (
                f"color=c=0x243044:s=1280x720:r=12:d={duration},"
                "drawbox=x=80:y=80:w=1120:h=560:color=0x31506e:t=fill,"
                "drawbox=x=460:y=220:w=360:h=220:color=0xf4f0e6:t=fill"
            ),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:sample_rate=48000:d={duration}",
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
    )


def sample_words() -> list[Word]:
    words: list[Word] = []

    def add(start: float, text: str) -> None:
        for index, token in enumerate(text.split()):
            begin = start + index * 0.34
            words.append(Word(begin, begin + 0.32, token))

    add(2, "We stopped people on the street and asked one question.")
    add(8, "OH MY GOD that was insane hahaha!")
    add(26, "The next person almost walked past the camera.")
    add(44, "Wait what. No way. This is the line.")
    add(66, "Then the whole group started laughing again hahaha.")
    add(82, "She turned around and told the rest of the story.")
    return words


def sample_heatmap() -> list[dict]:
    hot = ((8, 16), (42, 52), (64, 74))
    points = []
    start = 0
    while start < 90:
        value = 1.0 if any(begin <= start < end for begin, end in hot) else 0.04
        points.append({"start_time": start, "end_time": start + 2, "value": value})
        start += 2
    return points


def build_demo(settings: Settings, *, preset: str = "veryfast") -> str:
    """Render the sample through the same picker and ffmpeg path the worker uses."""

    store = JobStore(settings.data_dir)
    job = store.create("https://www.youtube.com/watch?v=clipagentdemo")
    store.update(job["id"], status="rendering", stage="render", detail="Building the sample…")
    folder = store.job_dir(job["id"])
    source = folder / "source.mp4"
    generate_source(source, 90)
    words = sample_words()
    duration = 90.0
    moments = select_moments(words, sample_heatmap(), duration, title="Street interview")
    clips = []
    for index, moment in enumerate(moments):
        ass_path = folder / f"clip-{index + 1}.ass"
        video_name = f"clip-{index + 1}.mp4"
        thumb_name = f"clip-{index + 1}.jpg"
        cues = cues_for_clip(words, moment.start, moment.end)
        ass_path.write_text(build_ass(cues, moment.hook), encoding="utf-8")
        render_clip(
            source,
            moment.start,
            moment.end,
            ass_path,
            folder / video_name,
            folder / thumb_name,
            preset=preset,
        )
        clips.append(
            {
                "index": index,
                "start": moment.start,
                "end": moment.end,
                "description": moment.description,
                "hook": moment.hook,
                "caption": moment.caption,
                "video": video_name,
                "thumbnail": thumb_name,
            }
        )
    store.update(
        job["id"],
        status="done",
        stage="render",
        detail="Ready",
        title="Sample street interview",
        duration=duration,
        clips=clips,
        error=None,
    )
    return job["id"]


def main() -> None:
    settings = Settings.from_env()
    job_id = build_demo(settings)
    print(job_id)


if __name__ == "__main__":
    main()
