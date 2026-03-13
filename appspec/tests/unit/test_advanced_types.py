"""Tests for advanced field types (geo_point, vector) in code generation."""

from appspec.generation.registry import generate
from appspec.models import (
    AppSpec,
    CrudOperation,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
)


def _make_spec_with_geo() -> AppSpec:
    return AppSpec(
        app_name="Geo Test",
        slug="geo-test",
        entities=[
            EntitySpec(
                name="Location",
                collection="locations",
                description="A geolocated place",
                fields=[
                    DataField(name="name", type=FieldType.STRING),
                    DataField(name="coordinates", type=FieldType.GEO_POINT),
                ],
            )
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/locations", entity="Location", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/locations", entity="Location", operation=CrudOperation.CREATE),
        ],
    )


def _make_spec_with_vector() -> AppSpec:
    return AppSpec(
        app_name="Vector Test",
        slug="vector-test",
        entities=[
            EntitySpec(
                name="Document",
                collection="documents",
                description="A document with embeddings",
                fields=[
                    DataField(name="title", type=FieldType.STRING),
                    DataField(name="embedding", type=FieldType.VECTOR, vector_dimensions=768),
                ],
            )
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/documents", entity="Document", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/documents", entity="Document", operation=CrudOperation.CREATE),
        ],
    )


class TestGeoPointPythonFastAPI:
    def test_models_contain_geo_type(self):
        files = generate(_make_spec_with_geo(), "python-fastapi")
        assert "geo_point" in files["models.py"] or "dict[str, Any]" in files["models.py"]
        assert "Point" in files["models.py"]

    def test_deterministic(self):
        spec = _make_spec_with_geo()
        assert generate(spec, "python-fastapi") == generate(spec, "python-fastapi")


class TestGeoPointTypeScript:
    def test_models_contain_geo_type(self):
        files = generate(_make_spec_with_geo(), "typescript-express")
        assert "coordinates" in files["models.ts"]
        assert "Point" in files["models.ts"]


class TestGeoPointMongoDB:
    def test_validation_contains_geo_schema(self):
        files = generate(_make_spec_with_geo(), "mongodb-artifacts")
        assert "Point" in files["validation.json"]

    def test_indexes_contain_2dsphere(self):
        files = generate(_make_spec_with_geo(), "mongodb-artifacts")
        assert "2dsphere" in files["indexes.js"]

    def test_mongo_init_indexes_contain_2dsphere(self):
        files = generate(_make_spec_with_geo(), "mongodb-artifacts")
        assert "2dsphere" in files["mongo-init/02-indexes.js"]


class TestVectorPythonFastAPI:
    def test_models_contain_vector_type(self):
        files = generate(_make_spec_with_vector(), "python-fastapi")
        assert "list[float]" in files["models.py"]


class TestVectorTypeScript:
    def test_models_contain_vector_type(self):
        files = generate(_make_spec_with_vector(), "typescript-express")
        assert "number[]" in files["models.ts"]


class TestVectorMongoDB:
    def test_validation_contains_array(self):
        files = generate(_make_spec_with_vector(), "mongodb-artifacts")
        assert "array" in files["validation.json"]
