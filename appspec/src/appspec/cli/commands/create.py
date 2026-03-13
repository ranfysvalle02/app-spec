"""Full LLM pipeline command: prompt -> spec -> validate -> seed -> generate."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from appspec.cli.main import main, console


@main.command("create")
@click.argument("prompt")
@click.option("--target", default="python-fastapi", help="Code generation target")
@click.option("--output", "-o", default=None, help="Output directory (default: derived from slug)")
@click.option("--model", default="gemini/gemini-2.5-flash", help="LLM model string")
@click.option("--run", is_flag=True, help="Run docker compose up after generation")
@click.option("--dry-run", is_flag=True, help="Show what would be generated without writing files")
@click.option("--no-seed", is_flag=True, help="Skip seed data generation")
def create(prompt: str, target: str, output: str | None, model: str, run: bool,
           dry_run: bool, no_seed: bool):
    """Generate a full app from a natural language description."""
    import asyncio
    import subprocess

    try:
        from appspec.llm import create_spec, create_sample_data
    except ImportError:
        console.print(
            "[red]LLM support requires litellm.[/red]\n"
            "Install with: [bold]pip install appspec\\[llm][/bold]"
        )
        sys.exit(1)

    console.print(f"\n[bold]Creating app from:[/bold] {prompt}")
    console.print(f"[dim]Model: {model} | Target: {target}[/dim]\n")

    with console.status("[bold green]Generating AppSpec via LLM..."):
        try:
            spec = asyncio.run(create_spec(prompt, model=model))
        except Exception as e:
            console.print(f"[red]LLM generation failed:[/red] {e}")
            sys.exit(1)

    console.print(f"[green]Generated spec:[/green] {spec.app_name} ({spec.slug})")
    console.print(f"  Entities: {len(spec.entities)}, Endpoints: {len(spec.endpoints)}")

    from appspec.validation import validate as run_validate

    result = run_validate(spec)
    if not result.valid:
        console.print(f"\n[red]Validation failed:[/red] {result.summary()}")
        for issue in result.errors:
            console.print(f"  [red]ERROR[/red] {issue.path}: {issue.message}")
        sys.exit(1)
    console.print("[green]Validation passed.[/green]")

    if not no_seed:
        with console.status("[bold green]Generating seed data..."):
            try:
                from appspec.models import AppSpec as AppSpecModel
                seed_data = asyncio.run(create_sample_data(spec, model=model))
                if seed_data:
                    data = spec.to_dict()
                    data["sample_data"] = seed_data
                    spec = AppSpecModel.from_dict(data)
                    total_docs = sum(len(docs) for docs in seed_data.values())
                    console.print(f"[green]Seed data:[/green] {total_docs} documents across {len(seed_data)} collections")
            except Exception as e:
                console.print(f"[yellow]Seed data generation failed ({e}), continuing without.[/yellow]")

    if dry_run:
        from appspec.generation.composer import compose_full_project
        code_files = compose_full_project(spec, target)
        console.print(f"\n[bold]Dry run — would generate {len(code_files)} files:[/bold]")
        for fp in sorted(code_files):
            console.print(f"  [dim]{fp}[/dim]")
        console.print(f"\nOutput directory: {output or spec.slug}")
        return

    output_dir = Path(output) if output else Path(spec.slug)
    output_dir.mkdir(parents=True, exist_ok=True)

    from appspec.compiler import compile_to_folder

    appspec_dir = output_dir / "appspec"
    compile_to_folder(spec, appspec_dir)
    console.print(f"[green]Wrote appspec/ to {appspec_dir}[/green]")

    from appspec.generation.composer import compose_full_project

    code_files = compose_full_project(spec, target)
    for filepath, content in code_files.items():
        full_path = output_dir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    console.print(
        f"[green]Generated {len(code_files)} files with target "
        f"[bold]{target}[/bold] → {output_dir}[/green]"
    )

    console.print(f"\n[bold green]Project ready at {output_dir}/[/bold green]")
    for fp in sorted(code_files):
        console.print(f"  [dim]{fp}[/dim]")

    if run:
        console.print("\n[bold]Starting docker compose...[/bold]")
        try:
            subprocess.run(
                ["docker", "compose", "up", "--build", "-d"],
                cwd=str(output_dir),
                check=True,
            )
            console.print("\n[bold green]App running at http://localhost:8000[/bold green]")
            console.print("  API docs: http://localhost:8000/docs")
            console.print("  Health:   http://localhost:8000/health")
        except FileNotFoundError:
            console.print("[red]docker compose not found. Install Docker Desktop.[/red]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]docker compose failed (exit {e.returncode})[/red]")
    else:
        console.print("\nNext steps:")
        console.print(f"  cd {output_dir}")
        console.print("  docker compose up --build")
