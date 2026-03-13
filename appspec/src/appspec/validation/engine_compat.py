"""Engine compatibility checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from appspec.models import DatabaseEngine, FieldType

if TYPE_CHECKING:
    from appspec.models import AppSpec
    from appspec.validation import ValidationIssue


def check_engine_compat(spec: "AppSpec", issues: list["ValidationIssue"]) -> None:
    """Warn about features that don't translate cleanly to the chosen engine."""
    from appspec.engines import get_adapter
    from appspec.validation import ValidationIssue

    engine = spec.database.engine
    if engine == DatabaseEngine.MONGODB:
        return

    adapter = get_adapter(engine)
    supported_idx = adapter.supported_index_types()

    for i, entity in enumerate(spec.entities):
        path = f"entities[{i}]"

        if entity.embedded_entities:
            issues.append(ValidationIssue(
                "warning", f"{path}.embedded_entities",
                f"Entity '{entity.name}' has embedded entities — these will be stored "
                f"as JSON columns in {engine.value} mode"
            ))

        if entity.is_time_series:
            issues.append(ValidationIssue(
                "warning", f"{path}.is_time_series",
                f"Time-series entity '{entity.name}' will be a regular table in "
                f"{engine.value} (consider TimescaleDB for native time-series)"
            ))

        for j, idx in enumerate(entity.indexes):
            if idx.type not in supported_idx:
                issues.append(ValidationIssue(
                    "warning", f"{path}.indexes[{j}]",
                    f"Index type '{idx.type.value}' on '{entity.name}' is not natively "
                    f"supported by {engine.value} — it will be mapped to a btree index"
                ))

        for j, fld in enumerate(entity.fields):
            if fld.type == FieldType.GEO_POINT:
                issues.append(ValidationIssue(
                    "warning", f"{path}.fields[{j}]",
                    f"Field '{entity.name}.{fld.name}' (geo_point) will be stored as "
                    f"JSONB in {engine.value} — install PostGIS for native spatial support"
                ))
            if fld.type == FieldType.VECTOR:
                issues.append(ValidationIssue(
                    "warning", f"{path}.fields[{j}]",
                    f"Field '{entity.name}.{fld.name}' (vector) will be stored as "
                    f"JSONB in {engine.value} — install pgvector for native vector support"
                ))
