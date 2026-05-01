"""Tests for telegram_opencode.config module."""

import dataclasses
from unittest.mock import patch

import pytest

from telegram_opencode.config import Config, load_config


@pytest.fixture(autouse=True)
def _no_dotenv() -> "pytest.FixtureRequest":
    """Prevent load_dotenv from reading any .env file during tests."""
    with patch("telegram_opencode.config.load_dotenv"):
        yield  # type: ignore[misc]


def test_load_config_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("AUTHORIZED_USER_IDS", "111,222")
    config = load_config()
    assert config.bot_token == "abc"
    assert config.authorized_user_ids == frozenset({111, 222})


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("AUTHORIZED_USER_IDS", "111")
    with pytest.raises(ValueError):
        load_config()


def test_invalid_user_ids_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("AUTHORIZED_USER_IDS", "abc")
    with pytest.raises(ValueError):
        load_config()


def test_config_is_frozen() -> None:
    config = Config(bot_token="x", authorized_user_ids=frozenset({1}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.bot_token = "y"  # type: ignore[misc]
