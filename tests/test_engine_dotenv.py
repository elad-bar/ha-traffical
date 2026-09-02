"""Engine CLI loads repo-root ``.env`` without overriding the process env."""

from __future__ import annotations

import logging
import os

from engine.entrypoint import LOG_LEVEL_ENV, _configure_logging, _load_repo_dotenv


def test_load_repo_dotenv_sets_unset_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    (tmp_path / ".env").write_text(f"{LOG_LEVEL_ENV}=DEBUG\n", encoding="utf-8")
    assert _load_repo_dotenv(tmp_path) is True
    assert os.environ[LOG_LEVEL_ENV] == "DEBUG"


def test_load_repo_dotenv_does_not_override_process_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV, "WARNING")
    (tmp_path / ".env").write_text(f"{LOG_LEVEL_ENV}=DEBUG\n", encoding="utf-8")
    assert _load_repo_dotenv(tmp_path) is True
    assert os.environ[LOG_LEVEL_ENV] == "WARNING"


def test_load_repo_dotenv_missing_file(tmp_path) -> None:
    assert _load_repo_dotenv(tmp_path) is False


def test_log_level_env_is_the_only_verbosity_knob(monkeypatch) -> None:
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv(LOG_LEVEL_ENV, "WARNING")
    try:
        _configure_logging()
        assert logging.getLogger().level == logging.WARNING
    finally:
        logging.getLogger().handlers.clear()


def test_log_level_env_defaults_to_info(monkeypatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    try:
        _configure_logging()
        assert logging.getLogger().level == logging.INFO
    finally:
        logging.getLogger().handlers.clear()
