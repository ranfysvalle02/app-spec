"""Spec folder I/O: serialize/deserialize AppSpec to the canonical folder structure."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appspec.models import AppSpec


def compile_to_folder(spec: "AppSpec", output_dir: Path) -> dict[str, Path]:
    """Write an AppSpec document to the canonical folder structure."""
    from appspec.generation.renderers import render_all

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    json_path = output_dir / "appspec.json"
    json_path.write_text(spec.to_json(), encoding="utf-8")
    written["appspec.json"] = json_path

    md_files = render_all(spec)
    for rel_path, content in md_files.items():
        stripped = rel_path
        if stripped.startswith("appspec/"):
            stripped = stripped[len("appspec/"):]
        full_path = output_dir / stripped
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        written[stripped] = full_path

    changes_dir = output_dir / "changes"
    changes_dir.mkdir(exist_ok=True)
    gitkeep = changes_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        written["changes/.gitkeep"] = gitkeep

    return written


def load_from_folder(folder: Path) -> "AppSpec":
    """Load an AppSpec document from an appspec/ folder."""
    from appspec.models import AppSpec

    json_path = folder / "appspec.json"
    if not json_path.exists():
        raise FileNotFoundError(f"No appspec.json found in {folder}")
    raw = json_path.read_text(encoding="utf-8")
    return AppSpec.from_json(raw)


def load_from_file(path: Path) -> "AppSpec":
    """Load an AppSpec from a standalone JSON file."""
    from appspec.models import AppSpec

    raw = path.read_text(encoding="utf-8")
    return AppSpec.from_json(raw)
