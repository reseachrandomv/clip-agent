"""Ask an OpenAI-compatible chat model to rank windows. Optional."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.moments import MAX_CLIP, MIN_CLIP, HeatPoint, Moment, word_count
from app.transcript import Segment

logger = logging.getLogger(__name__)


def llm_enabled(api_key: str) -> bool:
    return bool(api_key and api_key.strip())


def parse_llm_clips(payload: object, duration: float) -> list[Moment]:
    raw = payload.get("clips") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    accepted: list[Moment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < -0.05 or end > duration + 0.35 or end <= start:
            continue
        length = end - start
        if duration >= MIN_CLIP and not (MIN_CLIP - 0.05 <= length <= MAX_CLIP + 0.05):
            continue
        hook = re.sub(r"\s+", " ", str(item.get("hook") or "")).strip()
        if word_count(hook) < 1 or word_count(hook) >= 8:
            continue
        description = re.sub(r"\s+", " ", str(item.get("description") or "")).strip()
        caption = str(item.get("caption") or "").strip()
        if not description or not caption:
            continue
        if any(start < moment.end and end > moment.start for moment in accepted):
            continue
        accepted.append(
            Moment(
                start=start,
                end=end,
                score=10.0 - len(accepted),
                hook=hook,
                description=description,
                caption=caption,
                signals=["llm"],
            )
        )
        if len(accepted) == 5:
            break
    return accepted


def _json_from_content(content: str) -> dict:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model did not return a JSON object")
    return parsed


def select_with_llm(
    *,
    api_key: str,
    base_url: str,
    model: str,
    duration: float,
    segments: list[Segment],
    heatmap: list[HeatPoint],
) -> list[Moment] | None:
    if not llm_enabled(api_key):
        return None
    transcript = "\n".join(
        f"[{seg.start:.1f}-{seg.end:.1f}] {seg.text}" for seg in segments
    )
    if len(transcript) > 14000:
        transcript = transcript[:14000] + "\n…"
    heat = "\n".join(
        f"{point.start:.1f}-{point.end:.1f} intensity {point.value:.2f}"
        for point in heatmap[:40]
    )
    prompt = (
        "Choose viral vertical clips from this video.\n"
        f"Video duration: {duration:.1f} seconds.\n"
        "Return JSON only, shaped as "
        '{"clips":[{"start":0,"end":20,"hook":"under 8 words",'
        '"description":"what happens","caption":"hook line\\n\\n#shorts #youtubeshorts"}]}.\n'
        "Rules: 3 to 5 clips when the video is long enough, otherwise as many as fit. "
        "Each clip is 15 to 35 seconds and clips do not overlap. "
        "Prefer the most-replayed heatmap peaks and lines with laughter, shouting, "
        "strong reactions, or a punchline. The hook is under 8 words. "
        "The caption is the post text, with hashtags.\n\n"
        f"HEATMAP\n{heat or 'none'}\n\nTRANSCRIPT\n{transcript or 'none'}"
    )
    try:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You choose viral short-form clips. Reply with JSON only.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        clips = parse_llm_clips(_json_from_content(content), duration)
    except Exception:
        logger.exception("LLM clip scoring failed; using heuristics")
        return None
    return clips or None
