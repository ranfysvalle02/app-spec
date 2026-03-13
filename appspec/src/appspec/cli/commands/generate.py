"""Code generation commands: generate, targets."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from appspec.cli.main import main, console, _load_spec


@main.command()
@click.option("--target", required=True, help="Code generation target name")
@click.option("--output", "-o", default="generated", help="Output directory")
def generate(target: str, output: str):
    """Generate code from the spec using a deterministic target."""
    from appspec.generation.registry import generate as run_generate

    spec, folder = _load_spec()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = run_generate(spec, target)

    for filepath, content in files.items():
        full_path = output_dir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    console.print(
        f"\n[green]Generated {len(files)} files with target "
        f"[bold]{target}[/bold] → {output_dir}[/green]\n"
    )
    for fp in sorted(files):
        console.print(f"  [dim]{fp}[/dim]")


@main.command("targets")
def list_targets():
    """List available code generation targets."""
    from appspec.generation.registry import get_registry

    registry = get_registry()
    names = registry.list_targets()

    if not names:
        console.print("[yellow]No targets discovered.[/yellow]")
        return

    table = Table(title="Available Targets")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")

    for name in names:
        t = registry.get(name)
        table.add_row(t.name, t.description)

    console.print(table)
