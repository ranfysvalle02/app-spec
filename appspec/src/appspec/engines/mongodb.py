"""MongoDB engine adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from appspec.models import DatabaseEngine, FieldType, IndexType
from appspec.engines.base import DatabaseAdapter

if TYPE_CHECKING:
    from appspec.models import AppSpec, DataField

_MONGO_BSON_MAP: dict[FieldType, str] = {
    FieldType.STRING: "string",
    FieldType.INTEGER: "int",
    FieldType.FLOAT: "double",
    FieldType.BOOLEAN: "bool",
    FieldType.DATETIME: "date",
    FieldType.ENUM: "string",
    FieldType.REFERENCE: "objectId",
    FieldType.TEXT: "string",
    FieldType.EMAIL: "string",
    FieldType.ARRAY: "array",
    FieldType.OBJECT: "object",
    FieldType.GEO_POINT: "object",
    FieldType.VECTOR: "array",
}

_MONGO_PYTHON_MAP: dict[FieldType, str] = {
    FieldType.STRING: "str",
    FieldType.INTEGER: "int",
    FieldType.FLOAT: "float",
    FieldType.BOOLEAN: "bool",
    FieldType.DATETIME: "datetime",
    FieldType.ENUM: "str",
    FieldType.REFERENCE: "str",
    FieldType.TEXT: "str",
    FieldType.EMAIL: "str",
    FieldType.ARRAY: "list",
    FieldType.OBJECT: "dict",
    FieldType.GEO_POINT: "dict",
    FieldType.VECTOR: "list[float]",
}


class MongoDBAdapter(DatabaseAdapter):
    engine = DatabaseEngine.MONGODB

    def field_to_column_type(self, field: "DataField") -> str:
        return _MONGO_BSON_MAP.get(field.type, "string")

    def field_to_python_type(self, field: "DataField") -> str:
        return _MONGO_PYTHON_MAP.get(field.type, "str")

    def id_column_type(self) -> str:
        return "objectId"

    def id_python_type(self) -> str:
        return "str"

    def id_import(self) -> str:
        return "from bson import ObjectId"

    def supports_embedded(self) -> bool:
        return True

    def supports_time_series(self) -> bool:
        return True

    def supported_index_types(self) -> set[IndexType]:
        return {
            IndexType.REGULAR, IndexType.TEXT, IndexType.GEO,
            IndexType.VECTOR, IndexType.UNIQUE,
        }

    def connection_env_vars(self, spec: "AppSpec") -> dict[str, str]:
        db_name = spec.slug.replace("-", "_")
        return {
            "MONGODB_URI": "mongodb://localhost:27017",
            "MONGODB_DB": db_name,
        }

    def docker_service_name(self) -> str:
        return "mongodb"

    def docker_image(self) -> str:
        return "mongo:8"

    def docker_port(self) -> int:
        return 27017

    def docker_healthcheck(self) -> list[str]:
        return ["CMD", "mongosh", "--eval", "db.runCommand('ping').ok", "--quiet"]

    def docker_env(self, spec: "AppSpec") -> dict[str, str]:
        return {"MONGO_INITDB_DATABASE": spec.slug.replace("-", "_")}

    def docker_volumes(self, spec: "AppSpec") -> dict[str, str]:
        return {"mongodb_data": "/data/db"}

    def python_requirements(self) -> list[str]:
        return [
            "pymongo>=4.16",
        ]

    def health_check_python(self) -> str:
        return (
            "db = get_db()\n"
            "        await db.command(\"ping\")\n"
            "        db_status = \"connected\""
        )
