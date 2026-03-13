# AppSpec Architecture

## Package Structure

```
appspec/src/appspec/
├── __init__.py                 # Top-level re-exports (AppSpec, FieldType, etc.)
├── models.py                   # Pydantic V2 document model (the most-read file)
├── validation/                 # Spec validation (split by concern)
│   ├── __init__.py             # validate() entry point + ValidationResult
│   ├── schema.py               # Naming and cross-reference checks
│   ├── quality.py              # Entity/endpoint quality linting
│   ├── safety.py               # Secrets and dangerous pattern scanning
│   └── engine_compat.py        # Database engine compatibility warnings
├── engines/                    # Database engine adapters
│   ├── __init__.py             # get_adapter() factory
│   ├── base.py                 # DatabaseAdapter ABC
│   ├── mongodb.py              # MongoDBAdapter
│   └── postgresql.py           # PostgreSQLAdapter
├── generation/                 # Deterministic code generation
│   ├── contracts.py            # BaseTarget ABC (plugin contract)
│   ├── registry.py             # TargetRegistry + auto-discovery + entry-points
│   ├── composer.py             # Multi-target composition (the ONLY composition point)
│   ├── renderers/              # Markdown rendering (Jinja2)
│   │   ├── __init__.py         # render_all()
│   │   ├── data_model.py, api.py, features.py
│   │   └── templates/          # .jinja template files
│   └── targets/                # Code generation targets (plugins)
│       ├── python_fastapi/
│       ├── typescript_express/
│       ├── mongodb_artifacts/
│       ├── sql_artifacts/
│       └── tailwind_ui/
├── llm/                        # LLM-powered spec generation
│   ├── client.py               # litellm wrapper, DEFAULT_MODEL
│   ├── prompts.py              # System prompts for schema + seed generation
│   └── pipeline.py             # create_spec(), create_sample_data()
├── store/                      # MongoDB persistence
│   └── mongodb.py              # AppSpecStore (persist, search, audit)
├── cli/                        # CLI layer — thin command handlers
│   ├── main.py                 # Click group, entry point
│   └── commands/               # One module per command group
│       ├── spec.py             # init, validate, render, show
│       ├── generate.py         # generate, targets
│       ├── change.py           # change new/diff/apply
│       ├── mongodb.py          # push, search, stats, audit
│       └── create.py           # Full LLM pipeline
├── compiler.py                 # Spec folder serialization/deserialization
└── scaffold.py                 # Project scaffolding (init_folder)
```

## Layer Dependencies

```
CLI → Models, Validation, Generation, LLM, Store, Compiler  (thin orchestration only)
Validation → Models + Engines (for engine compat checks)
Engines → Models (for type references)
Generation → Models + Engines (for rendering context)
LLM → Models + Validation (spec generation + retry loop)
Store → Models (for serialization)
Compiler → Models + Generation/Renderers
```

## Key Design Rules

1. **CLI is thin.** Command modules only parse arguments and call into generation/validation/llm APIs. No business logic in CLI.

2. **Targets are pure.** Each target renders ONLY its own files. No target calls another target. The `generation/composer.py` is the single composition point for combining backend + db-init + UI targets.

3. **Discovery is explicit.** The `TargetRegistry` logs warnings when target imports fail (no silent swallowing). External targets register via `[project.entry-points."appspec.targets"]`.

4. **Validation is modular.** Each validation concern (schema, quality, safety, engine-compat) is in its own module. New checks can be added without touching the others.

5. **Templates are colocated.** Each target and renderer keeps its Jinja2 templates in a `templates/` subdirectory next to its Python module. Templates load via `Path(__file__).parent / "templates"`.

## Adding a New Target

See [plugin-authoring.md](plugin-authoring.md).
