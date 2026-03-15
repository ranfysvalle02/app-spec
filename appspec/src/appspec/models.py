"""
AppSpec Document Model
======================

The universal application specification format. Describes *what* an application
is — entities, relationships, endpoints, auth, UI — without prescribing *how*
to build it.

Database-agnostic: the ``database`` config selects an engine (MongoDB or
PostgreSQL). Every type here maps 1:1 to JSON, making AppSpec documents
natively storable and validatable via Pydantic V2.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Enums ────────────────────────────────────────────────────────────────────


class FieldType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    ENUM = "enum"
    REFERENCE = "reference"
    TEXT = "text"
    EMAIL = "email"
    ARRAY = "array"
    OBJECT = "object"
    GEO_POINT = "geo_point"
    VECTOR = "vector"


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class CrudOperation(str, Enum):
    LIST = "list"
    GET = "get"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    AGGREGATE = "aggregate"


class IndexType(str, Enum):
    REGULAR = "regular"
    TEXT = "text"
    GEO = "2dsphere"
    VECTOR = "vectorSearch"
    UNIQUE = "unique"
    BTREE = "btree"
    GIN = "gin"


class DatabaseEngine(str, Enum):
    MONGODB = "mongodb"
    POSTGRESQL = "postgresql"


# ── Field-level specs ────────────────────────────────────────────────────────


class DataField(BaseModel):
    """A single field in an entity."""

    name: str = Field(..., description="snake_case field name")
    type: FieldType = Field(..., description="Data type")
    required: bool = Field(default=True)
    description: str = Field(default="")
    default: Any = Field(default=None, description="Default value")
    enum_values: list[str] = Field(default_factory=list, description="Allowed values when type=enum")
    reference: str = Field(default="", description="Target collection when type=reference")
    vector_dimensions: int = Field(default=0, description="Embedding dimensions when type=vector")
    is_filterable: bool = Field(default=False)
    is_sortable: bool = Field(default=False)
    is_unique: bool = Field(default=False)
    min_value: float | None = Field(default=None)
    max_value: float | None = Field(default=None)
    max_length: int | None = Field(default=None)
    pattern: str = Field(default="", description="Regex validation pattern")

    @model_validator(mode="after")
    def _check_type_constraints(self) -> "DataField":
        if not re.fullmatch(r"^[a-z][a-z0-9_]*$", self.name):
            raise ValueError("field name must be lowercase snake_case")
        if self.type == FieldType.ENUM and not self.enum_values:
            raise ValueError("enum_values required when type is 'enum'")
        if self.type == FieldType.REFERENCE and not self.reference:
            raise ValueError("reference collection required when type is 'reference'")
        if self.type == FieldType.VECTOR and self.vector_dimensions <= 0:
            raise ValueError("vector_dimensions must be > 0 when type is 'vector'")
        return self


class IndexSpec(BaseModel):
    """An explicit index definition."""

    name: str = Field(default="", description="Index name (auto-generated if empty)")
    type: IndexType = Field(default=IndexType.REGULAR)
    keys: dict[str, int | str] = Field(
        ..., description="Field -> direction mapping, e.g. {'status': 1, 'created_at': -1}"
    )
    sparse: bool = Field(default=False)
    unique: bool = Field(default=False, description="Enforce uniqueness constraint")
    expire_after_seconds: int | None = Field(
        default=None, description="TTL: auto-delete documents after N seconds"
    )
    partial_filter: dict[str, Any] = Field(
        default_factory=dict,
        description="Partial index filter expression, e.g. {'status': 'active'}",
    )


# ── Entity specs ─────────────────────────────────────────────────────────────


class EntitySpec(BaseModel):
    """A data entity (collection) in the application."""

    name: str = Field(..., description="PascalCase class name, e.g. 'Patient'")
    collection: str = Field(..., description="snake_case storage name (collection or table)")
    description: str = Field(default="")
    fields: list[DataField] = Field(default_factory=list)
    relationships: list[str] = Field(
        default_factory=list, description="References to other entity names"
    )
    embedded_entities: list["EntitySpec"] = Field(
        default_factory=list, description="Nested sub-document schemas"
    )
    is_time_series: bool = Field(default=False)
    time_field: str = Field(default="", description="datetime field for time-series collections")
    meta_field: str = Field(default="", description="Grouping field for time-series collections")
    indexes: list[IndexSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_time_series(self) -> "EntitySpec":
        if self.is_time_series and not self.time_field:
            raise ValueError("time_field is required when is_time_series is True")
        return self


# ── Endpoint specs ───────────────────────────────────────────────────────────


class Endpoint(BaseModel):
    """An API endpoint."""

    method: HttpMethod = Field(...)
    path: str = Field(..., description="URL path, e.g. /patients/{id}")
    description: str = Field(default="")
    entity: str = Field(..., description="Which EntitySpec this endpoint operates on")
    operation: CrudOperation = Field(default=CrudOperation.LIST)
    filters: list[str] = Field(default_factory=list, description="Filterable field names")
    sort_fields: list[str] = Field(default_factory=list, description="Sortable field names")
    auth_required: bool = Field(default=False)
    roles: list[str] = Field(default_factory=list, description="Required roles (empty = any authed)")


# ── Auth specs ───────────────────────────────────────────────────────────────


class AuthSpec(BaseModel):
    """Authentication and authorization configuration."""

    enabled: bool = Field(default=False)
    strategy: str = Field(default="jwt", description="Auth strategy: jwt, session, api_key, oauth")
    roles: list[str] = Field(default_factory=list)
    default_role: str = Field(default="")


# ── UI specs ─────────────────────────────────────────────────────────────────


class SectionType(str, Enum):
    TABLE = "table"
    FORM = "form"
    CHART = "chart"
    KPI_ROW = "kpi_row"
    CARD_GRID = "card_grid"
    DETAIL = "detail"
    LIST = "list"
    CALENDAR = "calendar"
    MAP = "map"
    MARKDOWN = "markdown"
    CUSTOM = "custom"


class PageLayout(str, Enum):
    SINGLE = "single"
    SIDEBAR = "sidebar"
    DASHBOARD = "dashboard"


class ChartSectionConfig(BaseModel):
    """Configuration for chart sections."""

    chart_type: str = Field(default="bar", description="bar, line, pie, doughnut, area")
    x_field: str = Field(default="", description="Field for the x-axis")
    y_field: str = Field(default="", description="Field for the y-axis")
    group_by: str = Field(default="", description="Field to group/categorize by")
    aggregation: str = Field(default="count", description="count, sum, avg, min, max")


class KPIMetric(BaseModel):
    """A single KPI metric in a KPI row."""

    label: str = Field(..., description="Display label")
    data_source: str = Field(default="", description="Collection to aggregate over")
    aggregation: str = Field(default="count", description="count, sum, avg, min, max")
    field: str = Field(default="", description="Field to aggregate (ignored for count)")
    icon: str = Field(default="", description="Optional icon name")
    color: str = Field(default="", description="Accent color hint")


class KPISectionConfig(BaseModel):
    """Configuration for KPI row sections."""

    metrics: list[KPIMetric] = Field(default_factory=list)


class TableSectionConfig(BaseModel):
    """Configuration for table sections."""

    columns: list[str] = Field(default_factory=list, description="Fields to display (empty = all)")
    default_sort: str = Field(default="", description="Default sort field")
    page_size: int = Field(default=25)
    row_actions: list[str] = Field(
        default_factory=lambda: ["edit", "delete"],
        description="Actions per row: edit, delete, view",
    )


class CardGridSectionConfig(BaseModel):
    """Configuration for card grid sections."""

    title_field: str = Field(default="", description="Field to use as card title")
    subtitle_field: str = Field(default="", description="Field to use as card subtitle")
    image_field: str = Field(default="", description="Field containing image URLs")
    badge_field: str = Field(default="", description="Field for status badge")
    columns: int = Field(default=3, description="Number of grid columns (2-4)")


class DetailSectionConfig(BaseModel):
    """Configuration for single-record detail sections."""

    title_field: str = Field(default="", description="Field to use as detail title")
    fields: list[str] = Field(default_factory=list, description="Fields to display (empty = all)")


class PageSection(BaseModel):
    """A section within a custom page."""

    id: str = Field(..., description="Section identifier")
    type: SectionType = Field(
        default=SectionType.TABLE,
        description="Section type: table, chart, kpi_row, card_grid, form, detail, list, markdown, custom",
    )
    title: str = Field(default="")
    data_source: str = Field(default="", description="Collection or endpoint to fetch data from")
    config: dict[str, Any] = Field(default_factory=dict)
    col_span: int = Field(default=1, description="Column span in dashboard grid (1-3)")
    row_span: int = Field(default=1, description="Row span in dashboard grid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_section_type(cls, data: Any) -> Any:
        """Accept raw strings for backward compatibility with existing specs."""
        if isinstance(data, dict) and isinstance(data.get("type"), str):
            raw = data["type"]
            try:
                SectionType(raw)
            except ValueError:
                data["type"] = SectionType.CUSTOM.value
        return data


class PageSpec(BaseModel):
    """A page in the application UI."""

    id: str = Field(..., description="URL-safe page identifier")
    label: str = Field(..., description="Navigation label")
    description: str = Field(default="")
    layout: PageLayout = Field(default=PageLayout.SINGLE, description="Page layout: single, sidebar, dashboard")
    icon: str = Field(default="", description="Optional icon identifier for navigation")
    data_collections: list[str] = Field(default_factory=list)
    sections: list[PageSection] = Field(default_factory=list)
    is_default: bool = Field(default=False, description="Show this page first")


class UISpec(BaseModel):
    """Frontend configuration."""

    framework: str = Field(default="tailwind", description="UI framework: tailwind, react, vue, none")
    pages: list[PageSpec] = Field(default_factory=list)
    theme: str = Field(default="default")


# ── Database config ───────────────────────────────────────────────────────────


class DatabaseConfig(BaseModel):
    """Selects the database engine for code generation."""

    engine: DatabaseEngine = Field(
        default=DatabaseEngine.MONGODB,
        description="Database engine: mongodb, postgresql",
    )
    version: str = Field(default="", description="Target DB version hint (e.g. '17' for PostgreSQL 17)")


# ── The root document ────────────────────────────────────────────────────────


class AppSpec(BaseModel):
    """
    The universal application specification document.

    Describes *what* an application is — entities, relationships, endpoints,
    authentication, and UI — without prescribing *how* to build it.

    Database-agnostic: set ``database.engine`` to target MongoDB or PostgreSQL.
    The same spec drives deterministic code generation for any supported engine.
    """

    schema_version: str = Field(default="1.0", description="AppSpec schema version")
    app_name: str = Field(..., description="Human-readable application name")
    slug: str = Field(..., description="URL-safe kebab-case identifier")
    description: str = Field(default="")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthSpec = Field(default_factory=AuthSpec)
    entities: list[EntitySpec] = Field(..., min_length=1)
    endpoints: list[Endpoint] = Field(default_factory=list)
    ui: UISpec = Field(default_factory=UISpec)
    sample_data: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict, description="store_name -> list of sample records"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extensible metadata for domain-specific use"
    )

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "AppSpec":
        entity_names = {e.name for e in self.entities}
        collection_names = {e.collection for e in self.entities}

        for entity in self.entities:
            for rel in entity.relationships:
                if rel not in entity_names:
                    raise ValueError(
                        f"Entity '{entity.name}' references unknown entity '{rel}'"
                    )
            for field in entity.fields:
                if field.type == FieldType.REFERENCE and field.reference:
                    if field.reference not in collection_names:
                        raise ValueError(
                            f"Field '{entity.name}.{field.name}' references unknown "
                            f"collection '{field.reference}'"
                        )

        for ep in self.endpoints:
            if ep.entity not in entity_names:
                raise ValueError(
                    f"Endpoint '{ep.method.value} {ep.path}' references unknown "
                    f"entity '{ep.entity}'"
                )

        return self

    def to_json(self, **kwargs: Any) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2, **kwargs)

    @classmethod
    def from_json(cls, data: str | bytes) -> "AppSpec":
        """Deserialize from JSON string or bytes."""
        return cls.model_validate_json(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSpec":
        """Create from a plain dict (e.g. loaded from MongoDB)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (e.g. for MongoDB insertion)."""
        return self.model_dump(mode="json")
