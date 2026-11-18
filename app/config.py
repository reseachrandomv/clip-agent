"""Runtime settings. Everything the host can change lives in the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    whisper_model: str
    max_duration_sec: int
    max_upload_mb: int
    workers: int
    render_preset: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "data")).expanduser().resolve(),
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            whisper_model=os.environ.get("WHISPER_MODEL", "base").strip() or "base",
            max_duration_sec=_int("MAX_DURATION_SEC", 20 * 60),
            max_upload_mb=_int("MAX_UPLOAD_MB", 500),
            workers=max(1, _int("CLIP_WORKERS", 1)),
            render_preset=os.environ.get("RENDER_PRESET", "veryfast").strip() or "veryfast",
        )
