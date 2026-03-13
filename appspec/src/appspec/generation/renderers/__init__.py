"""
AppSpec Renderers
=================

Convert an AppSpec document into human-readable Markdown spec files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from appspec.models import AppSpec

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_all(spec: "AppSpec") -> dict[str, str]:
    """Render all Markdown spec files from an AppSpec document.

    Returns a dict of {relative_path: content}.
    """
    from appspec.generation.renderers.data_model import render as render_data_model
    from appspec.generation.renderers.api import render as render_api
    from appspec.generation.renderers.features import render as render_features

    files: dict[str, str] = {}
    files["appspec/specs/data-model/spec.md"] = render_data_model(spec)
    files["appspec/specs/api/spec.md"] = render_api(spec)
    files["appspec/specs/features/spec.md"] = render_features(spec)
    return files
