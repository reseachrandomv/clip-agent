"""Transcript parsing: YouTube captions in, timed segments out."""

from app.transcript import Segment, dedupe_segments, parse_vtt


def test_parse_vtt_reads_cues_and_strips_tags():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
Hello <c>there</c>

00:00:04.000 --> 00:00:05.250
A second line
with a break
"""
    segments = parse_vtt(vtt)
    assert segments == [
        Segment(1.0, 3.5, "Hello there"),
        Segment(4.0, 5.25, "A second line with a break"),
    ]


def test_parse_vtt_ignores_notes_and_cue_ids():
    vtt = """WEBVTT

NOTE this is a comment

cue-1
00:01.000 --> 00:02.000
Just words
"""
    segments = parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].start == 1.0
    assert segments[0].text == "Just words"


def test_dedupe_rolling_youtube_captions():
    rolling = [
        Segment(0.0, 1.5, "I can't"),
        Segment(0.4, 2.0, "I can't believe"),
        Segment(0.8, 2.6, "I can't believe this"),
        Segment(2.6, 4.0, "happened today"),
        Segment(2.8, 4.2, "happened today"),
    ]
    cleaned = dedupe_segments(rolling)
    assert [seg.text for seg in cleaned] == [
        "I can't believe this",
        "happened today",
    ]
    assert cleaned[0].start == 0.0
    assert cleaned[0].end == 2.6
    assert cleaned[1].end == 4.2


def test_parse_vtt_dedupes_by_default():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:01.200
wow

00:00:00.400 --> 00:00:01.800
wow look
"""
    segments = parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "wow look"
