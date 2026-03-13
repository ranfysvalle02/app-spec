"""Render the data-model spec from an AppSpec document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from appspec.generation.renderers import _get_jinja_env

if TYPE_CHECKING:
    from appspec.models import AppSpec


def render(spec: "AppSpec") -> str:
    env = _get_jinja_env()
    template = env.get_template("data_model.md.jinja")
    return template.render(spec=spec)
