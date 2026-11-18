"""Shared records for words, moments, and failures a person can act on."""

from __future__ import annotations

from dataclasses import dataclass


class PipelineError(Exception):
    """A failure message that is safe to show to the person who submitted the URL."""


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    score: float
    hook: str
    description: str
    caption: str


@dataclass(frozen=True)
class DownloadResult:
    video_path: str
    title: str
    duration: float
    heatmap: list[dict]
    words: list[Word]
