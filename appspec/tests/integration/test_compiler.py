"""Tests for the AppSpec compiler."""

from pathlib import Path

import pytest

from appspec.compiler import compile_to_folder, load_from_file, load_from_folder
from appspec.scaffold import init_folder
from appspec.models import AppSpec, DataField, EntitySpec, FieldType


def _make_spec() -> AppSpec:
    return AppSpec(
        app_name="Compiler Test",
        slug="compiler-test",
        entities=[
            EntitySpec(
                name="Widget",
                collection="widgets",
                fields=[DataField(name="name", type=FieldType.STRING)],
            )
        ],
    )


class TestCompiler:
    def test_compile_to_folder(self, tmp_path: Path):
        spec = _make_spec()
        output = tmp_path / "appspec"
        written = compile_to_folder(spec, output)

        assert (output / "appspec.json").exists()
        assert (output / "specs" / "data-model" / "spec.md").exists()
        assert (output / "specs" / "api" / "spec.md").exists()
        assert (output / "specs" / "features" / "spec.md").exists()
        assert len(written) >= 4

    def test_load_from_folder(self, tmp_path: Path):
        spec = _make_spec()
        output = tmp_path / "appspec"
        compile_to_folder(spec, output)

        loaded = load_from_folder(output)
        assert loaded.slug == spec.slug
        assert len(loaded.entities) == 1

    def test_load_from_file(self, tmp_path: Path):
        spec = _make_spec()
        json_path = tmp_path / "spec.json"
        json_path.write_text(spec.to_json())

        loaded = load_from_file(json_path)
        assert loaded.app_name == "Compiler Test"

    def test_init_folder(self, tmp_path: Path):
        written = init_folder(tmp_path, app_name="My New App")

        assert (tmp_path / "appspec" / "appspec.json").exists()
        assert len(written) >= 4

        loaded = load_from_folder(tmp_path / "appspec")
        assert loaded.app_name == "My New App"
        assert loaded.slug == "my-new-app"

    def test_load_missing_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_from_folder(tmp_path / "nonexistent")

    def test_roundtrip_preserves_data(self, tmp_path: Path):
        spec = _make_spec()
        output = tmp_path / "appspec"
        compile_to_folder(spec, output)
        loaded = load_from_folder(output)

        assert loaded.to_dict() == spec.to_dict()
