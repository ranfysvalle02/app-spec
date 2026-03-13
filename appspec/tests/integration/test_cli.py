"""Tests for the AppSpec CLI."""

from pathlib import Path

from click.testing import CliRunner

from appspec.cli.main import main


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_init(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--name", "CLI Test", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert (tmp_path / "appspec" / "appspec.json").exists()

    def test_validate_valid(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Valid App", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["validate"])
            assert result.exit_code == 0
            assert "Valid" in result.output

    def test_show(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Show Test", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["show"])
            assert result.exit_code == 0
            assert "Show Test" in result.output

    def test_show_json(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "JSON Test", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["show", "--json"])
            assert result.exit_code == 0
            assert '"slug"' in result.output

    def test_targets(self):
        runner = CliRunner()
        result = runner.invoke(main, ["targets"])
        assert result.exit_code == 0
        assert "python-fastapi" in result.output

    def test_generate(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Gen Test", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            out_dir = tmp_path / "output"
            result = runner.invoke(
                main, ["generate", "--target", "python-fastapi", "-o", str(out_dir)]
            )
            assert result.exit_code == 0
            assert (out_dir / "main.py").exists()

    def test_change_new(self, tmp_path: Path):
        runner = CliRunner()
        runner.invoke(main, ["init", "--name", "Change Test", "--dir", str(tmp_path)])

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["change", "new", "add-auth"])
            assert result.exit_code == 0
            assert "Created change proposal" in result.output
            assert (tmp_path / "appspec" / "changes" / "add-auth" / "proposal.md").exists()
