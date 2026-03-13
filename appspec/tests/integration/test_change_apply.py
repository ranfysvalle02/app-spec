"""Tests for the change apply functionality."""

import json
from pathlib import Path

from click.testing import CliRunner

from appspec.cli.main import main
from appspec.cli.commands.change import _deep_merge


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        delta = {"b": 3, "c": 4}
        result = _deep_merge(base, delta)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"auth": {"enabled": False, "strategy": "jwt"}}
        delta = {"auth": {"enabled": True}}
        result = _deep_merge(base, delta)
        assert result["auth"]["enabled"] is True
        assert result["auth"]["strategy"] == "jwt"

    def test_list_replacement(self):
        base = {"roles": ["user"]}
        delta = {"roles": ["admin", "user"]}
        result = _deep_merge(base, delta)
        assert result["roles"] == ["admin", "user"]

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        delta = {"a": {"b": 2}}
        _deep_merge(base, delta)
        assert base["a"]["b"] == 1


class TestChangeApplyCLI:
    def test_apply_valid_delta(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Apply Test", "--dir", str(tmp_path)])

        changes_dir = tmp_path / "appspec" / "changes" / "test-change"
        changes_dir.mkdir(parents=True)
        delta = {"description": "Updated description"}
        (changes_dir / "spec-delta.json").write_text(json.dumps(delta))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["change", "apply", "test-change", "-y"])
            assert result.exit_code == 0
            assert "Applied" in result.output

        spec_data = json.loads(
            (tmp_path / "appspec" / "appspec.json").read_text()
        )
        assert spec_data["description"] == "Updated description"

    def test_apply_empty_delta(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Empty Delta", "--dir", str(tmp_path)])

        changes_dir = tmp_path / "appspec" / "changes" / "empty"
        changes_dir.mkdir(parents=True)
        (changes_dir / "spec-delta.json").write_text("{}")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["change", "apply", "empty", "-y"])
            assert result.exit_code == 0
            assert "empty" in result.output.lower()

    def test_apply_missing_change(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Missing", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["change", "apply", "nonexistent", "-y"])
            assert result.exit_code == 1
