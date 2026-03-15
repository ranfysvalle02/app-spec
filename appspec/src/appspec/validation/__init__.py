"""Validation pipeline for AppSpec documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appspec.validation.schema import check_naming, check_cross_references
from appspec.validation.quality import check_entity_quality, check_endpoint_quality, check_schema_design
from appspec.validation.safety import check_safety
from appspec.validation.engine_compat import check_engine_compat
from appspec.validation.pages import check_pages

if TYPE_CHECKING:
    from appspec.models import AppSpec


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    path: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> str:
        if self.valid and not self.warnings:
            return "Valid (no issues)"
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        return ", ".join(parts)


def validate(spec: "AppSpec") -> ValidationResult:
    """Run all validation checks on an AppSpec document."""
    issues: list[ValidationIssue] = []

    check_naming(spec, issues)
    check_cross_references(spec, issues)
    check_entity_quality(spec, issues)
    check_endpoint_quality(spec, issues)
    check_schema_design(spec, issues)
    check_engine_compat(spec, issues)
    check_safety(spec, issues)
    check_pages(spec, issues)

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationResult(valid=not has_errors, issues=issues)


__all__ = ["ValidationIssue", "ValidationResult", "validate"]
