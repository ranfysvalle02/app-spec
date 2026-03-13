"""Multi-target composition — the only place that orchestrates cross-target output.

Replaces the previous pattern where targets called other targets directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from appspec.generation.registry import get_registry

if TYPE_CHECKING:
    from appspec.models import AppSpec


def compose_full_project(spec: "AppSpec", primary_target: str) -> dict[str, str]:
    """Generate a complete project by composing a primary backend target with
    its database init scripts and a UI target.

    Returns ``{filepath: content}`` for all files.
    """
    registry = get_registry()
    files: dict[str, str] = {}

    primary = registry.get(primary_target)
    if not primary.supports(spec):
        raise ValueError(
            f"Target '{primary_target}' does not support this spec "
            f"(engine={spec.database.engine.value})"
        )
    files.update(primary.render(spec))

    _compose_db_init(spec, files)
    _compose_ui(spec, files)

    return files


def _compose_db_init(spec: "AppSpec", files: dict[str, str]) -> None:
    """Add database init scripts if the appropriate artifact target exists."""
    registry = get_registry()
    engine = spec.database.engine.value

    if engine == "mongodb":
        artifact_target = "mongodb-artifacts"
        init_prefix = "mongo-init/"
    elif engine == "postgresql":
        artifact_target = "sql-artifacts"
        init_prefix = "sql-init/"
    else:
        return

    try:
        target = registry.get(artifact_target)
    except KeyError:
        return

    if not target.supports(spec):
        return

    artifact_files = target.render(spec)
    for fp, content in artifact_files.items():
        if fp.startswith(init_prefix) and fp not in files:
            files[fp] = content


def _compose_ui(spec: "AppSpec", files: dict[str, str]) -> None:
    """Add Tailwind UI files under static/."""
    registry = get_registry()
    try:
        ui_target = registry.get("tailwind-ui")
    except KeyError:
        return

    if not ui_target.supports(spec):
        return

    ui_files = ui_target.render(spec)
    for fp, content in ui_files.items():
        files[f"static/{fp}"] = content
