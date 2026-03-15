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
│   ├── engine_compat.py        # Database engine compatibility warnings
│   └── pages.py                # Page/section validation (data_source, IDs, configs)
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
│       ├── mongodb_artifacts/  # Language-agnostic DB init (see below)
│       ├── sql_artifacts/
│       └── tailwind_ui/        # Composable page/section frontend
├── llm/                        # LLM-powered spec generation
│   ├── client.py               # litellm wrapper, DEFAULT_MODEL
│   ├── prompts.py              # System prompts for schema + seed + pages
│   └── pipeline.py             # create_spec(), create_sample_data(), _ensure_pages()
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

4. **Validation is modular.** Each validation concern (schema, quality, safety, engine-compat, pages) is in its own module. New checks can be added without touching the others.

5. **Templates are colocated.** Each target and renderer keeps its Jinja2 templates in a `templates/` subdirectory next to its Python module. Templates load via `Path(__file__).parent / "templates"`.

6. **Frontend is backend-agnostic.** The `tailwind-ui` target generates a single `index.html` that communicates with any backend via a standard REST convention (`GET/POST/PUT/DELETE /{collection}`). The same frontend works with `python-fastapi`, `typescript-express`, or any future backend target.

## The Mongosh Init Scripts Trick: Language-Agnostic Database Setup

One of the most powerful architectural patterns in AppSpec is using **MongoDB shell (`mongosh`) init scripts** to push all database setup logic out of the application layer and into Docker's entrypoint. This makes the database setup completely **language-agnostic** — it works identically whether your backend is Python, TypeScript, Go, Rust, or anything else.

### How It Works

When MongoDB starts in Docker, it automatically executes any `.js` files found in `/docker-entrypoint-initdb.d/` (in alphabetical order). AppSpec exploits this by generating a numbered sequence of pure JavaScript init scripts:

```
mongo-init/
├── 00-setup.js       # Create collections (incl. time-series, capped)
├── 01-validation.js  # Apply $jsonSchema validation rules per collection
├── 02-indexes.js     # Create all indexes (compound, text, geo, TTL, unique)
└── 03-seed.js        # Insert sample data for development
```

The generated `docker-compose.yml` mounts this folder:

```yaml
services:
  mongo:
    image: mongo:7
    volumes:
      - ./mongo-init:/docker-entrypoint-initdb.d:ro
```

### Why This Matters

**Traditional approach**: every backend framework re-implements collection creation, schema validation, index management, and seed data in its own language. A Python app uses PyMongo, a Node app uses the MongoDB driver, a Go app uses the official Go driver — all doing the same work differently, with different bugs.

**AppSpec approach**: the `mongodb-artifacts` target generates idempotent `mongosh` scripts that run once at container startup. The backend application code never touches indexes, validation rules, or seed data — it just connects and starts serving CRUD. This means:

- **Swap backends freely.** Switch from `python-fastapi` to `typescript-express` (or any future target) without rewriting database setup. The `mongo-init/` scripts don't change.
- **Database-as-code.** The init scripts are deterministic, version-controlled artifacts generated from the spec. `git diff` shows exactly what changed in your database schema.
- **Zero application-startup overhead.** The database is fully configured before the app process even starts. No migration scripts, no "ensure indexes on first request" patterns.
- **DevOps-friendly.** `docker compose up` gives you a fully initialized database with sample data. No separate setup step.

### The Composition Pattern

The `composer.py` module orchestrates this cleanly. When generating a full project:

1. The **primary target** (e.g. `python-fastapi`) renders backend code
2. The **mongodb-artifacts** target renders `mongo-init/*.js` scripts
3. The **tailwind-ui** target renders `static/index.html`

All three are independent, pure render functions. The composer just merges their outputs into one file tree. The backend code has no knowledge of the init scripts. The init scripts have no knowledge of the backend language. The frontend has no knowledge of either.

```
compose_full_project(spec, "python-fastapi")
  ├── primary.render(spec)         → main.py, routes.py, models.py, ...
  ├── mongodb-artifacts.render(spec) → mongo-init/00-setup.js, 01-validation.js, ...
  └── tailwind-ui.render(spec)     → static/index.html
```

This three-layer independence is what makes AppSpec's "generate, preview, download" loop so fast — the AI describes the app, the templates render all three layers deterministically, and the result runs anywhere Docker runs.

## CustomPage Template Architecture

The `tailwind-ui` target uses a composable template system where pages, layouts, and sections are separate Jinja2 partials:

```
tailwind_ui/templates/
├── base.html.jinja           # HTML shell, page composition, all JS logic
├── partials/                  # Shared UI fragments
│   ├── auth.html.jinja       # Login/register screen
│   ├── nav.html.jinja        # Page-driven tab navigation
│   ├── modal.html.jinja      # CRUD modals
│   └── toast.html.jinja      # Notifications
├── layouts/                   # Page layout strategies
│   ├── single.html.jinja     # Full-width stacked sections
│   ├── sidebar.html.jinja    # Main + sidebar
│   └── dashboard.html.jinja  # CSS grid with col_span/row_span
└── sections/                  # Self-contained section types
    ├── table.html.jinja      # CRUD table with sort, filter, pagination
    ├── chart.html.jinja      # Chart.js (pie, bar, line, doughnut)
    ├── kpi_row.html.jinja    # Stats cards with client-side aggregation
    ├── card_grid.html.jinja  # Responsive card layout
    ├── form.html.jinja       # Standalone create form
    ├── detail.html.jinja     # Single-record view
    ├── list.html.jinja       # Activity feed / log
    ├── calendar.html.jinja   # Date-based view
    ├── map.html.jinja        # Geo visualization
    ├── markdown.html.jinja   # Static content
    └── custom.html.jinja     # Raw HTML/JS/CSS passthrough
```

The LLM generates `ui.pages` in the spec, which defines which pages exist, what layout each uses, and what sections they contain. When pages are absent, `_ensure_pages()` auto-generates a dashboard with KPIs and charts plus one CRUD page per entity. The frontend is fully CSP-safe (no inline event handlers — uses `data-action` delegation) and includes a fetch cache, error boundaries, URL hash routing, and loading skeletons.

## Adding a New Target

See [plugin-authoring.md](plugin-authoring.md).
