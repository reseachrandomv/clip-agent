"""Hooks, descriptions, and captions. Heuristic, and reused to check LLM copy."""

from __future__ import annotations

import re

from app.models import Word

STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "but", "can", "could", "did", "does", "doing", "dont", "down", "each",
    "else", "even", "ever", "for", "from", "get", "gets", "got", "had", "has",
    "have", "having", "her", "here", "hers", "him", "his", "how", "into", "its",
    "just", "like", "look", "make", "more", "most", "much", "not", "now", "off",
    "once", "only", "onto", "our", "out", "over", "really", "said", "say", "says",
    "she", "should", "some", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "too", "very", "was",
    "were", "what", "when", "where", "which", "while", "who", "why", "will",
    "with", "would", "you", "your", "yours", "yeah", "okay", "ok", "gonna",
    "wanna", "um", "uh", "ah",
}

_LAUGH = re.compile(r"\b(ha(ha)+|hahaha|lol+|lmao+|hehe|haha)\b|\[laugh|laughs?\b", re.I)
_REACT = re.compile(
    r"\b(oh my god|oh my|no way|what the|wait what|insane|crazy|wow|let's go|lets go|unbelievable|i can't)\b",
    re.I,
)
_PUNCH = re.compile(r"\b(that's the|the point is|plot twist|turns out|i was wrong|punchline)\b|\?", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z']{3,}")


def signal_score(text: str) -> float:
    """How much a line sounds like a moment people replay. 0 to 1."""

    if not text or not text.strip():
        return 0.0
    lower = text.lower()
    laughter = 1.0 if _LAUGH.search(lower) else 0.0
    reaction = 1.0 if _REACT.search(lower) else 0.0
    punch = 1.0 if _PUNCH.search(lower) else 0.0
    letters = [char for char in text if char.isalpha()]
    caps_ratio = (sum(1 for char in letters if char.isupper()) / len(letters)) if letters else 0.0
    shouting = 1.0 if (caps_ratio > 0.6 and len(letters) >= 8) or text.count("!") >= 2 else 0.0
    if text.count("!") == 1 and shouting == 0.0:
        shouting = 0.45
    raw = (0.40 * laughter) + (0.35 * reaction) + (0.30 * punch) + (0.35 * shouting)
    return max(0.0, min(1.0, raw))


def limit_hook(text: str) -> str:
    words = re.findall(r"\S+", (text or "").replace("\n", " "))
    hook = " ".join(words[:8]).strip(" \"'`“”")
    hook = re.sub(r"\s+", " ", hook).strip()
    if not hook:
        return "Watch this moment"
    return hook


def hook_words(hook: str) -> int:
    return len(re.findall(r"\S+", hook))


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+", text or "")


def best_span(text: str, limit: int) -> str:
    """The stretch, up to `limit` words, with the strongest reaction signal."""

    tokens = _tokens(text)
    if not tokens:
        return ""
    if len(tokens) <= limit:
        return " ".join(tokens)
    best = " ".join(tokens[:limit])
    best_score = signal_score(best)
    best_len = limit
    for size in range(2, limit + 1):
        for index in range(0, len(tokens) - size + 1):
            phrase = " ".join(tokens[index : index + size])
            score = signal_score(phrase)
            if score > best_score + 1e-6 or (score > 0 and abs(score - best_score) <= 1e-6 and size > best_len):
                best = phrase
                best_score = score
                best_len = size
    return best


def focus_text(text: str, limit: int) -> str:
    """Prefer the sentence that actually sounds like a moment, then a short span of it."""

    pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+|[.!?]+", text or "") if part.strip()]
    if len(pieces) > 1:
        best = max(pieces, key=lambda piece: (signal_score(piece), -len(piece.split())))
        if signal_score(best) > 0:
            if len(best.split()) <= limit:
                return best
            return best_span(best, limit)
    return best_span(text, limit)


def build_hook(text: str) -> str:
    span = focus_text(text, 8)
    if not span:
        return "Watch this moment"
    return limit_hook(span)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def first_sentence(text: str, limit: int = 180) -> str:
    clean = _clean(text)
    if not clean:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", clean)[0]
    if len(sentence) <= limit:
        return sentence
    trimmed = sentence[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return (trimmed or sentence[:limit]).rstrip() + "…"


def build_description(text: str) -> str:
    sentence = focus_text(text, 18) or first_sentence(text, 180)
    if not sentence:
        return "A short highlight from the video."
    lower = text.lower()
    if _LAUGH.search(lower):
        prefix = "Laughter breaks in: "
    elif _REACT.search(lower) or text.count("!") >= 2:
        prefix = "A strong reaction: "
    else:
        prefix = ""
    description = prefix + sentence
    if len(description) > 280:
        description = description[:277].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return description


def keywords(text: str, limit: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for match in _WORD.findall(text or ""):
        word = match.strip("'").lower()
        if word in STOPWORDS or len(word) < 4:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return ranked[:limit]


def build_caption(text: str, title: str = "") -> str:
    body = focus_text(text, 22) or first_sentence(text, 220) or "A moment worth replaying."
    tags = ["#Shorts", "#YouTubeShorts"]
    for word in keywords(f"{title} {text}", limit=3):
        tag = "#" + word[:24].capitalize()
        if tag not in tags:
            tags.append(tag)
    return body + "\n\n" + " ".join(tags)


def text_between(words: list[Word], start: float, end: float) -> str:
    parts = [word.text.strip() for word in words if word.end > start and word.start < end and word.text.strip()]
    return _clean(" ".join(parts))
