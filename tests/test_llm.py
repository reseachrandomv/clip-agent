from app.copy import hook_words
from app.llm import apply_llm_picks, choose_moments, parse_json_content
from app.models import Moment
from app.moments import take_best


def _moment(start, end, hook="Keep me") -> Moment:
    return Moment(start, end, 0.5, hook, "A thing happens.", "A thing happens.\n\n#Shorts #YouTubeShorts")


def test_fenced_json_parses():
    payload = parse_json_content('```json\n{"clips": []}\n```')
    assert payload == {"clips": []}


def test_matching_window_keeps_its_timestamps_and_new_copy():
    first = _moment(0, 20, "Old hook")
    second = _moment(40, 60, "Other hook")
    payload = {
        "clips": [
            {
                "start": 0.4,
                "end": 19.6,
                "hook": "Wait for the laugh",
                "description": "The guest lands the joke.",
                "caption": "The guest lands the joke.",
            }
        ]
    }
    result = apply_llm_picks([first, second], payload, 90)
    rewritten = next(moment for moment in result if moment.start == 0)
    assert rewritten.end == 20
    assert rewritten.hook == "Wait for the laugh"
    assert rewritten.description == "The guest lands the joke."
    assert "#Shorts" in rewritten.caption
    assert any(moment.start == 40 for moment in result)


def test_overlong_hook_is_trimmed_to_eight_words():
    moment = _moment(0, 20)
    payload = {
        "clips": [
            {
                "start": 0,
                "end": 20,
                "hook": "one two three four five six seven eight nine",
                "description": "Still fine.",
                "caption": "Still fine.\n\n#Shorts",
            }
        ]
    }
    result = apply_llm_picks([moment], payload, 40)
    assert hook_words(result[0].hook) <= 8
    assert "nine" not in result[0].hook.split()


def test_invented_timestamps_are_ignored():
    moment = _moment(0, 20)
    result = apply_llm_picks([moment], {"clips": [{"start": 500, "end": 520, "hook": "Nope"}]}, 40)
    assert result[0].hook == "Keep me"


def test_choose_without_a_key_matches_the_heuristic(settings):
    moments = [_moment(0, 20, "A"), _moment(30, 50, "B"), _moment(60, 80, "C")]
    assert choose_moments(moments, 90, settings) == take_best(moments, 90)
