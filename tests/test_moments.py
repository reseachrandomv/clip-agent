from app.copy import hook_words, signal_score
from app.models import Word
from app.moments import select_moments


def _words(script: list[tuple[float, str]]) -> list[Word]:
    words = []
    for start, text in script:
        for offset, token in enumerate(text.split()):
            begin = start + offset * 0.35
            words.append(Word(begin, begin + 0.32, token))
    return words


def _long_transcript() -> list[Word]:
    words = []
    boring = "the meeting continues today with notes from the office"
    for slot in range(0, 180, 4):
        words.extend(_words([(slot, boring)]))
    words.extend(_words([(20, "OH MY GOD that was insane hahaha")]))
    words.extend(_words([(102, "wait what no way")]))
    return words


def test_signal_ranks_a_reaction_above_small_talk():
    hot = signal_score("OH MY GOD that was insane hahaha!!!")
    cold = signal_score("the meeting continues today with notes")
    assert hot > 0.5
    assert hot > cold


def test_long_video_yields_three_to_five_safe_clips():
    heatmap = [
        {"start_time": index * 2, "end_time": index * 2 + 2, "value": 1.0 if 100 <= index * 2 < 112 else 0.0}
        for index in range(90)
    ]
    moments = select_moments(_long_transcript(), heatmap, 180, title="Interview")
    assert 3 <= len(moments) <= 5
    starts = [moment.start for moment in moments]
    assert starts == sorted(starts)
    for moment in moments:
        length = moment.end - moment.start
        assert 15 <= length <= 35.01
        assert 0 <= moment.start < moment.end <= 180.01
        assert hook_words(moment.hook) <= 8
        assert moment.hook
        assert moment.description
        assert "#Shorts" in moment.caption
        assert "#YouTubeShorts" in moment.caption
    assert all(earlier.end <= later.start + 0.05 for earlier, later in zip(moments, moments[1:]))
    assert any(moment.start <= 20 <= moment.end or (moment.start <= 28 and moment.end >= 20) for moment in moments)
    assert any(moment.start < 112 and moment.end > 100 for moment in moments)


def test_short_video_is_one_clip_of_the_whole_file():
    words = _words([(0, "hello there friends welcome back")])
    moments = select_moments(words, [], 12)
    assert len(moments) == 1
    assert moments[0].start == 0
    assert moments[0].end == 12


def test_twenty_second_video_stays_inside_the_clip_window():
    words = _words([(0, "a quick story with a real laugh hahaha at the end")])
    moments = select_moments(words, [], 20)
    assert len(moments) == 1
    assert 15 <= moments[0].end - moments[0].start <= 20


def test_distant_reactions_are_not_swallowed_by_one_long_window():
    words = _words(
        [
            (0, "the meeting continues today with notes from the office"),
            (8, "OH MY GOD that was insane hahaha"),
            (40, "the meeting continues today with notes from the office"),
            (62, "wait what no way"),
        ]
    )
    moments = select_moments(words, [], 90)
    assert len(moments) >= 3
    assert all(moment.end - moment.start <= 31 for moment in moments)
    assert any(moment.start <= 8 <= moment.end for moment in moments)
    assert any(moment.start <= 62 <= moment.end for moment in moments)


def test_hook_comes_from_the_loud_line():
    words = _words([(0, "the meeting continues today"), (4, "OH MY GOD that was insane hahaha")])
    moments = select_moments(words, [], 24)
    assert hook_words(moments[0].hook) <= 8
    assert any(token in moments[0].hook.lower() for token in ("god", "insane", "hahaha"))
