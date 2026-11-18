"""Burned-in caption file: big bottom captions, hook only for the first two seconds."""

from pathlib import Path

from app.subs import write_ass
from app.transcript import Segment


def test_ass_is_clip_relative_and_hook_ends_at_two_seconds(tmp_path: Path):
    path = tmp_path / "captions.ass"
    write_ass(
        path,
        segments=[
            Segment(100.0, 104.0, "the gate was open the whole time"),
            Segment(104.0, 108.0, "and nobody noticed until the end"),
        ],
        hook="The gate was open",
        clip_start=100.0,
        clip_end=122.0,
    )
    text = path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "Style: Hook" in text
    assert "Style: Caption" in text
    # Hook dialogue lasts exactly two seconds from the start of the clip.
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Hook," in text
    assert "The gate was open" in text
    # First spoken line starts at the clip's zero, not at 100s.
    assert "Dialogue: 0,0:00:00.00,0:00:04.00,Caption," in text
    assert "the gate was open" in text
