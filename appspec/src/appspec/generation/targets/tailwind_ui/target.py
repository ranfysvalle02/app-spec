"""Tailwind UI — backend-agnostic frontend target with composable page sections.

Produces a single ``index.html`` that uses Tailwind CSS (CDN) and vanilla JS
to provide a full page-driven interface against any backend that exposes the
standard AppSpec REST convention (``/api/{collection}``).

Pages, layouts, and section types are defined in ``spec.ui.pages``.  When pages
are absent, ``_ensure_pages`` from the LLM pipeline auto-generates a dashboard
plus one CRUD page per entity for backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader

from appspec.generation.contracts import BaseTarget
from appspec.models import SectionType

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


def _pages_to_json(pages: list[Any]) -> str:
    """Serialize page specs to a JS-embeddable JSON array."""
    out = []
    for p in pages:
        pd = p.model_dump(mode="json") if hasattr(p, "model_dump") else dict(p)
        out.append(pd)
    return json.dumps(out, indent=2)


class TailwindUITarget(BaseTarget):
    name = "tailwind-ui"
    description = "Zero-build Tailwind CSS + vanilla JS frontend with composable page sections (backend-agnostic)"

    def supports(self, spec: "AppSpec") -> bool:
        return bool(spec.entities)

    def render(self, spec: "AppSpec") -> dict[str, str]:
        from appspec.llm.pipeline import _ensure_pages

        spec = _ensure_pages(spec)
        pages = spec.ui.pages

        has_charts = any(
            section.type == SectionType.CHART
            for page in pages
            for section in page.sections
        )

        env = _env()
        html = env.get_template("base.html.jinja").render(
            spec=spec,
            pages=pages,
            pages_json=_pages_to_json(pages),
            has_charts=has_charts,
        )
        return {"index.html": html}
