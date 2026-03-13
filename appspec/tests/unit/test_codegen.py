"""Tests for the deterministic code generation engine."""

from appspec.generation.registry import TargetRegistry, generate, get_registry
from appspec.models import (
    AppSpec,
    CrudOperation,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
)


def _make_spec() -> AppSpec:
    return AppSpec(
        app_name="Codegen Test",
        slug="codegen-test",
        entities=[
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
                ],
            )
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/tasks", entity="Task", operation=CrudOperation.LIST),
            Endpoint(method=HttpMethod.POST, path="/tasks", entity="Task", operation=CrudOperation.CREATE),
            Endpoint(method=HttpMethod.GET, path="/tasks/{id}", entity="Task", operation=CrudOperation.GET),
            Endpoint(method=HttpMethod.PUT, path="/tasks/{id}", entity="Task", operation=CrudOperation.UPDATE),
            Endpoint(method=HttpMethod.DELETE, path="/tasks/{id}", entity="Task", operation=CrudOperation.DELETE),
        ],
    )


class TestTargetRegistry:
    def test_auto_discover(self):
        registry = get_registry()
        targets = registry.list_targets()
        assert "python-fastapi" in targets
        assert "typescript-express" in targets
        assert "mongodb-artifacts" in targets

    def test_get_unknown_target_raises(self):
        registry = TargetRegistry()
        try:
            registry.get("nonexistent")
            assert False, "Should have raised"
        except KeyError:
            pass


class TestPythonFastAPITarget:
    def test_generates_expected_files(self):
        spec = _make_spec()
        files = generate(spec, "python-fastapi")
        assert "main.py" in files
        assert "models.py" in files
        assert "routes.py" in files
        assert "database.py" in files
        assert "requirements.txt" in files

    def test_deterministic_output(self):
        spec = _make_spec()
        files1 = generate(spec, "python-fastapi")
        files2 = generate(spec, "python-fastapi")
        assert files1 == files2

    def test_main_contains_app_name(self):
        spec = _make_spec()
        files = generate(spec, "python-fastapi")
        assert "Codegen Test" in files["main.py"]

    def test_models_contain_entity(self):
        spec = _make_spec()
        files = generate(spec, "python-fastapi")
        assert "TaskCreate" in files["models.py"]
        assert "TaskResponse" in files["models.py"]


class TestTypescriptExpressTarget:
    def test_generates_expected_files(self):
        spec = _make_spec()
        files = generate(spec, "typescript-express")
        assert "server.ts" in files
        assert "models.ts" in files
        assert "routes.ts" in files
        assert "package.json" in files

    def test_deterministic_output(self):
        spec = _make_spec()
        files1 = generate(spec, "typescript-express")
        files2 = generate(spec, "typescript-express")
        assert files1 == files2


class TestMongoDBTarget:
    def test_generates_expected_files(self):
        spec = _make_spec()
        files = generate(spec, "mongodb-artifacts")
        assert "indexes.js" in files
        assert "validation.json" in files
        assert "setup.js" in files

    def test_indexes_contain_filterable(self):
        spec = _make_spec()
        files = generate(spec, "mongodb-artifacts")
        assert "status" in files["indexes.js"]

    def test_deterministic_output(self):
        spec = _make_spec()
        files1 = generate(spec, "mongodb-artifacts")
        files2 = generate(spec, "mongodb-artifacts")
        assert files1 == files2
