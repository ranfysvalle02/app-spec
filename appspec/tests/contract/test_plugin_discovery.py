"""Contract tests: verify target plugin discovery and template asset integrity."""

from appspec.generation.registry import get_registry
from appspec.generation.contracts import BaseTarget


class TestPluginDiscovery:
    def test_all_builtin_targets_discovered(self):
        registry = get_registry()
        names = registry.list_targets()
        assert "python-fastapi" in names
        assert "typescript-express" in names
        assert "mongodb-artifacts" in names
        assert "sql-artifacts" in names
        assert "tailwind-ui" in names

    def test_each_target_has_name_and_description(self):
        registry = get_registry()
        for name in registry.list_targets():
            target = registry.get(name)
            assert target.name, f"Target {name} has no name"
            assert target.description, f"Target {name} has no description"

    def test_targets_are_base_target_subclasses(self):
        registry = get_registry()
        for name in registry.list_targets():
            target = registry.get(name)
            assert isinstance(target, BaseTarget)

    def test_unknown_target_raises(self):
        import pytest
        registry = get_registry()
        with pytest.raises(KeyError, match="Unknown target"):
            registry.get("nonexistent-target")


class TestTemplateAssets:
    def test_renderer_templates_exist(self):
        from pathlib import Path
        import appspec.generation.renderers as renderers_pkg
        templates_dir = Path(renderers_pkg.__file__).parent / "templates"
        assert templates_dir.exists()
        assert (templates_dir / "data_model.md.jinja").exists()
        assert (templates_dir / "api.md.jinja").exists()
        assert (templates_dir / "features.md.jinja").exists()

    def test_target_templates_exist(self):
        from pathlib import Path
        import appspec.generation.targets as targets_pkg
        targets_dir = Path(targets_pkg.__file__).parent

        expected = {
            "python_fastapi": ["templates"],
            "typescript_express": ["templates"],
            "mongodb_artifacts": ["templates"],
            "sql_artifacts": ["templates"],
            "tailwind_ui": ["templates"],
        }

        for target_name, subdirs in expected.items():
            target_path = targets_dir / target_name
            assert target_path.exists(), f"Target directory missing: {target_name}"
            for subdir in subdirs:
                assert (target_path / subdir).exists(), f"Templates missing: {target_name}/{subdir}"
