"""LLM client wrapper and utilities."""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger("appspec.llm")

DEFAULT_MODEL = os.getenv("APPSPEC_MODEL", "gemini/gemini-2.5-flash")


def check_litellm() -> None:
    if litellm is None:
        raise ImportError(
            "LLM support requires litellm. Install with: pip install appspec[llm]"
        )


def log_usage(response: Any, label: str) -> None:
    try:
        usage = getattr(response, "usage", None)
        if usage:
            total = getattr(usage, "total_tokens", 0)
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            logger.info(
                "%s: %d tokens (prompt=%d, completion=%d)",
                label, total, prompt_tokens, completion_tokens,
            )
        cost = getattr(response, "_hidden_params", {}).get("response_cost")
        if cost:
            logger.info("%s cost: $%.4f", label, cost)
    except Exception:
        pass
