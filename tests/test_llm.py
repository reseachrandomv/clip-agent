"""Optional OpenAI-compatible scoring. Heuristics stay in charge without a key."""

import json

from app.llm import llm_enabled, parse_llm_clips, select_with_llm
from app.moments import HeatPoint
from app.transcript import Segment


def test_llm_disabled_without_a_key():
    assert llm_enabled("") is False
    assert (
        select_with_llm(
            api_key="",
            base_url="https://example.invalid/v1",
            model="gpt-test",
            duration=90,
            segments=[Segment(0, 20, "hello there friends")],
            heatmap=[HeatPoint(0, 20, 0.5)],
        )
        is None
    )


def test_parse_llm_clips_keeps_valid_windows_only():
    payload = {
        "clips": [
            {
                "start": 10,
                "end": 32,
                "hook": "Nobody saw that coming",
                "description": "The host drops the result and the room reacts.",
                "caption": "Nobody saw that coming\n\n#shorts",
            },
            {
                "start": 40,
                "end": 90,  # 50s, too long
                "hook": "Way too long to be a short",
                "description": "nope",
                "caption": "nope",
            },
            {
                "start": 50,
                "end": 70,
                "hook": "This hook is definitely more than eight words long",
                "description": "bad hook",
                "caption": "bad",
            },
        ]
    }
    clips = parse_llm_clips(payload, duration=120)
    assert len(clips) == 1
    assert clips[0].start == 10
    assert clips[0].end == 32
    assert clips[0].hook == "Nobody saw that coming"


def test_overlapping_llm_clips_are_dropped():
    payload = {
        "clips": [
            {
                "start": 0,
                "end": 20,
                "hook": "First moment",
                "description": "The opening spike.",
                "caption": "First moment\n\n#shorts",
            },
            {
                "start": 10,
                "end": 30,
                "hook": "Overlaps the first",
                "description": "Should be removed.",
                "caption": "Overlaps\n\n#shorts",
            },
            {
                "start": 40,
                "end": 60,
                "hook": "Second moment",
                "description": "A later spike.",
                "caption": "Second moment\n\n#shorts",
            },
        ]
    }
    clips = parse_llm_clips(payload, duration=80)
    assert [(c.start, c.end) for c in clips] == [(0, 20), (40, 60)]


def test_select_with_llm_posts_transcript_and_parses_clips(monkeypatch):
    body = {
        "clips": [
            {
                "start": 5,
                "end": 25,
                "hook": "The room goes quiet",
                "description": "A pause, then the result.",
                "caption": "The room goes quiet\n\n#shorts",
            }
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(body)}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            assert url == "https://example.invalid/v1/chat/completions"
            assert headers["Authorization"] == "Bearer sk-test"
            assert "hello there" in json["messages"][1]["content"]
            return FakeResponse()

    monkeypatch.setattr("app.llm.httpx.Client", FakeClient)
    clips = select_with_llm(
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        model="gpt-test",
        duration=90,
        segments=[Segment(0, 20, "hello there friends")],
        heatmap=[HeatPoint(0, 20, 0.4)],
    )
    assert clips is not None
    assert clips[0].hook == "The room goes quiet"
    assert clips[0].start == 5
    assert clips[0].end == 25
