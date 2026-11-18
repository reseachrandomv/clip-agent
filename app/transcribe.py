"""Local transcript fallback. YouTube captions are preferred when they exist."""

from __future__ import annotations

import threading
from pathlib import Path

from app.transcript import Segment

_lock = threading.Lock()
_model = None
_model_name: str | None = None


class TranscribeError(RuntimeError):
    pass


def transcribe(path: Path, model_name: str) -> list[Segment]:
    global _model, _model_name
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscribeError(
            "This video has no captions, and faster-whisper is not installed."
        ) from exc
    with _lock:
        if _model is None or _model_name != model_name:
            try:
                # Prefer the copy baked into the image. A missing model falls
                # through to a download, which needs network.
                try:
                    _model = WhisperModel(
                        model_name,
                        device="cpu",
                        compute_type="int8",
                        local_files_only=True,
                    )
                except Exception:
                    _model = WhisperModel(model_name, device="cpu", compute_type="int8")
            except Exception as exc:
                raise TranscribeError(
                    f"Could not load the whisper model '{model_name}'. "
                    "Check the network if it is not already downloaded."
                ) from exc
            _model_name = model_name
        model = _model
    try:
        segments, _info = model.transcribe(str(path), vad_filter=True, beam_size=1)
        result: list[Segment] = []
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                result.append(Segment(float(seg.start), float(seg.end), text))
    except Exception as exc:
        raise TranscribeError("Local transcription failed.") from exc
    return result
