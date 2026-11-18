import subprocess

import pytest

from app.models import PipelineError
from app.youtube import download_video


def test_a_hung_download_becomes_an_error(monkeypatch, tmp_path, settings):
    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=50)

    monkeypatch.setattr("app.youtube.subprocess.run", hang)
    monkeypatch.setattr("app.youtube.shutil.which", lambda _name: "/usr/bin/yt-dlp")
    with pytest.raises(PipelineError, match="didn't respond in time"):
        download_video("https://www.youtube.com/watch?v=abcdefghijk", tmp_path, settings)


def test_a_bot_check_is_shown_to_the_user(monkeypatch, tmp_path, settings):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot"

    monkeypatch.setattr("app.youtube.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("app.youtube.shutil.which", lambda _name: "/usr/bin/yt-dlp")
    with pytest.raises(PipelineError, match="not a bot"):
        download_video("https://www.youtube.com/watch?v=abcdefghijk", tmp_path, settings)
