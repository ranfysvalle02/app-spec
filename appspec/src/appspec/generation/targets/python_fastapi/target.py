"""Python + FastAPI code generation target (MongoDB or SQL)."""

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


def _env(*search_paths: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader([str(p) for p in search_paths]),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


class PythonFastAPITarget(BaseTarget):
    name = "python-fastapi"
    description = "Python backend with FastAPI, database-agnostic (MongoDB or PostgreSQL)"

    def supports(self, spec: "AppSpec") -> bool:
        return spec.database.engine in (DatabaseEngine.MONGODB, DatabaseEngine.POSTGRESQL)

    def render(self, spec: "AppSpec") -> dict[str, str]:
        adapter = get_adapter(spec.database.engine)
        engine_dir = "mongodb" if not adapter.is_sql else "sql"
        engine_path = _TEMPLATES / engine_dir

        env = _env(engine_path, _TEMPLATES)
        ctx = {"spec": spec, "db": adapter}
        files: dict[str, str] = {}

        tmpl_names = [
            "main.py", "models.py", "routes.py", "database.py",
            "requirements.txt", "Dockerfile", "docker-compose.yml",
        ]
        if spec.auth.enabled:
            tmpl_names.append("auth.py")

        for tmpl_name in tmpl_names:
            jinja_name = f"{tmpl_name}.jinja"
            resolved = engine_path / jinja_name
            if not resolved.exists():
                resolved = _TEMPLATES / jinja_name
            if resolved.exists():
                files[tmpl_name] = env.get_template(jinja_name).render(**ctx)

        return files
