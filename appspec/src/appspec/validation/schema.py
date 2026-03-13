"""Naming conventions and cross-reference validation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from appspec.models import FieldType

if TYPE_CHECKING:
    from appspec.models import AppSpec
    from appspec.validation import ValidationIssue

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$")
_COLLECTION_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")


def check_naming(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    if not _SLUG_RE.match(spec.slug):
        issues.append(ValidationIssue(
            "error", "slug",
            f"Slug '{spec.slug}' must be lowercase kebab-case (a-z, 0-9, hyphens)"
        ))

    seen_collections: set[str] = set()
    seen_names: set[str] = set()

    for i, entity in enumerate(spec.entities):
        path = f"entities[{i}]"
        if not _PASCAL_RE.match(entity.name):
            issues.append(ValidationIssue(
                "warning", f"{path}.name",
                f"Entity name '{entity.name}' should be PascalCase"
            ))
        if not _COLLECTION_RE.match(entity.collection):
            issues.append(ValidationIssue(
                "error", f"{path}.collection",
                f"Collection name '{entity.collection}' must be lowercase snake_case"
            ))
        if entity.collection in seen_collections:
            issues.append(ValidationIssue(
                "error", f"{path}.collection",
                f"Duplicate collection name '{entity.collection}'"
            ))
        if entity.name in seen_names:
            issues.append(ValidationIssue(
                "error", f"{path}.name",
                f"Duplicate entity name '{entity.name}'"
            ))
        seen_collections.add(entity.collection)
        seen_names.add(entity.name)

        seen_fields: set[str] = set()
        for j, fld in enumerate(entity.fields):
            if fld.name in seen_fields:
                issues.append(ValidationIssue(
                    "error", f"{path}.fields[{j}].name",
                    f"Duplicate field name '{fld.name}' in {entity.name}"
                ))
            seen_fields.add(fld.name)


def check_cross_references(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    entity_names = {e.name for e in spec.entities}
    collection_names = {e.collection for e in spec.entities}

    for i, entity in enumerate(spec.entities):
        for rel in entity.relationships:
            if rel not in entity_names:
                issues.append(ValidationIssue(
                    "error", f"entities[{i}].relationships",
                    f"'{entity.name}' references unknown entity '{rel}'"
                ))

        for j, fld in enumerate(entity.fields):
            if fld.type == FieldType.REFERENCE and fld.reference:
                if fld.reference not in collection_names:
                    issues.append(ValidationIssue(
                        "error", f"entities[{i}].fields[{j}].reference",
                        f"Field '{entity.name}.{fld.name}' references unknown collection "
                        f"'{fld.reference}'"
                    ))

    for k, ep in enumerate(spec.endpoints):
        if ep.entity not in entity_names:
            issues.append(ValidationIssue(
                "error", f"endpoints[{k}].entity",
                f"Endpoint '{ep.method.value} {ep.path}' references unknown entity '{ep.entity}'"
            ))
