"""LLM pipeline: spec generation and seed data generation."""

from __future__ import annotations

import json
from typing import Any

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

from appspec.models import (
    AppSpec,
    CrudOperation,
    Endpoint,
    FieldType,
    HttpMethod,
    PageLayout,
    PageSection,
    PageSpec,
    SectionType,
)
from appspec.validation import validate
from appspec.llm.client import check_litellm, log_usage, DEFAULT_MODEL
from appspec.llm.prompts import SCHEMA_PROMPT, get_seed_prompt

_LLM_TIMEOUT_SECONDS = 60


def _ensure_endpoints(spec: AppSpec) -> AppSpec:
    if spec.endpoints:
        return spec
    endpoints = []
    for entity in spec.entities:
        c = entity.collection
        endpoints.extend([
            Endpoint(method=HttpMethod.GET, path=f"/{c}", entity=entity.name, operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.GET, path=f"/{c}/{{id}}", entity=entity.name, operation=CrudOperation.GET),
            Endpoint(method=HttpMethod.POST, path=f"/{c}", entity=entity.name, operation=CrudOperation.CREATE),
            Endpoint(method=HttpMethod.PUT, path=f"/{c}/{{id}}", entity=entity.name, operation=CrudOperation.UPDATE),
            Endpoint(method=HttpMethod.DELETE, path=f"/{c}/{{id}}", entity=entity.name, operation=CrudOperation.DELETE),
        ])
    data = spec.to_dict()
    data["endpoints"] = [e.model_dump(mode="json") for e in endpoints]
    return AppSpec.from_dict(data)


def _ensure_pages(spec: AppSpec) -> AppSpec:
    """Auto-generate sensible UI pages when ``spec.ui.pages`` is empty.

    Produces a dashboard overview page plus one CRUD page per entity,
    keeping backward compatibility with specs that predate the page system.
    """
    if spec.ui.pages:
        return spec

    pages: list[PageSpec] = []

    # ── Dashboard page ───────────────────────────────────────────────────
    dashboard_sections: list[PageSection] = []

    # KPI row: one count metric per entity
    kpi_metrics = [
        {"label": entity.name, "data_source": entity.collection, "aggregation": "count"}
        for entity in spec.entities
    ]
    dashboard_sections.append(
        PageSection(
            id="overview-kpis",
            type=SectionType.KPI_ROW,
            title="Overview",
            config={"metrics": kpi_metrics},
            col_span=3,
        )
    )

    # Charts for entities with enum fields (pie) or sortable datetime fields (line)
    for entity in spec.entities:
        enum_fields = [f for f in entity.fields if f.type == FieldType.ENUM]
        if enum_fields:
            ef = enum_fields[0]
            dashboard_sections.append(
                PageSection(
                    id=f"chart-{entity.collection}-{ef.name}",
                    type=SectionType.CHART,
                    title=f"{entity.name} by {ef.name.replace('_', ' ').title()}",
                    data_source=entity.collection,
                    config={
                        "chart_type": "pie",
                        "group_by": ef.name,
                        "aggregation": "count",
                    },
                )
            )

        dt_fields = [
            f for f in entity.fields
            if f.type == FieldType.DATETIME and f.is_sortable
        ]
        if dt_fields:
            df = dt_fields[0]
            dashboard_sections.append(
                PageSection(
                    id=f"chart-{entity.collection}-{df.name}",
                    type=SectionType.CHART,
                    title=f"{entity.name} over Time",
                    data_source=entity.collection,
                    config={
                        "chart_type": "line",
                        "x_field": df.name,
                        "aggregation": "count",
                    },
                )
            )

    pages.append(
        PageSpec(
            id="dashboard",
            label="Dashboard",
            layout=PageLayout.DASHBOARD,
            icon="chart-bar",
            is_default=True,
            sections=dashboard_sections,
        )
    )

    # ── One CRUD page per entity ─────────────────────────────────────────
    for entity in spec.entities:
        pages.append(
            PageSpec(
                id=entity.collection,
                label=entity.name,
                icon="table-cells",
                data_collections=[entity.collection],
                sections=[
                    PageSection(
                        id=f"table-{entity.collection}",
                        type=SectionType.TABLE,
                        title=entity.name,
                        data_source=entity.collection,
                        config={"page_size": 25},
                    )
                ],
            )
        )

    data = spec.to_dict()
    data["ui"]["pages"] = [p.model_dump(mode="json") for p in pages]
    return AppSpec.from_dict(data)


async def create_spec(
    prompt: str,
    model: str = "",
    temperature: float = 0.2,
    max_retries: int = 3,
) -> AppSpec:
    """Generate a validated AppSpec document from a prompt."""
    check_litellm()
    model = model or DEFAULT_MODEL

    messages = [
        {"role": "system", "content": SCHEMA_PROMPT},
        {"role": "user", "content": prompt},
    ]
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        log_usage(response, f"schema (attempt {attempt})")

        raw_content = response.choices[0].message.content
        if not raw_content:
            last_error = ValueError("LLM returned empty response")
            continue

        try:
            spec = AppSpec.from_json(raw_content)
        except Exception as e:
            last_error = ValueError(f"Failed to parse LLM output as AppSpec: {e}")
            messages.append({"role": "assistant", "content": raw_content})
            messages.append({
                "role": "user",
                "content": (
                    f"The JSON you produced failed validation: {e}\n\n"
                    "Please fix the issues and return a corrected JSON object."
                ),
            })
            continue

        result = validate(spec)
        if result.errors:
            error_msgs = "; ".join(f"{i.path}: {i.message}" for i in result.errors)
            last_error = ValueError(f"Spec validation failed: {error_msgs}")
            messages.append({"role": "assistant", "content": raw_content})
            messages.append({
                "role": "user",
                "content": (
                    f"The spec has validation errors: {error_msgs}\n\n"
                    "Please fix all errors and return a corrected JSON object."
                ),
            })
            continue

        spec = _ensure_endpoints(spec)
        spec = _ensure_pages(spec)
        return spec

    raise last_error or ValueError("Failed to generate a valid AppSpec")


_RESERVED_SEED_KEYS = {"id", "_id", "created_at", "updated_at"}


def _fallback_value(field: Any, entity_name: str, index: int) -> Any:
    """Generate deterministic fallback values for a field."""
    field_type = field.type.value
    field_name = field.name.lower()
    n = index + 1

    if field_type == "email" or "email" in field_name:
        return f"{entity_name.lower()}_{n}@example.com"
    if field_type in {"string", "text"}:
        if "name" in field_name or "title" in field_name:
            return f"{entity_name} {n}"
        if "description" in field_name:
            return f"Sample {entity_name.lower()} description {n}"
        if "phone" in field_name:
            return f"+1-555-01{n:02d}"
        return f"sample_{field.name}_{n}"
    if field_type == "integer":
        return n
    if field_type == "float":
        return round(float(n) * 1.1, 2)
    if field_type == "boolean":
        return n % 2 == 1
    if field_type == "datetime":
        month = ((n - 1) % 12) + 1
        day = ((n - 1) % 28) + 1
        hour = (n * 3) % 24
        return f"2025-{month:02d}-{day:02d}T{hour:02d}:00:00Z"
    if field_type == "enum":
        if field.enum_values:
            return field.enum_values[(n - 1) % len(field.enum_values)]
        return "unknown"
    if field_type == "array":
        return []
    if field_type == "object":
        return {"label": f"{entity_name} {n}"}
    if field_type == "geo_point":
        return {"type": "Point", "coordinates": [0.0 + n * 0.001, 0.0 + n * 0.001]}
    if field_type == "vector":
        dims = max(int(field.vector_dimensions or 3), 1)
        return [round(0.01 * n, 4)] * dims
    return f"sample_{field.name}_{n}"


def _fallback_seed_data(spec: "AppSpec", docs_per_collection: int = 10) -> dict[str, list[dict[str, Any]]]:
    """Build deterministic fallback seed data for all collections."""
    fallback: dict[str, list[dict[str, Any]]] = {}
    for entity in spec.entities:
        docs: list[dict[str, Any]] = []
        non_ref_fields = [
            f
            for f in entity.fields
            if f.type.value != "reference" and f.name not in _RESERVED_SEED_KEYS
        ]
        for i in range(docs_per_collection):
            doc: dict[str, Any] = {}
            for field in non_ref_fields:
                # Always populate required fields; usually populate optional too for richer demo UX.
                if field.required or i < 3:
                    doc[field.name] = _fallback_value(field, entity.name, i)
            docs.append(doc)
        fallback[entity.collection] = docs
    return fallback


def _normalize_seed_data(
    data: dict[str, list[dict[str, Any]]], spec: "AppSpec", docs_per_collection: int = 10
) -> dict[str, list[dict[str, Any]]]:
    """Ensure every collection gets usable docs, filling gaps deterministically."""
    normalized: dict[str, list[dict[str, Any]]] = {}
    fallback = _fallback_seed_data(spec, docs_per_collection=docs_per_collection)

    for entity in spec.entities:
        collection = entity.collection
        source_docs = data.get(collection, [])
        if not isinstance(source_docs, list):
            source_docs = []

        non_ref_fields = [
            f
            for f in entity.fields
            if f.type.value != "reference" and f.name not in _RESERVED_SEED_KEYS
        ]
        allowed = {f.name for f in non_ref_fields}

        docs: list[dict[str, Any]] = []
        for idx in range(docs_per_collection):
            source = source_docs[idx] if idx < len(source_docs) and isinstance(source_docs[idx], dict) else {}
            fallback_doc = fallback[collection][idx]
            doc: dict[str, Any] = {}

            for field in non_ref_fields:
                if field.name in source and source[field.name] is not None:
                    doc[field.name] = source[field.name]
                elif field.required:
                    doc[field.name] = fallback_doc.get(field.name)

            # Keep any extra safe keys from source (still constrained to non-reference known fields).
            for key, value in source.items():
                if key in allowed and key not in doc:
                    doc[key] = value

            # If doc is empty but we have non-reference fields, use fallback doc for a useful record.
            if not doc and non_ref_fields:
                doc = dict(fallback_doc)

            # Clamp enum values to the allowed list so charts group correctly.
            for field in non_ref_fields:
                if field.type.value == "enum" and field.enum_values and field.name in doc:
                    if doc[field.name] not in field.enum_values:
                        doc[field.name] = field.enum_values[idx % len(field.enum_values)]

            docs.append(doc)

        normalized[collection] = docs

    return normalized


def _sanitize_seed_data(
    data: dict[str, list[dict[str, Any]]], spec: "AppSpec"
) -> dict[str, list[dict[str, Any]]]:
    """Strip reference fields and reserved keys from LLM-generated seed data."""
    ref_fields: dict[str, set[str]] = {}
    for entity in spec.entities:
        refs = {f.name for f in entity.fields if f.type.value == "reference"}
        ref_fields[entity.collection] = refs | _RESERVED_SEED_KEYS

    cleaned: dict[str, list[dict[str, Any]]] = {}
    for collection, docs in data.items():
        if not isinstance(docs, list):
            continue
        drop_keys = ref_fields.get(collection, _RESERVED_SEED_KEYS)
        cleaned[collection] = [
            {k: v for k, v in doc.items() if k not in drop_keys}
            for doc in docs if isinstance(doc, dict)
        ]
    return cleaned


async def create_sample_data(
    spec: AppSpec,
    model: str = "",
    temperature: float = 0.4,
    max_retries: int = 1,
) -> dict[str, list[dict[str, Any]]]:
    """Generate realistic seed data for a validated spec."""
    check_litellm()
    model = model or DEFAULT_MODEL

    entity_summary = []
    for e in spec.entities:
        fields_desc = []
        for f in e.fields:
            parts = [f"  - {f.name}: {f.type.value}"]
            if f.enum_values:
                parts.append(f" (enum: {f.enum_values})")
            if f.type.value == "reference":
                parts.append(f" (references {f.reference})")
            fields_desc.append("".join(parts))
        entity_summary.append(
            f"Entity: {e.name} (collection: {e.collection})\n"
            f"Description: {e.description or 'N/A'}\n"
            f"Fields:\n" + "\n".join(fields_desc)
        )

    user_msg = (
        f"Application: {spec.app_name}\n"
        f"Description: {spec.description}\n\n"
        + "\n\n".join(entity_summary)
    )

    seed_prompt = get_seed_prompt(spec.database.engine.value)
    messages = [
        {"role": "system", "content": seed_prompt},
        {"role": "user", "content": user_msg},
    ]

    for attempt in range(1, max_retries + 2):
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        log_usage(response, f"seed (attempt {attempt})")

        raw = response.choices[0].message.content
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if not isinstance(data, dict):
            continue

        collections = {e.collection for e in spec.entities}
        if not any(k in collections for k in data):
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Keys must be collection names: {sorted(collections)}. Fix and return.",
            })
            continue

        data = _sanitize_seed_data(data, spec)
        data = _normalize_seed_data(data, spec)
        return data

    # Final bulletproof fallback: never leave generated apps without seed payload.
    return _fallback_seed_data(spec)


def create_spec_sync(
    prompt: str, model: str = "", temperature: float = 0.2, max_retries: int = 3,
) -> AppSpec:
    import asyncio
    return asyncio.run(create_spec(prompt, model or DEFAULT_MODEL, temperature, max_retries))


def create_sample_data_sync(
    spec: AppSpec, model: str = "", temperature: float = 0.4, max_retries: int = 1,
) -> dict[str, list[dict[str, Any]]]:
    import asyncio
    return asyncio.run(create_sample_data(spec, model or DEFAULT_MODEL, temperature, max_retries))
