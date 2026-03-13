# Writing an AppSpec Target Plugin

AppSpec targets are pluggable code generation backends. Each target consumes a validated `AppSpec` document and produces a set of files.

## Quick Start

1. Create a Python package with your target class.
2. Subclass `BaseTarget` from `appspec.generation.contracts`.
3. Register via entry points in your `pyproject.toml`.

## Target Contract

```python
from appspec.generation.contracts import BaseTarget


class GoFiberTarget(BaseTarget):
    name = "go-fiber"
    description = "Go backend with Fiber framework"

    def supports(self, spec):
        """Return True if this target can handle the given spec."""
        return spec.database.engine.value == "postgresql"

    def render(self, spec):
        """Return {filepath: content} for all generated files.

        MUST be deterministic: same spec in, same files out.
        MUST be pure: do not call other targets.
        """
        files = {}
        files["main.go"] = _render_main(spec)
        files["models.go"] = _render_models(spec)
        return files
```

## Rules

- **`name`**: kebab-case identifier used in `appspec generate --target <name>`.
- **`description`**: one-line description shown in `appspec targets`.
- **`supports(spec)`**: return `False` if the target cannot handle the spec (e.g., wrong database engine). The framework will skip it gracefully.
- **`render(spec)`**: return a dict of `{relative_filepath: file_content}`. Must be deterministic and must not call other targets.

## Registration via Entry Points

In your package's `pyproject.toml`:

```toml
[project.entry-points."appspec.targets"]
go-fiber = "my_package.target:GoFiberTarget"
```

AppSpec's registry will discover your target automatically when it's installed in the same environment.

## Built-in Discovery

If you're contributing a target to the AppSpec core package, place it at:

```
appspec/src/appspec/generation/targets/<name>/
├── target.py       # Contains your BaseTarget subclass
└── templates/      # Jinja2 templates
```

The registry auto-discovers any `BaseTarget` subclass in `appspec.generation.targets.*.target` modules.

## Using Templates

Most targets use Jinja2 templates. Load them relative to `__file__`:

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATES = Path(__file__).parent / "templates"

def _env():
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
```

## Accessing Engine Adapters

If your target needs database-specific type mappings:

```python
from appspec.engines import get_adapter

adapter = get_adapter(spec.database.engine)
column_type = adapter.field_to_column_type(field)
```

## Testing

Write tests that verify your target:

1. Produces expected files for a sample spec.
2. Is deterministic (same spec -> same output).
3. Correctly returns `False` from `supports()` for unsupported specs.

See `tests/unit/test_codegen.py` for examples.
