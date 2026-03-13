"""Tests for the Markdown renderers."""

from appspec.models import (
    AppSpec,
    AuthSpec,
    CrudOperation,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
)
from appspec.generation.renderers import render_all
from appspec.generation.renderers.data_model import render as render_data_model
from appspec.generation.renderers.api import render as render_api
from appspec.generation.renderers.features import render as render_features


def _make_spec() -> AppSpec:
    return AppSpec(
        app_name="Renderer Test",
        slug="renderer-test",
        description="Test application",
        auth=AuthSpec(enabled=True, strategy="jwt", roles=["admin"]),
        entities=[
            EntitySpec(
                name="Widget",
                collection="widgets",
                description="A widget",
                fields=[
                    DataField(name="name", type=FieldType.STRING, is_sortable=True),
                    DataField(
                        name="color",
                        type=FieldType.ENUM,
                        enum_values=["red", "blue"],
                        is_filterable=True,
                    ),
                ],
            )
        ],
        endpoints=[
            Endpoint(
                method=HttpMethod.GET,
                path="/widgets",
                entity="Widget",
                operation=CrudOperation.LIST,
                filters=["color"],
            )
        ],
    )


class TestRenderers:
    def test_render_all_produces_three_files(self):
        spec = _make_spec()
        files = render_all(spec)
        assert "appspec/specs/data-model/spec.md" in files
        assert "appspec/specs/api/spec.md" in files
        assert "appspec/specs/features/spec.md" in files

    def test_data_model_contains_entity(self):
        md = render_data_model(_make_spec())
        assert "Widget" in md
        assert "widgets" in md
        assert "name" in md
        assert "color" in md

    def test_data_model_contains_enum_values(self):
        md = render_data_model(_make_spec())
        assert "red" in md
        assert "blue" in md

    def test_api_contains_endpoint(self):
        md = render_api(_make_spec())
        assert "GET" in md
        assert "/widgets" in md

    def test_api_contains_auth(self):
        md = render_api(_make_spec())
        assert "jwt" in md

    def test_features_contains_app_name(self):
        md = render_features(_make_spec())
        assert "Renderer Test" in md

    def test_render_is_deterministic(self):
        spec = _make_spec()
        files1 = render_all(spec)
        files2 = render_all(spec)
        assert files1 == files2
