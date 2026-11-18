"""Runtime settings, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Load a .env file without overriding variables that are already set."""

    env_path = path or Path(".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    max_duration_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        data_dir = Path(os.environ.get("DATA_DIR", "data")).expanduser()
        try:
            max_duration = int(os.environ.get("MAX_DURATION_SECONDS", "1800"))
        except ValueError:
            max_duration = 1800
        return cls(
            data_dir=data_dir,
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            whisper_model=os.environ.get("WHISPER_MODEL", "base").strip() or "base",
            whisper_device=os.environ.get("WHISPER_DEVICE", "cpu").strip() or "cpu",
            whisper_compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            max_duration_seconds=max(60, max_duration),
        )
