"""MongoDB-native artifacts code generation target.

Produces indexes, $jsonSchema validation, aggregation pipelines, and setup
scripts. Stack-agnostic — works with any backend language.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from appspec.generation.contracts import BaseTarget
from appspec.models import DatabaseEngine

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


class MongoDBTarget(BaseTarget):
    name = "mongodb-artifacts"
    description = "MongoDB-native artifacts: indexes, validation, aggregations, setup, seed, docker init"

    def supports(self, spec: "AppSpec") -> bool:
        return spec.database.engine == DatabaseEngine.MONGODB

    def render(self, spec: "AppSpec") -> dict[str, str]:
        env = _env()
        ctx = {"spec": spec}
        files: dict[str, str] = {}

        for tmpl_name in ("indexes.js", "validation.json", "aggregations.js", "setup.js",
                          "seed.js"):
            jinja_name = f"{tmpl_name}.jinja"
            tmpl_path = _TEMPLATES / jinja_name
            if tmpl_path.exists():
                files[tmpl_name] = env.get_template(jinja_name).render(**ctx)

        mongo_init_map = {
            "mongo-init/00-setup.js": "mongo_init_setup.js.jinja",
            "mongo-init/01-validation.js": "mongo_init_validation.js.jinja",
            "mongo-init/02-indexes.js": "mongo_init_indexes.js.jinja",
            "mongo-init/03-seed.js": "mongo_init_seed.js.jinja",
        }
        for out_path, jinja_name in mongo_init_map.items():
            tmpl_path = _TEMPLATES / jinja_name
            if tmpl_path.exists():
                files[out_path] = env.get_template(jinja_name).render(**ctx)

        return files
