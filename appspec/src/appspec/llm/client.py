"""LLM client wrapper and utilities."""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Any

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger("appspec.llm")

DEFAULT_MODEL = os.getenv("APPSPEC_MODEL", "gemini/gemini-2.5-flash")

_EMPTY_USAGE: dict[str, Any] = {
    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0,
}
_usage_acc: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_usage_acc", default=None,
)


def check_litellm() -> None:
    if litellm is None:
        raise ImportError(
            "LLM support requires litellm. Install with: pip install appspec[llm]"
        )


def extract_usage(response: Any) -> dict[str, Any]:
    """Pull token counts and cost from a litellm response object."""
    info: dict[str, Any] = {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0,
    }
    try:
        usage = getattr(response, "usage", None)
        if usage:
            info["prompt_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            info["completion_tokens"] = getattr(usage, "completion_tokens", 0) or 0
            info["total_tokens"] = getattr(usage, "total_tokens", 0) or 0
        cost = getattr(response, "_hidden_params", {}).get("response_cost")
        if cost:
            info["cost"] = float(cost)
    except Exception:
        pass
    return info


def reset_usage() -> None:
    """Start accumulating token/cost data for the current async task."""
    _usage_acc.set(dict(_EMPTY_USAGE))


def get_accumulated_usage() -> dict[str, Any]:
    """Return accumulated token/cost data since the last ``reset_usage()``."""
    return _usage_acc.get() or dict(_EMPTY_USAGE)


def log_usage(response: Any, label: str) -> dict[str, Any]:
    """Log and return token/cost data from a litellm response."""
    info = extract_usage(response)
    try:
        if info["total_tokens"]:
            logger.info(
                "%s: %d tokens (prompt=%d, completion=%d)",
                label, info["total_tokens"], info["prompt_tokens"], info["completion_tokens"],
            )
        if info["cost"]:
            logger.info("%s cost: $%.4f", label, info["cost"])
    except Exception:
        pass
    acc = _usage_acc.get()
    if acc is not None:
        acc["prompt_tokens"] += info["prompt_tokens"]
        acc["completion_tokens"] += info["completion_tokens"]
        acc["total_tokens"] += info["total_tokens"]
        acc["cost"] += info["cost"]
    return info
