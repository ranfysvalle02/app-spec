"""Spec management commands: init, validate, render, show."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.table import Table

from appspec.cli.main import main, console, _load_spec


@main.command()
@click.option("--name", default="My App", help="Application name")
@click.option("--dir", "target_dir", default=".", help="Target directory")
def init(name: str, target_dir: str):
    """Scaffold a new appspec/ folder with a starter spec."""
    from appspec.scaffold import init_folder

    target = Path(target_dir)
    written = init_folder(target, app_name=name)
    console.print(f"\n[green]Initialized appspec/ in {target.resolve()}[/green]\n")
    for rel in sorted(written):
        console.print(f"  [dim]{rel}[/dim]")
    console.print(f"\n  [bold]{len(written)} files created.[/bold]")
    console.print("\nNext steps:")
    console.print("  1. Edit [bold]appspec/appspec.json[/bold] to define your entities")
    console.print("  2. Run [bold]appspec validate[/bold] to check the spec")
    console.print("  3. Run [bold]appspec generate --target python-fastapi[/bold]")


@main.command()
def validate():
    """Validate the current appspec.json."""
    from appspec.validation import validate as run_validate

    spec, folder = _load_spec()
    result = run_validate(spec)

    if result.errors:
        console.print(f"\n[red bold]Validation FAILED[/red bold] — {result.summary()}\n")
        for issue in result.errors:
            console.print(f"  [red]ERROR[/red]   {issue.path}: {issue.message}")
    if result.warnings:
        if not result.errors:
            console.print()
        for issue in result.warnings:
            console.print(f"  [yellow]WARN[/yellow]    {issue.path}: {issue.message}")
    if result.valid:
        console.print(f"\n[green bold]Valid[/green bold] — {result.summary()}")

    sys.exit(0 if result.valid else 1)


@main.command()
def render():
    """Render appspec.json into human-readable Markdown specs."""
    from appspec.compiler import compile_to_folder

    spec, folder = _load_spec()
    written = compile_to_folder(spec, folder)
    console.print(f"\n[green]Rendered {len(written)} files in {folder}[/green]\n")
    for rel in sorted(written):
        console.print(f"  [dim]{rel}[/dim]")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("--md", "as_md", is_flag=True, help="Output Markdown summary")
def show(as_json: bool, as_md: bool):
    """Display the current spec."""
    spec, folder = _load_spec()

    if as_json:
        click.echo(spec.to_json())
        return

    if as_md:
        from appspec.generation.renderers.data_model import render as render_dm
        click.echo(render_dm(spec))
        return

    table = Table(title=f"{spec.app_name} ({spec.slug})")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Schema Version", spec.schema_version)
    table.add_row("Description", spec.description or "—")
    table.add_row("Auth", f"{spec.auth.strategy}" if spec.auth.enabled else "Disabled")
    table.add_row("Entities", str(len(spec.entities)))
    table.add_row("Endpoints", str(len(spec.endpoints)))
    table.add_row("UI Framework", spec.ui.framework)
    console.print(table)

    console.print("\n[bold]Entities:[/bold]")
    for entity in spec.entities:
        console.print(
            f"  [cyan]{entity.name}[/cyan] → [dim]{entity.collection}[/dim] "
            f"({len(entity.fields)} fields)"
        )
