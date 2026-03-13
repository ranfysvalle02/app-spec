"""Entity and endpoint quality checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appspec.models import AppSpec
    from appspec.validation import ValidationIssue


def check_entity_quality(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    for i, entity in enumerate(spec.entities):
        if not entity.fields:
            issues.append(ValidationIssue(
                "warning", f"entities[{i}].fields",
                f"Entity '{entity.name}' has no fields defined"
            ))
        if not entity.description:
            issues.append(ValidationIssue(
                "warning", f"entities[{i}].description",
                f"Entity '{entity.name}' has no description"
            ))
        if entity.is_time_series and not entity.time_field:
            issues.append(ValidationIssue(
                "error", f"entities[{i}].time_field",
                f"Time-series entity '{entity.name}' must specify time_field"
            ))


def check_schema_design(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue
    from appspec.models import FieldType

    _MIN_SUBSTANTIVE_FIELDS = 3

    for i, entity in enumerate(spec.entities):
        non_ref_fields = [
            f for f in entity.fields if f.type != FieldType.REFERENCE
        ]

        if 0 < len(non_ref_fields) < _MIN_SUBSTANTIVE_FIELDS:
            issues.append(ValidationIssue(
                "warning",
                f"entities[{i}]",
                f"Entity '{entity.name}' has only {len(non_ref_fields)} "
                f"non-reference field(s) — consider modeling as an enum or "
                f"embedded sub-document instead of a separate collection",
            ))

        ref_fields = [f for f in entity.fields if f.type == FieldType.REFERENCE]
        if ref_fields and not entity.relationships:
            ref_targets = ", ".join(f.reference for f in ref_fields if f.reference)
            issues.append(ValidationIssue(
                "warning",
                f"entities[{i}].relationships",
                f"Entity '{entity.name}' has reference fields ({ref_targets}) "
                f"but no 'relationships' declared — add relationships for "
                f"clearer documentation",
            ))


def check_endpoint_quality(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    seen_routes: set[str] = set()
    for k, ep in enumerate(spec.endpoints):
        route_key = f"{ep.method.value} {ep.path}"
        if route_key in seen_routes:
            issues.append(ValidationIssue(
                "error", f"endpoints[{k}]",
                f"Duplicate endpoint '{route_key}'"
            ))
        seen_routes.add(route_key)

        if ep.auth_required and not spec.auth.enabled:
            issues.append(ValidationIssue(
                "warning", f"endpoints[{k}].auth_required",
                f"Endpoint '{route_key}' requires auth but auth is disabled in spec"
            ))
