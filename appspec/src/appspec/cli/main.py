"""CLI entry point and shared utilities."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

_appspec_path_override: Path | None = None


def _find_appspec_dir() -> Path:
    if _appspec_path_override is not None:
        return _appspec_path_override

    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "appspec"
        if (candidate / "appspec.json").exists():
            return candidate
    return cwd / "appspec"


def _load_spec():
    from appspec.compiler import load_from_folder

    folder = _find_appspec_dir()
    if not (folder / "appspec.json").exists():
        console.print(
            f"[red]No appspec.json found in {folder}[/red]\n"
            "Run [bold]appspec init[/bold] to create one."
        )
        sys.exit(1)
    return load_from_folder(folder), folder


@click.group()
@click.version_option(package_name="appspec")
@click.option("--path", "appspec_path", default=None, type=click.Path(exists=False),
              help="Path to appspec/ directory (default: auto-detect)")
def main(appspec_path: str | None):
    """AppSpec — The Document Model for AI Code Generation."""
    global _appspec_path_override
    if appspec_path:
        _appspec_path_override = Path(appspec_path)


# Register command groups
from appspec.cli.commands import spec, generate, change, mongodb, create  # noqa: E402, F401
