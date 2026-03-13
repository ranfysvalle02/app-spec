"""Security and secrets scanning."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appspec.models import AppSpec
    from appspec.validation import ValidationIssue

_SECRET_PATTERNS = [
    re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"secret\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"mongodb(\+srv)?://[^/\s]+:[^@/\s]+@", re.IGNORECASE),
    re.compile(r"postgresql://[^/\s]+:[^@/\s]+@", re.IGNORECASE),
]

_DANGEROUS_PATTERNS = [
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\b__import__\s*\("),
    re.compile(r"\bsubprocess\b"),
]


def check_safety(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    raw = spec.to_json()

    for pattern in _SECRET_PATTERNS:
        match = pattern.search(raw)
        if match:
            issues.append(ValidationIssue(
                "error", "safety",
                f"Possible hardcoded secret detected: '{match.group()[:40]}...'"
            ))

    for pattern in _DANGEROUS_PATTERNS:
        match = pattern.search(raw)
        if match:
            issues.append(ValidationIssue(
                "warning", "safety",
                f"Dangerous pattern detected: '{match.group()[:30]}'"
            ))
