"""SQL-native artifacts code generation target.

Produces CREATE TABLE schemas, indexes, and seed INSERT scripts.
Stack-agnostic — works with any backend language targeting SQL databases.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from appspec.generation.contracts import BaseTarget
from appspec.engines import get_adapter
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


class SQLArtifactsTarget(BaseTarget):
    name = "sql-artifacts"
    description = "SQL-native artifacts: schema, indexes, seed data, docker init scripts"

    def supports(self, spec: "AppSpec") -> bool:
        return spec.database.engine == DatabaseEngine.POSTGRESQL

    def render(self, spec: "AppSpec") -> dict[str, str]:
        adapter = get_adapter(spec.database.engine)
        env = _env()
        ctx = {"spec": spec, "db": adapter}
        files: dict[str, str] = {}

        for tmpl_name in ("schema.sql", "indexes.sql", "seed.sql"):
            jinja_name = f"{tmpl_name}.jinja"
            tmpl_path = _TEMPLATES / jinja_name
            if tmpl_path.exists():
                files[tmpl_name] = env.get_template(jinja_name).render(**ctx)

        sql_init_map = {
            "sql-init/00-schema.sql": "sql_init_schema.sql.jinja",
            "sql-init/01-indexes.sql": "sql_init_indexes.sql.jinja",
            "sql-init/02-seed.sql": "sql_init_seed.sql.jinja",
        }
        for out_path, jinja_name in sql_init_map.items():
            tmpl_path = _TEMPLATES / jinja_name
            if tmpl_path.exists():
                files[out_path] = env.get_template(jinja_name).render(**ctx)

        return files
