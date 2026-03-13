"""Tests for the Tailwind UI code generation target."""

from appspec.generation.registry import generate, get_registry
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


def _make_spec() -> AppSpec:
    return AppSpec(
        app_name="Widget Store",
        slug="widget-store",
        description="A store for widgets",
        auth=AuthSpec(enabled=True, strategy="jwt", roles=["admin", "user"]),
        entities=[
            EntitySpec(
                name="Widget",
                collection="widgets",
                description="A purchasable widget",
                fields=[
                    DataField(name="name", type=FieldType.STRING, required=True, is_sortable=True),
                    DataField(
                        name="category",
                        type=FieldType.ENUM,
                        enum_values=["gadget", "tool", "part"],
                        is_filterable=True,
                    ),
                    DataField(name="price", type=FieldType.FLOAT, min_value=0, is_sortable=True),
                    DataField(name="in_stock", type=FieldType.BOOLEAN, is_filterable=True),
                    DataField(name="notes", type=FieldType.TEXT, required=False),
                    DataField(name="email", type=FieldType.EMAIL, required=False),
                    DataField(name="created_at", type=FieldType.DATETIME, is_sortable=True),
                ],
            ),
            EntitySpec(
                name="Order",
                collection="orders",
                description="A customer order",
                fields=[
                    DataField(
                        name="widget_id",
                        type=FieldType.REFERENCE,
                        reference="widgets",
                        required=True,
                    ),
                    DataField(name="quantity", type=FieldType.INTEGER, required=True, min_value=1),
                    DataField(
                        name="status",
                        type=FieldType.ENUM,
                        enum_values=["pending", "shipped", "delivered"],
                        is_filterable=True,
                    ),
                ],
                relationships=["Widget"],
            ),
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/widgets", entity="Widget", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/widgets", entity="Widget", operation=CrudOperation.CREATE),
            Endpoint(method=HttpMethod.GET, path="/widgets/{id}", entity="Widget", operation=CrudOperation.GET),
            Endpoint(method=HttpMethod.PUT, path="/widgets/{id}", entity="Widget", operation=CrudOperation.UPDATE),
            Endpoint(method=HttpMethod.DELETE, path="/widgets/{id}", entity="Widget", operation=CrudOperation.DELETE),
            Endpoint(method=HttpMethod.GET, path="/orders", entity="Order", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/orders", entity="Order", operation=CrudOperation.CREATE),
        ],
    )


class TestTailwindUIDiscovery:
    def test_target_is_discovered(self):
        registry = get_registry()
        assert "tailwind-ui" in registry.list_targets()

    def test_target_supports_any_spec(self):
        registry = get_registry()
        target = registry.get("tailwind-ui")
        assert target.supports(_make_spec())


class TestTailwindUIGeneration:
    def test_generates_single_index_html(self):
        files = generate(_make_spec(), "tailwind-ui")
        assert list(files.keys()) == ["index.html"]

    def test_deterministic_output(self):
        spec = _make_spec()
        assert generate(spec, "tailwind-ui") == generate(spec, "tailwind-ui")

    def test_contains_app_name(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "Widget Store" in html

    def test_contains_app_description(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "A store for widgets" in html

    def test_contains_api_base_constant(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "API_BASE" in html
        assert "/api" in html

    def test_contains_tailwind_cdn(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "cdn.tailwindcss.com" in html

    def test_contains_entity_tabs(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "Widget" in html
        assert "Order" in html
        assert 'data-collection="widgets"' in html
        assert 'data-collection="orders"' in html

    def test_contains_entity_metadata(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "'widgets'" in html
        assert "'orders'" in html
        assert "ENTITIES" in html

    def test_contains_field_definitions(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "'name'" in html
        assert "'category'" in html
        assert "'price'" in html
        assert "'in_stock'" in html

    def test_enum_values_embedded(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert '"gadget"' in html
        assert '"tool"' in html
        assert '"part"' in html

    def test_field_types_embedded(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "'string'" in html
        assert "'enum'" in html
        assert "'float'" in html
        assert "'boolean'" in html
        assert "'datetime'" in html
        assert "'reference'" in html
        assert "'integer'" in html

    def test_filterable_and_sortable_flags(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "filterable: true" in html
        assert "sortable: true" in html

    def test_crud_functions_present(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "fetchList" in html
        assert "createOne" in html
        assert "updateOne" in html
        assert "deleteOne" in html

    def test_modal_elements_present(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert 'id="modal"' in html
        assert 'id="modal-form"' in html
        assert 'id="delete-modal"' in html

    def test_form_rendering_function(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "renderForm" in html
        assert "renderTable" in html
        assert "renderFilters" in html

    def test_min_max_constraints(self):
        html = generate(_make_spec(), "tailwind-ui")["index.html"]
        assert "min: 0" in html
