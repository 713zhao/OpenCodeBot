"""Configuration loader for the Telegram OpenCode bridge bot."""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """Immutable bot configuration loaded from environment variables."""

    bot_token: str
    authorized_user_ids: frozenset[int]


def load_config() -> Config:
    """Load and validate bot configuration from environment variables.

    Raises:
        ValueError: If TELEGRAM_BOT_TOKEN is missing/empty or
                    AUTHORIZED_USER_IDS cannot be parsed.
    """
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be set and non-empty")

    raw_ids = os.environ.get("AUTHORIZED_USER_IDS", "").strip()
    if not raw_ids:
        raise ValueError("AUTHORIZED_USER_IDS must contain at least one valid integer")

    try:
        user_ids = frozenset(int(uid.strip()) for uid in raw_ids.split(",") if uid.strip())
    except ValueError as exc:
        raise ValueError(
            "AUTHORIZED_USER_IDS must contain at least one valid integer"
        ) from exc

    if not user_ids:
        raise ValueError("AUTHORIZED_USER_IDS must contain at least one valid integer")

    return Config(bot_token=token, authorized_user_ids=user_ids)
