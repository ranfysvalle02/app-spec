# Migration Guide: v1 to v2

AppSpec v2 is a major breaking re-architecture. All import paths have changed. This guide maps every old import to its new location.

## Import Path Changes

| Old Path (v1) | New Path (v2) |
|---|---|
| `appspec.models` | `appspec.models` (unchanged) |
| `appspec.db` | `appspec.engines` |
| `appspec.db.get_adapter` | `appspec.engines.get_adapter` |
| `appspec.db.DatabaseAdapter` | `appspec.engines.base.DatabaseAdapter` |
| `appspec.db.MongoDBAdapter` | `appspec.engines.mongodb.MongoDBAdapter` |
| `appspec.db.PostgreSQLAdapter` | `appspec.engines.postgresql.PostgreSQLAdapter` |
| `appspec.validator` | `appspec.validation` |
| `appspec.validator.validate` | `appspec.validation.validate` |
| `appspec.validator.ValidationResult` | `appspec.validation.ValidationResult` |
| `appspec.codegen` | `appspec.generation.registry` |
| `appspec.codegen.BaseTarget` | `appspec.generation.contracts.BaseTarget` |
| `appspec.codegen.generate` | `appspec.generation.registry.generate` |
| `appspec.codegen.get_registry` | `appspec.generation.registry.get_registry` |
| `appspec.compiler` | `appspec.compiler` (unchanged) |
| `appspec.compiler.compile_to_folder` | `appspec.compiler.compile_to_folder` (unchanged) |
| `appspec.compiler.init_folder` | `appspec.scaffold.init_folder` |
| `appspec.llm` | `appspec.llm` (unchanged) |
| `appspec.llm.create_spec` | `appspec.llm.create_spec` (unchanged) |
| `appspec.llm.create_sample_data` | `appspec.llm.create_sample_data` (unchanged) |
| `appspec.llm.DEFAULT_MODEL` | `appspec.llm.DEFAULT_MODEL` (unchanged) |
| `appspec.mongodb` | `appspec.store` |
| `appspec.mongodb.AppSpecStore` | `appspec.store.mongodb.AppSpecStore` |
| `appspec.renderers` | `appspec.generation.renderers` |
| `appspec.renderers.render_all` | `appspec.generation.renderers.render_all` |
| `appspec.cli` | `appspec.cli.main` |

## Top-Level Convenience Imports

The top-level `appspec` package still re-exports all model classes for convenience:

```python
from appspec import AppSpec, DataField, EntitySpec, FieldType  # still works
```

## Target Plugin Changes

Targets no longer call other targets directly. If your custom target previously did:

```python
from appspec.codegen import generate as _gen
mongo_files = _gen(spec, "mongodb-artifacts")
```

Remove this. Targets should only render their own files. Use `appspec.generation.composer.compose_full_project()` at the orchestration layer to combine targets.

## CLI Entry Point

The CLI entry point changed from `appspec.cli:main` to `appspec.cli.main:main`. Update your `pyproject.toml` if you reference it.
