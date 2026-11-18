from app.captions import build_ass, cues_for_clip
from app.copy import hook_words, limit_hook
from app.models import Word


def test_cues_are_short_and_relative_to_the_clip():
    words = [
        Word(10.0 + index * 0.4, 10.3 + index * 0.4, token)
        for index, token in enumerate(["one", "two", "three", "four", "five", "six"])
    ]
    cues = cues_for_clip(words, 10.0, 20.0)
    assert cues
    assert cues[0].start == 0
    assert all(len(cue.text.split()) <= 4 for cue in cues)
    assert all(earlier.end <= later.start + 0.05 for earlier, later in zip(cues, cues[1:]))
    assert "one" in cues[0].text


def test_ass_puts_the_hook_on_screen_for_two_seconds():
    words = [Word(0.0, 0.4, "hello"), Word(0.4, 0.9, "world")]
    cues = cues_for_clip(words, 0.0, 15.0)
    hook = limit_hook("Wait for the last word please now extra extra")
    script = build_ass(cues, hook)
    assert "PlayResX: 1080" in script
    assert "PlayResY: 1920" in script
    assert hook in script
    assert hook_words(hook) <= 8
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Hook" in script
    assert "hello world" in script or "hello" in script
