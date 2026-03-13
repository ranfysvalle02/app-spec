"""Abstract base for database engine adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from appspec.models import DatabaseEngine, IndexType

if TYPE_CHECKING:
    from appspec.models import AppSpec, DataField, EntitySpec


class DatabaseAdapter(ABC):
    """Contract every database backend must fulfil."""

    engine: DatabaseEngine

    @abstractmethod
    def field_to_column_type(self, field: "DataField") -> str:
        ...

    @abstractmethod
    def field_to_python_type(self, field: "DataField") -> str:
        ...

    @abstractmethod
    def id_column_type(self) -> str:
        ...

    @abstractmethod
    def id_python_type(self) -> str:
        ...

    @abstractmethod
    def id_import(self) -> str:
        ...

    @property
    def is_sql(self) -> bool:
        return self.engine != DatabaseEngine.MONGODB

    def supports_embedded(self) -> bool:
        return not self.is_sql

    def supports_time_series(self) -> bool:
        return not self.is_sql

    @abstractmethod
    def supported_index_types(self) -> set[IndexType]:
        ...

    @abstractmethod
    def connection_env_vars(self, spec: "AppSpec") -> dict[str, str]:
        ...

    @abstractmethod
    def docker_service_name(self) -> str:
        ...

    @abstractmethod
    def docker_image(self) -> str:
        ...

    @abstractmethod
    def docker_port(self) -> int:
        ...

    @abstractmethod
    def docker_healthcheck(self) -> list[str]:
        ...

    @abstractmethod
    def docker_env(self, spec: "AppSpec") -> dict[str, str]:
        ...

    @abstractmethod
    def docker_volumes(self, spec: "AppSpec") -> dict[str, str]:
        ...

    @abstractmethod
    def python_requirements(self) -> list[str]:
        ...

    @abstractmethod
    def health_check_python(self) -> str:
        ...

    def reference_column_type(self) -> str:
        return self.id_column_type()

    def enum_column_type(self, field: "DataField") -> str:
        return self.field_to_column_type(field)

    def create_table_column(self, field: "DataField") -> str:
        raise NotImplementedError

    def fk_constraint(self, field: "DataField", entity: "EntitySpec") -> str:
        raise NotImplementedError

    def sql_index_type(self, idx_type: IndexType) -> str:
        raise NotImplementedError

    def sql_default(self, field: "DataField") -> str:
        raise NotImplementedError

    def sql_value_literal(self, value: Any, field: "DataField") -> str:
        raise NotImplementedError
