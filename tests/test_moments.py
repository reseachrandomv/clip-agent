"""Moment picking: heatmap plus transcript signals, with an LLM fallback."""

from app.moments import HeatPoint, select_moments, share_caption, word_count
from app.transcript import Segment


def _talk(start: float, end: float, text: str) -> Segment:
    return Segment(start, end, text)


def test_hook_is_under_eight_words_and_caption_has_hashtags():
    segments = [
        _talk(10, 16, "Oh my god that ending was unbelievable and everyone lost it"),
        _talk(16, 22, "I have never seen a finish like that in my life"),
    ]
    heatmap = [HeatPoint(10, 22, 0.9)]
    moments = select_moments(40, segments, heatmap)
    assert moments
    moment = moments[0]
    assert word_count(moment.hook) < 8
    assert moment.hook
    assert "#shorts" in moment.caption
    assert "#" in moment.caption.split()[-1]


def test_selects_three_to_five_bounded_clips_on_a_long_video():
    segments = []
    t = 0.0
    while t < 180:
        segments.append(_talk(t, t + 4, f"we keep going around the track at {int(t)}"))
        t += 4.5
    # A shout, a laugh, and a punchline sit on heatmap peaks.
    segments.extend(
        [
            _talk(20, 28, "HAHAHA I can't believe he did that wow"),
            _talk(70, 78, "WAIT. OH MY GOD. NO WAY that just happened"),
            _talk(120, 130, "Why did the plan fail? Because nobody checked the gate"),
        ]
    )
    heatmap = [
        HeatPoint(18, 30, 0.95),
        HeatPoint(68, 80, 0.88),
        HeatPoint(118, 132, 0.8),
        HeatPoint(0, 10, 0.05),
    ]
    moments = select_moments(180, segments, heatmap)
    assert 3 <= len(moments) <= 5
    for moment in moments:
        assert 15 <= moment.end - moment.start <= 35
        assert 0 <= moment.start < moment.end <= 180
        assert word_count(moment.hook) < 8
        assert moment.description
        assert "#shorts" in moment.caption
    # No overlaps.
    ordered = sorted(moments, key=lambda item: item.start)
    for left, right in zip(ordered, ordered[1:]):
        assert left.end <= right.start + 0.05
    # The dull intro is not the only thing we kept: at least two peaks are covered.
    covered = 0
    for peak in (24, 74, 124):
        if any(moment.start <= peak <= moment.end for moment in moments):
            covered += 1
    assert covered >= 2


def test_laughter_and_heatmap_beat_a_flat_intro():
    segments = [
        _talk(0, 12, "welcome back to the channel please like and subscribe"),
        _talk(30, 42, "haha haha that is the funniest thing I have ever seen"),
    ]
    heatmap = [HeatPoint(0, 12, 0.1), HeatPoint(28, 44, 0.97)]
    moments = select_moments(50, segments, heatmap)
    assert moments
    winner = max(moments, key=lambda item: item.score)
    assert winner.start >= 20
    assert "laughter" in winner.signals


def test_hot_line_starts_near_the_beginning_of_the_clip():
    segments = [
        _talk(0, 6, "welcome back to the channel please like and subscribe"),
        _talk(30, 37, "haha haha that is the funniest thing I have ever seen"),
        _talk(55, 62, "oh my god no way that just happened wow"),
    ]
    moments = select_moments(80, segments, [])
    laugh = next(moment for moment in moments if "laughter" in moment.signals)
    assert 24 <= laugh.start <= 32


def test_short_source_still_returns_one_clip():
    segments = [_talk(0, 12, "a quick tip you can use today")]
    moments = select_moments(12, segments, [])
    assert len(moments) == 1
    assert moments[0].start == 0
    assert moments[0].end == 12


def test_thirty_second_source_stays_inside_the_video():
    segments = [_talk(0, 30, "one continuous thought about the race")]
    moments = select_moments(30, segments, [])
    assert len(moments) == 1
    assert moments[0].end - moments[0].start == 30


def test_share_caption_includes_hook_and_hashtags():
    caption = share_caption("Wait for it", "A punchline lands.", "gate check fail")
    assert caption.startswith("Wait for it")
    assert "#shorts" in caption
    assert "#youtubeshorts" in caption
    assert "#the" not in caption
    assert "#gate" in caption
    assert "#check" in caption
