"""Token usage tracking with per-session and monthly persistence."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STORAGE_PATH = Path.home() / ".claude" / "telegram_bot_usage.json"
_CHARS_PER_TOKEN = 4  # rough English-text estimate


def _est(chars: int) -> int:
    return max(1, chars // _CHARS_PER_TOKEN)


@dataclass
class UsageTracker:
    storage_path: Path = field(default_factory=lambda: _STORAGE_PATH)

    # In-memory session accumulators (reset on /start)
    session_input_tokens: int = 0
    session_output_tokens: int = 0
    session_prompts: int = 0

    # Most-recent-prompt snapshot
    last_input_tokens: int = 0
    last_output_tokens: int = 0

    def record_prompt(self, input_chars: int, output_chars: int) -> None:
        in_tok = _est(input_chars)
        out_tok = _est(output_chars)
        self.last_input_tokens = in_tok
        self.last_output_tokens = out_tok
        self.session_input_tokens += in_tok
        self.session_output_tokens += out_tok
        self.session_prompts += 1
        self._persist(in_tok, out_tok)

    def reset_session(self) -> None:
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_prompts = 0
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def _persist(self, in_tok: int, out_tok: int) -> None:
        month_key = datetime.now(UTC).strftime("%Y-%m")
        try:
            data: dict = (
                json.loads(self.storage_path.read_text()) if self.storage_path.exists() else {}
            )
        except Exception:
            data = {}
        m = data.setdefault("monthly", {}).setdefault(
            month_key, {"input_tokens": 0, "output_tokens": 0, "prompts": 0}
        )
        m["input_tokens"] += in_tok
        m["output_tokens"] += out_tok
        m["prompts"] += 1
        try:
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.warning("Failed to persist usage data", exc_info=True)

    def get_monthly(self) -> tuple[int, int, int]:
        """Return (input_tokens, output_tokens, prompts) for the current calendar month."""
        month_key = datetime.now(UTC).strftime("%Y-%m")
        try:
            data = (
                json.loads(self.storage_path.read_text()) if self.storage_path.exists() else {}
            )
            m = data.get("monthly", {}).get(month_key, {})
            return (
                m.get("input_tokens", 0),
                m.get("output_tokens", 0),
                m.get("prompts", 0),
            )
        except Exception:
            return (0, 0, 0)

    def format_summary(self, monthly_budget: int | None = None) -> str:
        m_in, m_out, m_prompts = self.get_monthly()
        month = datetime.now(UTC).strftime("%b %Y")
        lines = [
            "📊 Token Usage",
            f"Last prompt:  {self.last_input_tokens:,} in / {self.last_output_tokens:,} out",
            f"Session ({self.session_prompts} prompts): "
            f"{self.session_input_tokens:,} in / {self.session_output_tokens:,} out",
            f"Monthly ({month}): {m_in:,} in / {m_out:,} out ({m_prompts} prompts)",
        ]
        if monthly_budget and monthly_budget > 0:
            total = m_in + m_out
            pct = total / monthly_budget * 100
            lines.append(f"Budget: {pct:.1f}% of {monthly_budget:,} tokens")
        lines.append("_(est. from character count)_")
        return "\n".join(lines)
