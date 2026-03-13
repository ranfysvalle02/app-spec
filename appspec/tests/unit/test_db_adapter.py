"""Tests for the database adapter abstraction layer."""

import pytest

from appspec.generation.registry import generate, get_registry
from appspec.engines import (
    MongoDBAdapter,
    PostgreSQLAdapter,
    get_adapter,
)
from appspec.models import (
    AppSpec,
    CrudOperation,
    DataField,
    DatabaseConfig,
    DatabaseEngine,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
    IndexSpec,
    IndexType,
)
from appspec.validation import validate


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_spec(engine: str = "mongodb", **overrides) -> AppSpec:
    base = {
        "app_name": "DB Test",
        "slug": "db-test",
        "database": {"engine": engine},
        "entities": [
            EntitySpec(
                name="Task",
                collection="tasks",
                description="A task item",
                fields=[
                    DataField(name="title", type=FieldType.STRING),
                    DataField(
                        name="status",
                        type=FieldType.ENUM,
                        enum_values=["todo", "done"],
                        is_filterable=True,
                    ),
                    DataField(name="priority", type=FieldType.INTEGER, required=False),
                    DataField(name="done", type=FieldType.BOOLEAN, required=False),
                ],
            ),
            EntitySpec(
                name="User",
                collection="users",
                description="A user",
                fields=[
                    DataField(name="email", type=FieldType.EMAIL, is_unique=True),
                    DataField(name="name", type=FieldType.STRING),
                ],
            ),
        ],
        "endpoints": [
            Endpoint(method=HttpMethod.GET, path="/tasks", entity="Task", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.GET, path="/tasks/{id}", entity="Task", operation=CrudOperation.GET),
            Endpoint(method=HttpMethod.POST, path="/tasks", entity="Task", operation=CrudOperation.CREATE),
            Endpoint(method=HttpMethod.PUT, path="/tasks/{id}", entity="Task", operation=CrudOperation.UPDATE),
            Endpoint(method=HttpMethod.DELETE, path="/tasks/{id}", entity="Task", operation=CrudOperation.DELETE),
            Endpoint(method=HttpMethod.GET, path="/users", entity="User", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/users", entity="User", operation=CrudOperation.CREATE),
        ],
    }
    base.update(overrides)
    return AppSpec(**base)


def _make_ref_spec(engine: str = "mongodb") -> AppSpec:
    return AppSpec(
        app_name="Ref Test",
        slug="ref-test",
        database=DatabaseConfig(engine=DatabaseEngine(engine)),
        entities=[
            EntitySpec(
                name="Owner",
                collection="owners",
                description="A pet owner",
                fields=[DataField(name="name", type=FieldType.STRING)],
            ),
            EntitySpec(
                name="Pet",
                collection="pets",
                description="A pet",
                fields=[
                    DataField(name="name", type=FieldType.STRING),
                    DataField(name="owner_id", type=FieldType.REFERENCE, reference="owners"),
                ],
            ),
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/owners", entity="Owner", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/owners", entity="Owner", operation=CrudOperation.CREATE),
            Endpoint(method=HttpMethod.GET, path="/pets", entity="Pet", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/pets", entity="Pet", operation=CrudOperation.CREATE),
        ],
    )


# ── Factory tests ─────────────────────────────────────────────────────────────


class TestGetAdapter:
    def test_mongodb_adapter(self):
        a = get_adapter(DatabaseEngine.MONGODB)
        assert isinstance(a, MongoDBAdapter)
        assert a.engine == DatabaseEngine.MONGODB

    def test_postgresql_adapter(self):
        a = get_adapter(DatabaseEngine.POSTGRESQL)
        assert isinstance(a, PostgreSQLAdapter)
        assert a.engine == DatabaseEngine.POSTGRESQL

    def test_unknown_engine_raises(self):
        with pytest.raises(ValueError, match="No adapter"):
            get_adapter("unknown_engine")


# ── MongoDB adapter tests ─────────────────────────────────────────────────────


class TestMongoDBAdapter:
    def setup_method(self):
        self.adapter = MongoDBAdapter()

    def test_is_not_sql(self):
        assert not self.adapter.is_sql

    def test_supports_embedded(self):
        assert self.adapter.supports_embedded()

    def test_supports_time_series(self):
        assert self.adapter.supports_time_series()

    def test_id_type(self):
        assert self.adapter.id_column_type() == "objectId"
        assert self.adapter.id_python_type() == "str"

    def test_field_types(self):
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.STRING)) == "string"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.INTEGER)) == "int"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.FLOAT)) == "double"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.BOOLEAN)) == "bool"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.DATETIME)) == "date"

    def test_python_types(self):
        assert self.adapter.field_to_python_type(DataField(name="x", type=FieldType.STRING)) == "str"
        assert self.adapter.field_to_python_type(DataField(name="x", type=FieldType.INTEGER)) == "int"

    def test_docker_config(self):
        spec = _make_spec("mongodb")
        assert self.adapter.docker_service_name() == "mongodb"
        assert self.adapter.docker_image() == "mongo:8"
        assert self.adapter.docker_port() == 27017
        env = self.adapter.docker_env(spec)
        assert "MONGO_INITDB_DATABASE" in env

    def test_connection_env_vars(self):
        spec = _make_spec("mongodb")
        env = self.adapter.connection_env_vars(spec)
        assert "MONGODB_URI" in env
        assert "MONGODB_DB" in env

    def test_supported_index_types(self):
        supported = self.adapter.supported_index_types()
        assert IndexType.REGULAR in supported
        assert IndexType.TEXT in supported
        assert IndexType.GEO in supported
        assert IndexType.UNIQUE in supported


# ── PostgreSQL adapter tests ──────────────────────────────────────────────────


class TestPostgreSQLAdapter:
    def setup_method(self):
        self.adapter = PostgreSQLAdapter()

    def test_is_sql(self):
        assert self.adapter.is_sql

    def test_does_not_support_embedded(self):
        assert not self.adapter.supports_embedded()

    def test_does_not_support_time_series(self):
        assert not self.adapter.supports_time_series()

    def test_id_type(self):
        assert self.adapter.id_column_type() == "UUID"
        assert self.adapter.id_python_type() == "uuid.UUID"

    def test_field_column_types(self):
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.STRING)) == "VARCHAR(255)"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.INTEGER)) == "INTEGER"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.FLOAT)) == "DOUBLE PRECISION"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.BOOLEAN)) == "BOOLEAN"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.DATETIME)) == "TIMESTAMPTZ"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.TEXT)) == "TEXT"
        assert self.adapter.field_to_column_type(DataField(name="x", type=FieldType.EMAIL)) == "VARCHAR(320)"
        assert self.adapter.field_to_column_type(
            DataField(name="x", type=FieldType.REFERENCE, reference="owners")
        ) == "UUID"

    def test_string_with_max_length(self):
        f = DataField(name="code", type=FieldType.STRING, max_length=10)
        assert self.adapter.field_to_column_type(f) == "VARCHAR(10)"

    def test_enum_sqla_type(self):
        f = DataField(name="status", type=FieldType.ENUM, enum_values=["a", "b"])
        sqla = self.adapter.field_to_sqla_type(f)
        assert "Enum" in sqla
        assert '"a"' in sqla

    def test_python_types(self):
        assert self.adapter.field_to_python_type(DataField(name="x", type=FieldType.STRING)) == "str"
        assert self.adapter.field_to_python_type(
            DataField(name="x", type=FieldType.REFERENCE, reference="y")
        ) == "uuid.UUID"
        optional = self.adapter.field_to_python_type(
            DataField(name="x", type=FieldType.STRING, required=False)
        )
        assert "None" in optional

    def test_docker_config(self):
        spec = _make_spec("postgresql")
        assert self.adapter.docker_service_name() == "postgres"
        assert self.adapter.docker_image() == "postgres:17"
        assert self.adapter.docker_port() == 5432
        env = self.adapter.docker_env(spec)
        assert "POSTGRES_DB" in env
        assert "POSTGRES_USER" in env

    def test_connection_env_vars(self):
        spec = _make_spec("postgresql")
        env = self.adapter.connection_env_vars(spec)
        assert "DATABASE_URL" in env
        assert "asyncpg" in env["DATABASE_URL"]

    def test_supported_index_types(self):
        supported = self.adapter.supported_index_types()
        assert IndexType.BTREE in supported
        assert IndexType.GIN in supported
        assert IndexType.UNIQUE in supported
        assert IndexType.GEO not in supported

    def test_create_table_column(self):
        f = DataField(name="title", type=FieldType.STRING, required=True, is_unique=True)
        col = self.adapter.create_table_column(f)
        assert "title" in col
        assert "VARCHAR(255)" in col
        assert "NOT NULL" in col
        assert "UNIQUE" in col

    def test_fk_constraint(self):
        f = DataField(name="owner_id", type=FieldType.REFERENCE, reference="owners")
        e = EntitySpec(name="Pet", collection="pets", fields=[f])
        fk = self.adapter.fk_constraint(f, e)
        assert "REFERENCES owners(id)" in fk

    def test_sql_value_literal(self):
        f = DataField(name="x", type=FieldType.STRING)
        assert self.adapter.sql_value_literal(None, f) == "NULL"
        assert self.adapter.sql_value_literal(True, f) == "TRUE"
        assert self.adapter.sql_value_literal(42, f) == "42"
        assert self.adapter.sql_value_literal("hello", f) == "'hello'"
        assert self.adapter.sql_value_literal("it's", f) == "'it''s'"

    def test_sql_index_type(self):
        assert self.adapter.sql_index_type(IndexType.REGULAR) == "btree"
        assert self.adapter.sql_index_type(IndexType.TEXT) == "gin"
        assert self.adapter.sql_index_type(IndexType.UNIQUE) == "btree"

    def test_python_requirements(self):
        reqs = self.adapter.python_requirements()
        assert any("sqlalchemy" in r for r in reqs)
        assert any("asyncpg" in r for r in reqs)


# ── Code generation with different engines ────────────────────────────────────


class TestMongoDBCodegen:
    def test_python_fastapi_generates(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "python-fastapi")
        assert "main.py" in files
        assert "database.py" in files
        assert "routes.py" in files
        assert "AsyncMongoClient" in files["database.py"]
        assert "MONGODB_URI" in files["database.py"]

    def test_mongodb_artifacts_generates(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "mongodb-artifacts")
        assert "indexes.js" in files
        assert "mongo-init/00-setup.js" in files

    def test_typescript_generates(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "typescript-express")
        assert "server.ts" in files
        assert "mongoose" in files["server.ts"]

    def test_python_routes_use_bracket_notation_for_collections(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "python-fastapi")
        routes = files["routes.py"]
        assert 'db["tasks"]' in routes
        assert "db.tasks" not in routes

    def test_mongo_response_reference_fields_are_optional(self):
        spec = _make_ref_spec("mongodb")
        files = generate(spec, "python-fastapi")
        models = files["models.py"]
        assert "class PetResponse(PetCreate):" in models
        assert "owner_id: Optional[str] = Field(None" in models

    def test_typescript_mongo_reference_is_optional_in_document_shape(self):
        spec = _make_ref_spec("mongodb")
        files = generate(spec, "typescript-express")
        models = files["models.ts"]
        assert "owner_id?: mongoose.Types.ObjectId;" in models

    def test_python_list_route_uses_projection(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "python-fastapi")
        routes = files["routes.py"]
        assert "projection" in routes
        assert '"title": 1' in routes
        assert '"created_at": 1' in routes

    def test_typescript_list_route_uses_select(self):
        spec = _make_spec("mongodb")
        files = generate(spec, "typescript-express")
        routes = files["routes.ts"]
        assert ".select(" in routes
        assert "title" in routes

    def test_text_fields_produce_text_index(self):
        spec = AppSpec(
            app_name="Text Test",
            slug="text-test",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Article",
                    collection="articles",
                    description="An article",
                    fields=[
                        DataField(name="title", type=FieldType.STRING),
                        DataField(name="body", type=FieldType.TEXT),
                        DataField(name="summary", type=FieldType.TEXT),
                    ],
                )
            ],
            endpoints=[
                Endpoint(method=HttpMethod.GET, path="/articles", entity="Article", operation=CrudOperation.LIST),
            ],
        )
        files = generate(spec, "mongodb-artifacts")
        indexes = files["indexes.js"]
        assert '"body": "text"' in indexes
        assert '"summary": "text"' in indexes
        assert "articles_text" in indexes

    def test_indexspec_unique_type_produces_unique_option(self):
        spec = AppSpec(
            app_name="Unique Idx",
            slug="unique-idx",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Widget",
                    collection="widgets",
                    description="A widget",
                    fields=[DataField(name="code", type=FieldType.STRING)],
                    indexes=[IndexSpec(type=IndexType.UNIQUE, keys={"code": 1})],
                )
            ],
        )
        files = generate(spec, "mongodb-artifacts")
        indexes = files["indexes.js"]
        assert "unique: true" in indexes

    def test_indexspec_ttl_produces_expire_after(self):
        spec = AppSpec(
            app_name="TTL Idx",
            slug="ttl-idx",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Session",
                    collection="sessions",
                    description="A session",
                    fields=[DataField(name="token", type=FieldType.STRING)],
                    indexes=[IndexSpec(keys={"created_at": 1}, expire_after_seconds=3600)],
                )
            ],
        )
        files = generate(spec, "mongodb-artifacts")
        indexes = files["indexes.js"]
        assert "expireAfterSeconds: 3600" in indexes

    def test_optional_unique_field_gets_sparse(self):
        spec = AppSpec(
            app_name="Sparse Test",
            slug="sparse-test",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Profile",
                    collection="profiles",
                    description="A profile",
                    fields=[
                        DataField(name="name", type=FieldType.STRING),
                        DataField(name="twitter", type=FieldType.STRING, required=False, is_unique=True),
                    ],
                )
            ],
        )
        files = generate(spec, "mongodb-artifacts")
        indexes = files["indexes.js"]
        assert "unique: true" in indexes
        assert "sparse: true" in indexes

    def test_esr_compound_index_generated(self):
        spec = AppSpec(
            app_name="ESR Test",
            slug="esr-test",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Order",
                    collection="orders",
                    description="An order",
                    fields=[
                        DataField(name="status", type=FieldType.ENUM, enum_values=["pending", "done"], is_filterable=True),
                        DataField(name="amount", type=FieldType.FLOAT),
                        DataField(name="placed_at", type=FieldType.DATETIME, is_sortable=True),
                    ],
                )
            ],
            endpoints=[
                Endpoint(method=HttpMethod.GET, path="/orders", entity="Order", operation=CrudOperation.LIST),
            ],
        )
        files = generate(spec, "mongodb-artifacts")
        init_indexes = files["mongo-init/02-indexes.js"]
        assert "esr_compound" in init_indexes
        status_pos = init_indexes.index('"status"')
        placed_pos = init_indexes.index('"placed_at"')
        assert status_pos < placed_pos

    def test_typescript_mongo_ignores_managed_fields_in_schema(self):
        spec = AppSpec(
            app_name="Managed Field Filter",
            slug="managed-field-filter",
            database=DatabaseConfig(engine=DatabaseEngine.MONGODB),
            entities=[
                EntitySpec(
                    name="Thing",
                    collection="things",
                    description="Entity with managed timestamp field in input spec",
                    fields=[
                        DataField(name="name", type=FieldType.STRING),
                        DataField(name="created_at", type=FieldType.DATETIME, required=True),
                    ],
                )
            ],
            endpoints=[
                Endpoint(method=HttpMethod.GET, path="/things", entity="Thing", operation=CrudOperation.LIST),
                Endpoint(method=HttpMethod.POST, path="/things", entity="Thing", operation=CrudOperation.CREATE),
            ],
        )
        files = generate(spec, "typescript-express")
        models = files["models.ts"]
        assert "created_at: { type: Date" not in models
        assert "createdAt?: Date;" in models


class TestPostgreSQLCodegen:
    def test_python_fastapi_generates(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "main.py" in files
        assert "database.py" in files
        assert "routes.py" in files
        assert "models.py" in files

    def test_database_uses_sqlalchemy(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "create_async_engine" in files["database.py"]
        assert "DATABASE_URL" in files["database.py"]
        assert "AsyncMongoClient" not in files["database.py"]

    def test_models_use_sqlalchemy_orm(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "DeclarativeBase" in files["models.py"]
        assert "Mapped" in files["models.py"]
        assert "mapped_column" in files["models.py"]
        assert "TaskRow" in files["models.py"]

    def test_routes_use_sessions(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "AsyncSession" in files["routes.py"]
        assert "get_session" in files["routes.py"]
        assert "ObjectId" not in files["routes.py"]

    def test_docker_compose_uses_postgres(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "postgres:17" in files["docker-compose.yml"]
        assert "POSTGRES_DB" in files["docker-compose.yml"]
        assert "mongo" not in files["docker-compose.yml"].lower()

    def test_requirements_have_sqlalchemy(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "python-fastapi")
        assert "sqlalchemy" in files["requirements.txt"]
        assert "asyncpg" in files["requirements.txt"]
        assert "motor" not in files["requirements.txt"]
        assert "pymongo" not in files["requirements.txt"]

    def test_sql_init_scripts_via_composer(self):
        from appspec.generation.composer import compose_full_project
        spec = _make_spec("postgresql")
        files = compose_full_project(spec, "python-fastapi")
        assert "sql-init/00-schema.sql" in files
        assert "sql-init/01-indexes.sql" in files
        assert "sql-init/02-seed.sql" in files
        assert not any(f.startswith("mongo-init/") for f in files)

    def test_sql_artifacts_generates(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "sql-artifacts")
        assert "schema.sql" in files
        assert "indexes.sql" in files
        assert "seed.sql" in files

    def test_schema_sql_has_create_table(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "sql-artifacts")
        schema = files["schema.sql"]
        assert "CREATE TABLE IF NOT EXISTS tasks" in schema
        assert "CREATE TABLE IF NOT EXISTS users" in schema
        assert "UUID PRIMARY KEY" in schema
        assert "TIMESTAMPTZ" in schema

    def test_schema_dedupes_managed_timestamp_fields(self):
        spec = AppSpec(
            app_name="Timestamp Test",
            slug="timestamp-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Plant",
                    collection="plants",
                    description="Plant entity",
                    fields=[
                        DataField(name="name", type=FieldType.STRING),
                        DataField(name="created_at", type=FieldType.DATETIME, required=True),
                    ],
                )
            ],
            endpoints=[
                Endpoint(method=HttpMethod.GET, path="/plants", entity="Plant", operation=CrudOperation.LIST),
                Endpoint(method=HttpMethod.POST, path="/plants", entity="Plant", operation=CrudOperation.CREATE),
            ],
        )
        files = generate(spec, "sql-artifacts")
        schema = files["schema.sql"]
        sql_init = files["sql-init/00-schema.sql"]
        assert schema.count("created_at TIMESTAMPTZ") == 1
        assert sql_init.count("created_at TIMESTAMPTZ") == 1

    def test_reference_becomes_fk(self):
        spec = _make_ref_spec("postgresql")
        files = generate(spec, "sql-artifacts")
        schema = files["schema.sql"]
        assert "REFERENCES owners(id)" in schema

    def test_deterministic_output(self):
        spec = _make_spec("postgresql")
        files1 = generate(spec, "python-fastapi")
        files2 = generate(spec, "python-fastapi")
        assert files1 == files2

    def test_mongodb_artifacts_not_supported(self):
        spec = _make_spec("postgresql")
        registry = get_registry()
        target = registry.get("mongodb-artifacts")
        assert not target.supports(spec)

    def test_typescript_supports_postgresql(self):
        spec = _make_spec("postgresql")
        registry = get_registry()
        target = registry.get("typescript-express")
        assert target.supports(spec)

    def test_typescript_postgresql_generates(self):
        spec = _make_spec("postgresql")
        files = generate(spec, "typescript-express")
        assert "server.ts" in files
        assert "database.ts" in files
        assert "routes.ts" in files
        assert "models.ts" in files
        assert "pg" in files["package.json"]
        assert "mongoose" not in files["package.json"]
        assert "DATABASE_URL" in files["database.ts"]
        assert "postgres:17" in files["docker-compose.yml"]

    def test_sql_response_reference_fields_are_optional(self):
        spec = _make_ref_spec("postgresql")
        files = generate(spec, "python-fastapi")
        models = files["models.py"]
        assert "class PetResponse(PetCreate):" in models
        assert "owner_id: Optional[str] = Field(None" in models

    def test_typescript_sql_response_reference_fields_are_optional(self):
        spec = _make_ref_spec("postgresql")
        files = generate(spec, "typescript-express")
        models = files["models.ts"]
        assert "export interface Pet {" in models
        assert "owner_id?: string;" in models


# ── Target support matrix ────────────────────────────────────────────────────


class TestTargetSupport:
    def test_sql_artifacts_discovered(self):
        registry = get_registry()
        assert "sql-artifacts" in registry.list_targets()

    def test_sql_artifacts_supports_postgresql(self):
        spec = _make_spec("postgresql")
        registry = get_registry()
        assert registry.get("sql-artifacts").supports(spec)

    def test_sql_artifacts_not_for_mongodb(self):
        spec = _make_spec("mongodb")
        registry = get_registry()
        assert not registry.get("sql-artifacts").supports(spec)

    def test_tailwind_ui_supports_both(self):
        registry = get_registry()
        mongo_spec = _make_spec("mongodb")
        pg_spec = _make_spec("postgresql")
        assert registry.get("tailwind-ui").supports(mongo_spec)
        assert registry.get("tailwind-ui").supports(pg_spec)


# ── Validator engine compatibility ────────────────────────────────────────────


class TestValidatorEngineCompat:
    def test_mongodb_no_compat_warnings(self):
        spec = _make_spec("mongodb")
        result = validate(spec)
        compat_warnings = [
            w for w in result.warnings
            if "mongodb" in w.message.lower() or "JSON column" in w.message
        ]
        assert len(compat_warnings) == 0

    def test_postgresql_embedded_entities_warns(self):
        spec = AppSpec(
            app_name="Embed Test",
            slug="embed-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Parent",
                    collection="parents",
                    description="Parent entity",
                    fields=[DataField(name="name", type=FieldType.STRING)],
                    embedded_entities=[
                        EntitySpec(
                            name="Child",
                            collection="children",
                            fields=[DataField(name="label", type=FieldType.STRING)],
                        )
                    ],
                )
            ],
        )
        result = validate(spec)
        assert any("JSON column" in w.message for w in result.warnings)

    def test_postgresql_time_series_warns(self):
        spec = AppSpec(
            app_name="TS Test",
            slug="ts-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Reading",
                    collection="readings",
                    description="Sensor readings",
                    fields=[DataField(name="ts", type=FieldType.DATETIME)],
                    is_time_series=True,
                    time_field="ts",
                )
            ],
        )
        result = validate(spec)
        assert any("TimescaleDB" in w.message for w in result.warnings)

    def test_postgresql_geo_point_warns(self):
        spec = AppSpec(
            app_name="Geo Test",
            slug="geo-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Place",
                    collection="places",
                    description="A place",
                    fields=[DataField(name="location", type=FieldType.GEO_POINT)],
                )
            ],
        )
        result = validate(spec)
        assert any("PostGIS" in w.message for w in result.warnings)

    def test_postgresql_vector_warns(self):
        spec = AppSpec(
            app_name="Vec Test",
            slug="vec-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Doc",
                    collection="docs",
                    description="A document",
                    fields=[DataField(name="embedding", type=FieldType.VECTOR, vector_dimensions=768)],
                )
            ],
        )
        result = validate(spec)
        assert any("pgvector" in w.message for w in result.warnings)

    def test_postgresql_unsupported_index_type_warns(self):
        spec = AppSpec(
            app_name="Idx Test",
            slug="idx-test",
            database=DatabaseConfig(engine=DatabaseEngine.POSTGRESQL),
            entities=[
                EntitySpec(
                    name="Place",
                    collection="places",
                    description="A place",
                    fields=[DataField(name="loc", type=FieldType.GEO_POINT)],
                    indexes=[IndexSpec(name="geo_idx", type=IndexType.GEO, keys={"loc": "2dsphere"})],
                )
            ],
        )
        result = validate(spec)
        assert any("not natively supported" in w.message for w in result.warnings)


# ── Backward compatibility ────────────────────────────────────────────────────


class TestBackwardCompat:
    def test_spec_without_database_field_defaults_to_mongodb(self):
        spec = AppSpec(
            app_name="Legacy",
            slug="legacy",
            entities=[
                EntitySpec(
                    name="Item",
                    collection="items",
                    fields=[DataField(name="x", type=FieldType.STRING)],
                )
            ],
        )
        assert spec.database.engine == DatabaseEngine.MONGODB

    def test_json_roundtrip_with_database(self):
        spec = _make_spec("postgresql")
        json_str = spec.to_json()
        restored = AppSpec.from_json(json_str)
        assert restored.database.engine == DatabaseEngine.POSTGRESQL

    def test_json_roundtrip_without_database(self):
        data = {"app_name": "Old", "slug": "old", "entities": [
            {"name": "X", "collection": "xs", "fields": [{"name": "a", "type": "string"}]}
        ]}
        import json
        spec = AppSpec.from_json(json.dumps(data))
        assert spec.database.engine == DatabaseEngine.MONGODB

    def test_dict_roundtrip_preserves_engine(self):
        spec = _make_spec("postgresql")
        d = spec.to_dict()
        assert d["database"]["engine"] == "postgresql"
        restored = AppSpec.from_dict(d)
        assert restored.database.engine == DatabaseEngine.POSTGRESQL
