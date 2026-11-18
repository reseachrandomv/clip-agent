from app.transcript import parse_json3, parse_vtt


def test_json3_words_keep_offsets():
    payload = {
        "events": [
            {
                "tStartMs": 1000,
                "dDurationMs": 2000,
                "segs": [
                    {"utf8": "hello", "tOffsetMs": 0},
                    {"utf8": " world", "tOffsetMs": 500},
                    {"utf8": "\n"},
                ],
            }
        ]
    }
    words = parse_json3(payload)
    assert [word.text for word in words] == ["hello", "world"]
    assert words[0].start == 1.0
    assert words[1].start == 1.5
    assert words[0].end == 1.5


def test_vtt_word_timings():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
<00:00:01.000><c>hello</c><00:00:01.800><c>world</c>
"""
    words = parse_vtt(vtt)
    assert [word.text for word in words] == ["hello", "world"]
    assert words[0].start == 1.0
    assert words[1].start == 1.8


def test_vtt_rolling_captions_do_not_repeat():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:01.000
hello

00:00:00.500 --> 00:00:02.000
hello world
"""
    words = parse_vtt(vtt)
    text = " ".join(word.text for word in words).lower()
    assert text.count("hello") == 1
    assert "world" in text
