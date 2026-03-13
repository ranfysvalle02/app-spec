"""PostgreSQL engine adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from appspec.models import DatabaseEngine, FieldType, IndexType
from appspec.engines.base import DatabaseAdapter

if TYPE_CHECKING:
    from appspec.models import AppSpec, DataField, EntitySpec

_PG_COLUMN_MAP: dict[FieldType, str] = {
    FieldType.STRING: "VARCHAR(255)",
    FieldType.INTEGER: "INTEGER",
    FieldType.FLOAT: "DOUBLE PRECISION",
    FieldType.BOOLEAN: "BOOLEAN",
    FieldType.DATETIME: "TIMESTAMPTZ",
    FieldType.ENUM: "VARCHAR(100)",
    FieldType.REFERENCE: "UUID",
    FieldType.TEXT: "TEXT",
    FieldType.EMAIL: "VARCHAR(320)",
    FieldType.ARRAY: "JSONB",
    FieldType.OBJECT: "JSONB",
    FieldType.GEO_POINT: "JSONB",
    FieldType.VECTOR: "JSONB",
}

_PG_SQLA_MAP: dict[FieldType, str] = {
    FieldType.STRING: "String(255)",
    FieldType.INTEGER: "Integer",
    FieldType.FLOAT: "Float",
    FieldType.BOOLEAN: "Boolean",
    FieldType.DATETIME: "DateTime(timezone=True)",
    FieldType.ENUM: "String(100)",
    FieldType.REFERENCE: "Uuid",
    FieldType.TEXT: "Text",
    FieldType.EMAIL: "String(320)",
    FieldType.ARRAY: "JSON",
    FieldType.OBJECT: "JSON",
    FieldType.GEO_POINT: "JSON",
    FieldType.VECTOR: "JSON",
}

_PG_PYTHON_MAP: dict[FieldType, str] = {
    FieldType.STRING: "str",
    FieldType.INTEGER: "int",
    FieldType.FLOAT: "float",
    FieldType.BOOLEAN: "bool",
    FieldType.DATETIME: "datetime",
    FieldType.ENUM: "str",
    FieldType.REFERENCE: "uuid.UUID",
    FieldType.TEXT: "str",
    FieldType.EMAIL: "str",
    FieldType.ARRAY: "dict | list",
    FieldType.OBJECT: "dict",
    FieldType.GEO_POINT: "dict",
    FieldType.VECTOR: "list",
}


class PostgreSQLAdapter(DatabaseAdapter):
    engine = DatabaseEngine.POSTGRESQL

    def field_to_column_type(self, field: "DataField") -> str:
        if field.type == FieldType.STRING and field.max_length:
            return f"VARCHAR({field.max_length})"
        if field.type == FieldType.ENUM and field.enum_values:
            return "VARCHAR(100)"
        return _PG_COLUMN_MAP.get(field.type, "TEXT")

    def field_to_sqla_type(self, field: "DataField") -> str:
        if field.type == FieldType.STRING and field.max_length:
            return f"String({field.max_length})"
        if field.type == FieldType.ENUM and field.enum_values:
            vals = ", ".join(f'"{v}"' for v in field.enum_values)
            return f'Enum({vals}, name="{field.name}_enum")'
        return _PG_SQLA_MAP.get(field.type, "Text")

    def field_to_python_type(self, field: "DataField") -> str:
        base = _PG_PYTHON_MAP.get(field.type, "str")
        if not field.required:
            return f"{base} | None"
        return base

    def id_column_type(self) -> str:
        return "UUID"

    def id_python_type(self) -> str:
        return "uuid.UUID"

    def id_import(self) -> str:
        return "import uuid"

    def supports_embedded(self) -> bool:
        return False

    def supports_time_series(self) -> bool:
        return False

    def supported_index_types(self) -> set[IndexType]:
        return {
            IndexType.REGULAR, IndexType.BTREE, IndexType.TEXT,
            IndexType.GIN, IndexType.UNIQUE,
        }

    def connection_env_vars(self, spec: "AppSpec") -> dict[str, str]:
        db_name = spec.slug.replace("-", "_")
        return {
            "DATABASE_URL": f"postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name}",
        }

    def docker_service_name(self) -> str:
        return "postgres"

    def docker_image(self) -> str:
        return "postgres:17"

    def docker_port(self) -> int:
        return 5432

    def docker_healthcheck(self) -> list[str]:
        return ["CMD-SHELL", "pg_isready -U postgres"]

    def docker_env(self, spec: "AppSpec") -> dict[str, str]:
        return {
            "POSTGRES_DB": spec.slug.replace("-", "_"),
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
        }

    def docker_volumes(self, spec: "AppSpec") -> dict[str, str]:
        return {"pgdata": "/var/lib/postgresql/data"}

    def python_requirements(self) -> list[str]:
        return [
            "sqlalchemy[asyncio]>=2.0",
            "asyncpg>=0.29",
            "alembic>=1.13",
        ]

    def health_check_python(self) -> str:
        return (
            "async with async_session() as sess:\n"
            "            from sqlalchemy import text\n"
            "            await sess.execute(text(\"SELECT 1\"))\n"
            "            db_status = \"connected\""
        )

    def reference_column_type(self) -> str:
        return "UUID"

    def enum_column_type(self, field: "DataField") -> str:
        return "VARCHAR(100)"

    def create_table_column(self, field: "DataField") -> str:
        col_type = self.field_to_column_type(field)
        parts = [field.name, col_type]
        if field.is_unique:
            parts.append("UNIQUE")
        if field.required:
            parts.append("NOT NULL")
        default = self.sql_default(field)
        if default:
            parts.append(default)
        return " ".join(parts)

    def fk_constraint(self, field: "DataField", entity: "EntitySpec") -> str:
        if field.type != FieldType.REFERENCE or not field.reference:
            return ""
        return f"REFERENCES {field.reference}(id)"

    def sql_index_type(self, idx_type: IndexType) -> str:
        mapping = {
            IndexType.REGULAR: "btree",
            IndexType.BTREE: "btree",
            IndexType.TEXT: "gin",
            IndexType.GIN: "gin",
            IndexType.UNIQUE: "btree",
        }
        return mapping.get(idx_type, "btree")

    def sql_default(self, field: "DataField") -> str:
        if field.default is None:
            return ""
        if isinstance(field.default, bool):
            return f"DEFAULT {'TRUE' if field.default else 'FALSE'}"
        if isinstance(field.default, (int, float)):
            return f"DEFAULT {field.default}"
        if isinstance(field.default, str):
            safe = field.default.replace("'", "''")
            return f"DEFAULT '{safe}'"
        return ""

    def sql_value_literal(self, value: Any, field: "DataField") -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            safe = value.replace("'", "''")
            return f"'{safe}'"
        if isinstance(value, (list, dict)):
            import json as _json
            safe = _json.dumps(value).replace("'", "''")
            return f"'{safe}'::jsonb"
        return f"'{value}'"
