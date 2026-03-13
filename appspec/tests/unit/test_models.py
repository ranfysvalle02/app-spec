"""Tests for the AppSpec document model."""


import pytest
from pydantic import ValidationError

from appspec.models import (
    AppSpec,
    AuthSpec,
    CrudOperation,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
    IndexSpec,
    UISpec,
)


def _minimal_spec(**overrides) -> dict:
    base = {
        "app_name": "Test App",
        "slug": "test-app",
        "entities": [
            {
                "name": "Item",
                "collection": "items",
                "fields": [{"name": "title", "type": "string"}],
            }
        ],
    }
    base.update(overrides)
    return base


class TestDataField:
    def test_enum_requires_values(self):
        with pytest.raises(ValidationError, match="enum_values required"):
            DataField(name="status", type=FieldType.ENUM)

    def test_reference_requires_target(self):
        with pytest.raises(ValidationError, match="reference collection required"):
            DataField(name="owner_id", type=FieldType.REFERENCE)

    def test_vector_requires_dimensions(self):
        with pytest.raises(ValidationError, match="vector_dimensions must be"):
            DataField(name="embedding", type=FieldType.VECTOR)

    def test_valid_enum_field(self):
        f = DataField(name="status", type=FieldType.ENUM, enum_values=["active", "archived"])
        assert f.enum_values == ["active", "archived"]

    def test_valid_reference_field(self):
        f = DataField(name="owner_id", type=FieldType.REFERENCE, reference="users")
        assert f.reference == "users"

    def test_field_name_must_be_snake_case(self):
        with pytest.raises(ValidationError, match="field name must be lowercase snake_case"):
            DataField(name="Owner ID", type=FieldType.STRING)


class TestEntitySpec:
    def test_time_series_requires_time_field(self):
        with pytest.raises(ValidationError, match="time_field is required"):
            EntitySpec(
                name="Reading",
                collection="readings",
                fields=[],
                is_time_series=True,
            )

    def test_valid_time_series(self):
        e = EntitySpec(
            name="Reading",
            collection="readings",
            fields=[DataField(name="ts", type=FieldType.DATETIME)],
            is_time_series=True,
            time_field="ts",
        )
        assert e.time_field == "ts"


class TestAppSpec:
    def test_minimal_spec(self):
        spec = AppSpec(**_minimal_spec())
        assert spec.slug == "test-app"
        assert len(spec.entities) == 1

    def test_cross_ref_invalid_relationship(self):
        data = _minimal_spec()
        data["entities"][0]["relationships"] = ["NonExistent"]
        with pytest.raises(ValidationError, match="unknown entity 'NonExistent'"):
            AppSpec(**data)

    def test_cross_ref_invalid_reference_field(self):
        data = _minimal_spec()
        data["entities"][0]["fields"].append(
            {"name": "owner_id", "type": "reference", "reference": "nonexistent"}
        )
        with pytest.raises(ValidationError, match="unknown collection 'nonexistent'"):
            AppSpec(**data)

    def test_cross_ref_invalid_endpoint_entity(self):
        data = _minimal_spec()
        data["endpoints"] = [
            {"method": "GET", "path": "/x", "entity": "Ghost", "operation": "list"}
        ]
        with pytest.raises(ValidationError, match="unknown entity 'Ghost'"):
            AppSpec(**data)

    def test_roundtrip_json(self):
        spec = AppSpec(**_minimal_spec())
        json_str = spec.to_json()
        restored = AppSpec.from_json(json_str)
        assert restored.slug == spec.slug
        assert len(restored.entities) == len(spec.entities)

    def test_roundtrip_dict(self):
        spec = AppSpec(**_minimal_spec())
        d = spec.to_dict()
        assert isinstance(d, dict)
        restored = AppSpec.from_dict(d)
        assert restored.app_name == spec.app_name

    def test_requires_at_least_one_entity(self):
        with pytest.raises(ValidationError):
            AppSpec(app_name="Empty", slug="empty", entities=[])

    def test_full_spec_with_all_features(self):
        spec = AppSpec(
            app_name="Full Test",
            slug="full-test",
            description="A comprehensive test spec",
            auth=AuthSpec(enabled=True, strategy="jwt", roles=["admin", "user"]),
            entities=[
                EntitySpec(
                    name="Widget",
                    collection="widgets",
                    fields=[
                        DataField(name="name", type=FieldType.STRING),
                        DataField(
                            name="status",
                            type=FieldType.ENUM,
                            enum_values=["active", "inactive"],
                            is_filterable=True,
                        ),
                    ],
                    indexes=[
                        IndexSpec(name="status_idx", keys={"status": 1}),
                    ],
                )
            ],
            endpoints=[
                Endpoint(
                    method=HttpMethod.GET,
                    path="/widgets",
                    entity="Widget",
                    operation=CrudOperation.LIST,
                    filters=["status"],
                )
            ],
            ui=UISpec(framework="vue"),
            metadata={"version": "2.0"},
        )
        assert spec.auth.enabled
        assert spec.ui.framework == "vue"
        assert spec.metadata["version"] == "2.0"
