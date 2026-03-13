"""Tailwind UI — backend-agnostic CRUD frontend target.

Produces a single ``index.html`` that uses Tailwind CSS (CDN) and vanilla JS
to provide a full CRUD interface against any backend that exposes the standard
AppSpec REST convention (``/api/{collection}``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from appspec.generation.contracts import BaseTarget

if TYPE_CHECKING:
    from appspec.models import AppSpec

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


class TailwindUITarget(BaseTarget):
    name = "tailwind-ui"
    description = "Zero-build Tailwind CSS + vanilla JS CRUD frontend (backend-agnostic)"

    def supports(self, spec: "AppSpec") -> bool:
        return bool(spec.entities)

    def render(self, spec: "AppSpec") -> dict[str, str]:
        env = _env()
        return {
            "index.html": env.get_template("index.html.jinja").render(spec=spec),
        }
