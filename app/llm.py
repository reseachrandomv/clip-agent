"""Optional OpenAI-compatible scoring. Heuristics stay in charge when this fails."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import replace

from app.config import Settings
from app.copy import hook_words, limit_hook
from app.models import Moment
from app.moments import take_best

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an editor who cuts long videos into YouTube Shorts. "
    "You receive candidate windows that already have timestamps. "
    "Pick the 3 to 5 windows most likely to be rewatched. "
    "For each one, write a hook under 8 words, a one-sentence description of what happens, "
    "and a caption that includes the hashtags #Shorts and #YouTubeShorts. "
    "Use only start and end times from the candidates. Return JSON only, no markdown, "
    'shaped as {"clips":[{"start":0,"end":20,"hook":"","description":"","caption":""}]}.'
)


def parse_json_content(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, count=1).strip()
        text = re.sub(r"```$", "", text).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object")
    return parsed


def _closest(candidates: list[Moment], start: float, end: float) -> Moment | None:
    best: Moment | None = None
    best_gap = 2.01
    for moment in candidates:
        gap = abs(moment.start - start) + abs(moment.end - end)
        if gap < best_gap:
            best = moment
            best_gap = gap
    return best


def _rewrite(moment: Moment, clip: dict) -> Moment:
    hook = limit_hook(str(clip.get("hook") or moment.hook))
    if hook_words(hook) > 8:
        hook = moment.hook
    description = str(clip.get("description") or moment.description).strip()
    description = re.sub(r"\s+", " ", description)[:280] or moment.description
    caption = str(clip.get("caption") or moment.caption).strip()
    if "#Shorts" not in caption:
        caption = (caption + "\n\n#Shorts #YouTubeShorts").strip()
    return replace(moment, hook=hook, description=description, caption=caption)


def _overlaps(left: Moment, right: Moment) -> bool:
    return not (left.end <= right.start or left.start >= right.end)


def apply_llm_picks(candidates: list[Moment], payload: dict, duration: float) -> list[Moment]:
    """Use the model's selection when each pick matches a real candidate window."""

    fallback = take_best(candidates, duration)
    clips = payload.get("clips") if isinstance(payload, dict) else None
    if not isinstance(clips, list):
        return fallback
    chosen: list[Moment] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        try:
            start = float(clip["start"])
            end = float(clip["end"])
        except (KeyError, TypeError, ValueError):
            continue
        match = _closest(candidates, start, end)
        if match is None or any(_overlaps(match, other) for other in chosen):
            continue
        chosen.append(_rewrite(match, clip))
    if not chosen:
        return fallback
    target = len(fallback)
    for moment in candidates:
        if len(chosen) >= target:
            break
        if any(_overlaps(moment, other) for other in chosen):
            continue
        chosen.append(moment)
    chosen.sort(key=lambda moment: moment.start)
    return chosen


def request_picks(candidates: list[Moment], settings: Settings) -> dict:
    preview = [
        {
            "start": moment.start,
            "end": moment.end,
            "score": moment.score,
            "transcript": moment.description[:320],
            "draft_hook": moment.hook,
        }
        for moment in candidates[:12]
    ]
    body = {
        "model": settings.openai_model,
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps({"windows": preview})},
        ],
    }
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return parse_json_content(content)


def choose_moments(candidates: list[Moment], duration: float, settings: Settings) -> list[Moment]:
    """LLM pick when a key is set. Any failure returns the heuristic cut."""

    if not settings.openai_api_key:
        return take_best(candidates, duration)
    try:
        payload = request_picks(candidates, settings)
        return apply_llm_picks(candidates, payload, duration)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        logger.warning("LLM moment scoring failed, using heuristics: %s", exc)
        return take_best(candidates, duration)
