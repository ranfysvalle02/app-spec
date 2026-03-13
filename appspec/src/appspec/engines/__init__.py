"""Database engine adapters for AppSpec code generation."""

from appspec.engines.base import DatabaseAdapter
from appspec.engines.mongodb import MongoDBAdapter
from appspec.engines.postgresql import PostgreSQLAdapter

from appspec.models import DatabaseEngine

_ADAPTERS: dict[DatabaseEngine, type[DatabaseAdapter]] = {
    DatabaseEngine.MONGODB: MongoDBAdapter,
    DatabaseEngine.POSTGRESQL: PostgreSQLAdapter,
}


def get_adapter(engine: DatabaseEngine) -> DatabaseAdapter:
    """Return the adapter for the given database engine."""
    cls = _ADAPTERS.get(engine)
    if cls is None:
        raise ValueError(f"No adapter for engine '{engine}'")
    return cls()


__all__ = ["DatabaseAdapter", "MongoDBAdapter", "PostgreSQLAdapter", "get_adapter"]
