"""Page and section validation checks.

Catches broken UI page specs that the LLM might produce — orphan data sources,
duplicate IDs, missing defaults, and config fields that reference nonexistent
entity fields.  These checks run inside the ``validate()`` pipeline, which
means they also fire during the LLM retry loop and trigger correction prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appspec.models import AppSpec
    from appspec.validation import ValidationIssue


def check_pages(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    from appspec.validation import ValidationIssue

    pages = spec.ui.pages
    if not pages:
        return

    collection_names = {e.collection for e in spec.entities}
    field_names_by_collection: dict[str, set[str]] = {
        e.collection: {f.name for f in e.fields} for e in spec.entities
    }

    # ── Duplicate page IDs ───────────────────────────────────────────────
    seen_page_ids: set[str] = set()
    for i, page in enumerate(pages):
        if page.id in seen_page_ids:
            issues.append(ValidationIssue(
                "error",
                f"ui.pages[{i}].id",
                f"Duplicate page ID '{page.id}' — page IDs must be unique",
            ))
        seen_page_ids.add(page.id)

    # ── Duplicate section IDs (globally unique across all pages) ─────────
    seen_section_ids: set[str] = set()
    for i, page in enumerate(pages):
        for j, section in enumerate(page.sections):
            if section.id in seen_section_ids:
                issues.append(ValidationIssue(
                    "error",
                    f"ui.pages[{i}].sections[{j}].id",
                    f"Duplicate section ID '{section.id}' — section IDs must "
                    f"be globally unique across all pages",
                ))
            seen_section_ids.add(section.id)

    # ── Default page checks ──────────────────────────────────────────────
    default_count = sum(1 for p in pages if p.is_default)
    if default_count == 0:
        issues.append(ValidationIssue(
            "warning",
            "ui.pages",
            "No page has is_default=true — the UI will show the first page "
            "but this is likely unintentional",
        ))
    elif default_count > 1:
        issues.append(ValidationIssue(
            "warning",
            "ui.pages",
            f"{default_count} pages have is_default=true — only the first "
            f"will be shown; set is_default on exactly one page",
        ))

    # ── Per-section checks ───────────────────────────────────────────────
    for i, page in enumerate(pages):
        if not page.sections:
            issues.append(ValidationIssue(
                "warning",
                f"ui.pages[{i}]",
                f"Page '{page.id}' has no sections — it will render as a "
                f"blank page",
            ))

        for j, section in enumerate(page.sections):
            sec_path = f"ui.pages[{i}].sections[{j}]"
            ds = section.data_source
            cfg = section.config or {}
            sec_type = section.type.value

            # Orphan data_source
            if ds and ds not in collection_names:
                issues.append(ValidationIssue(
                    "error",
                    f"{sec_path}.data_source",
                    f"Section '{section.id}' references unknown collection "
                    f"'{ds}' — must match an entity collection name",
                ))

            entity_fields = field_names_by_collection.get(ds, set())

            # Chart config field checks
            if sec_type == "chart":
                _check_field_ref(
                    cfg.get("group_by"), entity_fields, ds,
                    sec_path, "config.group_by", section.id, issues,
                )
                _check_field_ref(
                    cfg.get("x_field"), entity_fields, ds,
                    sec_path, "config.x_field", section.id, issues,
                )
                _check_field_ref(
                    cfg.get("y_field"), entity_fields, ds,
                    sec_path, "config.y_field", section.id, issues,
                )

            # Table config column checks
            if sec_type == "table":
                for col in cfg.get("columns", []):
                    _check_field_ref(
                        col, entity_fields, ds,
                        sec_path, f"config.columns['{col}']", section.id,
                        issues,
                    )
                _check_field_ref(
                    cfg.get("default_sort"), entity_fields, ds,
                    sec_path, "config.default_sort", section.id, issues,
                )

            # KPI metric data_source checks
            if sec_type == "kpi_row":
                for k, metric in enumerate(cfg.get("metrics", [])):
                    m_ds = metric.get("data_source", "") or ds
                    if m_ds and m_ds not in collection_names:
                        issues.append(ValidationIssue(
                            "warning",
                            f"{sec_path}.config.metrics[{k}].data_source",
                            f"KPI metric '{metric.get('label', k)}' in "
                            f"section '{section.id}' references unknown "
                            f"collection '{m_ds}'",
                        ))


def _check_field_ref(
    field_name: str | None,
    entity_fields: set[str],
    collection: str,
    sec_path: str,
    config_key: str,
    section_id: str,
    issues: list["ValidationIssue"],
) -> None:
    """Emit a warning if a config field reference points to a nonexistent field."""
    from appspec.validation import ValidationIssue

    if not field_name or not collection or not entity_fields:
        return
    if field_name not in entity_fields:
        issues.append(ValidationIssue(
            "warning",
            f"{sec_path}.{config_key}",
            f"Section '{section_id}' {config_key} references field "
            f"'{field_name}' which does not exist on '{collection}'",
        ))
