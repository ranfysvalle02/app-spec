"""Tests for the AppSpec validator."""

from appspec.models import AppSpec, DataField, Endpoint, EntitySpec, FieldType, HttpMethod, CrudOperation
from appspec.validation import validate


def _make_spec(**overrides) -> AppSpec:
    base = {
        "app_name": "Test App",
        "slug": "test-app",
        "entities": [
            EntitySpec(
                name="Item",
                collection="items",
                description="A test item",
                fields=[DataField(name="title", type=FieldType.STRING)],
            )
        ],
    }
    base.update(overrides)
    return AppSpec(**base)


class TestValidator:
    def test_valid_spec_passes(self):
        spec = _make_spec()
        result = validate(spec)
        assert result.valid

    def test_bad_slug(self):
        spec = _make_spec(slug="BAD SLUG!")
        result = validate(spec)
        assert not result.valid
        assert any("slug" in i.path for i in result.errors)

    def test_duplicate_collection(self):
        spec = _make_spec(
            entities=[
                EntitySpec(name="A", collection="items", fields=[DataField(name="x", type=FieldType.STRING)]),
                EntitySpec(name="B", collection="items", fields=[DataField(name="y", type=FieldType.STRING)]),
            ]
        )
        result = validate(spec)
        assert not result.valid
        assert any("Duplicate collection" in i.message for i in result.errors)

    def test_duplicate_entity_name(self):
        spec = _make_spec(
            entities=[
                EntitySpec(name="Item", collection="items_a", fields=[DataField(name="x", type=FieldType.STRING)]),
                EntitySpec(name="Item", collection="items_b", fields=[DataField(name="y", type=FieldType.STRING)]),
            ]
        )
        result = validate(spec)
        assert not result.valid
        assert any("Duplicate entity" in i.message for i in result.errors)

    def test_duplicate_field_name(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Item",
                    collection="items",
                    fields=[
                        DataField(name="title", type=FieldType.STRING),
                        DataField(name="title", type=FieldType.STRING),
                    ],
                )
            ]
        )
        result = validate(spec)
        assert not result.valid
        assert any("Duplicate field" in i.message for i in result.errors)

    def test_duplicate_endpoint(self):
        spec = _make_spec(
            endpoints=[
                Endpoint(method=HttpMethod.GET, path="/items", entity="Item", operation=CrudOperation.LIST),
                Endpoint(method=HttpMethod.GET, path="/items", entity="Item", operation=CrudOperation.LIST),
            ]
        )
        result = validate(spec)
        assert not result.valid
        assert any("Duplicate endpoint" in i.message for i in result.errors)

    def test_auth_required_but_disabled_warns(self):
        spec = _make_spec(
            endpoints=[
                Endpoint(
                    method=HttpMethod.GET,
                    path="/items",
                    entity="Item",
                    operation=CrudOperation.LIST,
                    auth_required=True,
                )
            ]
        )
        result = validate(spec)
        assert result.valid  # warnings don't fail
        assert any("auth is disabled" in i.message for i in result.warnings)

    def test_missing_description_warns(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Item",
                    collection="items",
                    fields=[DataField(name="x", type=FieldType.STRING)],
                )
            ]
        )
        result = validate(spec)
        assert result.valid
        assert any("no description" in i.message for i in result.warnings)

    def test_thin_entity_warns(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Genre",
                    collection="genres",
                    description="A music genre",
                    fields=[
                        DataField(name="name", type=FieldType.STRING),
                        DataField(name="is_active", type=FieldType.BOOLEAN),
                    ],
                )
            ]
        )
        result = validate(spec)
        assert result.valid
        assert any("non-reference field" in w.message and "Genre" in w.message for w in result.warnings)

    def test_normal_entity_no_thin_warning(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Album",
                    collection="albums",
                    description="A music album",
                    fields=[
                        DataField(name="title", type=FieldType.STRING),
                        DataField(name="artist", type=FieldType.STRING),
                        DataField(name="year", type=FieldType.INTEGER),
                        DataField(name="genre", type=FieldType.ENUM, enum_values=["rock", "pop"]),
                    ],
                )
            ]
        )
        result = validate(spec)
        thin_warnings = [w for w in result.warnings if "non-reference field" in w.message]
        assert len(thin_warnings) == 0

    def test_missing_relationships_warns(self):
        spec = _make_spec(
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
                        DataField(name="species", type=FieldType.STRING),
                        DataField(name="breed", type=FieldType.STRING),
                        DataField(name="owner_id", type=FieldType.REFERENCE, reference="owners"),
                    ],
                ),
            ]
        )
        result = validate(spec)
        assert result.valid
        assert any("relationships" in w.path and "Pet" in w.message for w in result.warnings)

    def test_errors_and_warnings_summary(self):
        result = validate(_make_spec())
        assert isinstance(result.summary(), str)
