"""Change proposal management commands."""

from __future__ import annotations

import copy
import json
import sys

import click

from appspec.cli.main import main, console, _find_appspec_dir


def _deep_merge(base: dict, delta: dict) -> dict:
    """Recursively merge delta into base. Lists are replaced, not appended."""
    result = copy.deepcopy(base)
    for key, value in delta.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


@main.group()
def change():
    """Manage change proposals."""
    pass


@change.command("new")
@click.argument("change_id")
def change_new(change_id: str):
    """Create a new change proposal."""
    from appspec.generation.renderers import _get_jinja_env

    folder = _find_appspec_dir()
    changes_dir = folder / "changes" / change_id
    if changes_dir.exists():
        console.print(f"[red]Change '{change_id}' already exists.[/red]")
        sys.exit(1)

    changes_dir.mkdir(parents=True)

    env = _get_jinja_env()
    try:
        tmpl = env.get_template("change_proposal.md.jinja")
        proposal_content = tmpl.render(change_id=change_id)
    except Exception:
        proposal_content = f"# Change Proposal: {change_id}\n\n## Summary\n\n## Tasks\n"

    (changes_dir / "proposal.md").write_text(proposal_content, encoding="utf-8")
    (changes_dir / "design.md").write_text(
        f"# Design: {change_id}\n\n## Technical Decisions\n", encoding="utf-8"
    )
    (changes_dir / "tasks.md").write_text(
        f"# Tasks: {change_id}\n\n- [ ] Task 1\n- [ ] Task 2\n", encoding="utf-8"
    )
    (changes_dir / "spec-delta.json").write_text("{}\n", encoding="utf-8")

    console.print(f"\n[green]Created change proposal: {change_id}[/green]\n")
    console.print(f"  [dim]{changes_dir / 'proposal.md'}[/dim]")
    console.print(f"  [dim]{changes_dir / 'design.md'}[/dim]")
    console.print(f"  [dim]{changes_dir / 'tasks.md'}[/dim]")
    console.print(f"  [dim]{changes_dir / 'spec-delta.json'}[/dim]")


@change.command("diff")
@click.argument("change_id")
def change_diff(change_id: str):
    """Show the spec delta for a change proposal."""
    folder = _find_appspec_dir()
    delta_path = folder / "changes" / change_id / "spec-delta.json"
    if not delta_path.exists():
        console.print(f"[red]Change '{change_id}' not found or has no spec-delta.json[/red]")
        sys.exit(1)

    raw = json.loads(delta_path.read_text(encoding="utf-8"))
    console.print_json(json.dumps(raw, indent=2))


@change.command("apply")
@click.argument("change_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def change_apply(change_id: str, yes: bool):
    """Apply a change proposal's spec-delta to appspec.json."""
    from appspec.models import AppSpec
    from appspec.validation import validate as run_validate

    folder = _find_appspec_dir()
    delta_path = folder / "changes" / change_id / "spec-delta.json"
    if not delta_path.exists():
        console.print(f"[red]Change '{change_id}' not found or has no spec-delta.json[/red]")
        sys.exit(1)

    spec_path = folder / "appspec.json"
    if not spec_path.exists():
        console.print(f"[red]No appspec.json found in {folder}[/red]")
        sys.exit(1)

    base = json.loads(spec_path.read_text(encoding="utf-8"))
    delta = json.loads(delta_path.read_text(encoding="utf-8"))

    if not delta:
        console.print("[yellow]spec-delta.json is empty — nothing to apply.[/yellow]")
        return

    merged = _deep_merge(base, delta)

    try:
        new_spec = AppSpec.from_dict(merged)
    except Exception as e:
        console.print(f"[red]Merged spec is invalid:[/red] {e}")
        sys.exit(1)

    result = run_validate(new_spec)
    if not result.valid:
        console.print(f"[red]Merged spec fails validation:[/red] {result.summary()}")
        for issue in result.errors:
            console.print(f"  [red]ERROR[/red] {issue.path}: {issue.message}")
        sys.exit(1)

    console.print(f"\n[bold]Changes from '{change_id}':[/bold]")
    console.print_json(json.dumps(delta, indent=2))

    if not yes:
        if not click.confirm("\nApply this delta to appspec.json?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    spec_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    console.print(f"\n[green]Applied '{change_id}' to appspec.json[/green]")

    if result.warnings:
        for issue in result.warnings:
            console.print(f"  [yellow]WARN[/yellow] {issue.path}: {issue.message}")
