# AppSpec

**One sentence in. Full-stack app out.**

Describe what you want in plain English. AppSpec calls Gemini to produce a structured JSON spec, validates it with Pydantic, generates realistic seed data, then deterministically renders a complete app — FastAPI backend, your choice of MongoDB or PostgreSQL, Tailwind CRUD UI — ready to `docker compose up`.

```
"A veterinary clinic app to manage pet owners, patients, and appointments"
    ↓
 Gemini 2.5 Flash (schema)  +  Gemini 2.5 Flash (seed data)
    ↓                              ↓
 AppSpec JSON (validated)     15 realistic records
    ↓
 Jinja2 templates (deterministic)
    ↓
 34 files: FastAPI + MongoDB/PostgreSQL + Tailwind UI
    ↓
 docker compose up --build → http://localhost:8000/ux
```

## Try It

```bash
# Install
cd appspec && pip install -e ".[all]"
pip install mdb-engine fastapi uvicorn python-dotenv

# Set your Gemini key
echo "GEMINI_API_KEY=your-key-here" > .env

# Launch the web demo (requires MongoDB — see below)
python demo.py
```

The demo persists every generated AppSpec to MongoDB via [mdb-engine](https://pypi.org/project/mdb-engine/). By default it connects to `mongodb://localhost:27017` — start a local instance with Docker if you don't have one:

```bash
docker run -d --name mongodb -p 27017:27017 mongodb/mongodb-atlas-local:latest
```

Or point to Atlas: `export MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/"`

Open **http://localhost:8000** — describe your app, pick a stack and database, click **Generate**, then download the `.zip`.

Or use the CLI directly:

```bash
appspec create "A recipe sharing app with users, recipes, and reviews"
cd recipe-share/python-fastapi
docker compose up --build
```

Then open:
- **http://localhost:8000** — API info
- **http://localhost:8000/ux** — Tailwind CRUD UI with seeded data
- **http://localhost:8000/docs** — Swagger interactive docs
- **http://localhost:8000/health** — Health check + DB status

## MongoDB + PostgreSQL

AppSpec supports two production-grade database engines. Set the `database.engine` field in the spec and the entire generated stack adapts:

| Engine | Python Backend | DB Init Scripts | Docker Service |
|--------|---------------|-----------------|----------------|
| `mongodb` (default) | FastAPI + PyMongo (async) | `mongo-init/` (JS) | `mongo:8` |
| `postgresql` | FastAPI + SQLAlchemy + asyncpg | `sql-init/` (SQL) | `postgres:17` |

The spec itself is identical across engines — same entities, fields, endpoints, auth. Only the generated code changes. Switch engines with one line:

```json
{ "database": { "engine": "postgresql" } }
```

## What Gets Generated

**MongoDB mode** (default):
```
<app-slug>/
├── appspec/                    # The spec itself + rendered Markdown docs
│   ├── appspec.json
│   └── specs/{data-model,api,features}/spec.md
├── python-fastapi/             # Python backend (docker compose up)
│   ├── main.py, routes.py, models.py, database.py
│   ├── Dockerfile, docker-compose.yml
│   ├── mongo-init/             # Setup, validation, indexes, seed data
│   └── static/index.html       # Tailwind UI served at /ux
├── typescript-express/         # TypeScript backend (docker compose up)
│   ├── server.ts, routes.ts, models.ts
│   ├── Dockerfile, tsconfig.json, docker-compose.yml
│   ├── mongo-init/
│   └── static/index.html
├── mongodb-artifacts/          # Standalone MongoDB scripts
│   ├── indexes.js, validation.json, seed.js
│   └── mongo-init/
└── tailwind-ui/                # Standalone UI (open in browser)
    └── index.html
```

**PostgreSQL mode**:
```
<app-slug>/
├── appspec/
├── python-fastapi/             # SQLAlchemy + asyncpg backend
│   ├── main.py, routes.py, models.py, database.py
│   ├── Dockerfile, docker-compose.yml (PostgreSQL 17)
│   ├── sql-init/               # Schema, indexes, seed SQL
│   └── static/index.html
├── sql-artifacts/              # Standalone SQL scripts
│   ├── schema.sql, indexes.sql, seed.sql
│   └── sql-init/
└── tailwind-ui/
    └── index.html
```

## How It Works

AppSpec separates AI code generation into layers that each do one thing well:

| Layer | Who | What |
|-------|-----|------|
| **Prompt** | You | One sentence describing the app |
| **Schema** | Gemini | Structured JSON: entities, fields, endpoints, auth, database engine |
| **Validation** | Pydantic | Type checking, cross-reference verification, engine compatibility, safety audit |
| **Seed Data** | Gemini | 5 realistic records per table/collection (parallel call) |
| **Adapter** | `db.py` | Translates field types, IDs, docker config per engine |
| **Code** | Jinja2 | Deterministic templates — same spec in, same code out |
| **DB Init** | Init scripts | MongoDB JS or PostgreSQL SQL — auto-seeded on `docker compose up` |

The LLM touches two things: the schema and the seed data. Everything else is deterministic. If the LLM produces a bad spec, Pydantic catches it and retries.

## The AppSpec Document

An AppSpec is a JSON document that describes *what* an application is — not *how* to build it:

```json
{
  "schema_version": "1.0",
  "app_name": "Pet Clinic",
  "slug": "pet-clinic",
  "description": "Veterinary clinic management",
  "database": { "engine": "mongodb" },
  "auth": { "enabled": true, "strategy": "jwt", "roles": ["vet", "admin"] },
  "entities": [
    {
      "name": "Patient",
      "collection": "patients",
      "fields": [
        { "name": "name", "type": "string", "required": true },
        { "name": "species", "type": "enum", "enum_values": ["dog", "cat", "bird"] },
        { "name": "owner_id", "type": "reference", "reference": "owners" }
      ]
    }
  ],
  "endpoints": [
    { "method": "GET", "path": "/patients", "entity": "Patient", "operation": "list" }
  ],
  "sample_data": {
    "patients": [
      { "name": "Buddy", "species": "dog", "owner_id": "owner_1" }
    ]
  }
}
```

## Code Generation Targets

| Target | Stack | Engine |
|--------|-------|--------|
| `python-fastapi` | Python + FastAPI + PyMongo/SQLAlchemy | MongoDB or PostgreSQL |
| `typescript-express` | TypeScript + Express + Mongoose | MongoDB |
| `mongodb-artifacts` | MongoDB-native JS scripts | MongoDB |
| `sql-artifacts` | PostgreSQL SQL scripts | PostgreSQL |
| `tailwind-ui` | Tailwind CSS + vanilla JS | Any (REST API) |

Targets that don't support the spec's engine are automatically skipped during generation.

## CLI

```bash
appspec init                    # Scaffold a new spec
appspec validate                # Check your spec
appspec render                  # Generate Markdown docs
appspec generate --target python-fastapi -o ./output
appspec targets                 # List all targets
appspec create "..."            # Full LLM pipeline (like demo.py)
```

## MongoDB

Every MongoDB-engine app includes production-ready setup:

- **`00-setup.js`** — Creates collections (idempotent)
- **`01-validation.js`** — Applies `$jsonSchema` rules (try/catch, warn mode)
- **`02-indexes.js`** — Creates indexes: unique, filterable, sortable, reference, compound (try/catch, deduped)
- **`03-seed.js`** — Inserts LLM-generated realistic demo data (try/catch)

## PostgreSQL

Every PostgreSQL-engine app includes:

- **`00-schema.sql`** — CREATE TABLE with UUID primary keys, foreign keys, constraints, updated_at triggers
- **`01-indexes.sql`** — CREATE INDEX for filterable, sortable, unique, and reference fields
- **`02-seed.sql`** — INSERT statements from LLM-generated seed data

All SQL uses `IF NOT EXISTS` / `IF EXISTS` for idempotent re-runs.

## Project Structure

```
app-spec/
├── demo.py                      # The magic: prompt → LLM → app
├── docs/                        # Architecture, migration, plugin authoring
└── appspec/                     # The Python package
    ├── src/appspec/
    │   ├── models.py            # The AppSpec document model (Pydantic)
    │   ├── validation/          # Spec validation (schema, quality, safety)
    │   ├── engines/             # Database adapters (MongoDB, PostgreSQL)
    │   ├── generation/          # Code generation (registry, composer, targets/)
    │   ├── llm/                 # LLM-powered spec generation
    │   ├── store/               # MongoDB persistence
    │   ├── cli/                 # Click CLI (thin command handlers)
    │   ├── compiler.py          # Spec folder serialization
    │   └── scaffold.py          # Project scaffolding
    └── tests/                   # 191 tests (unit / integration / contract)
```

See [docs/architecture.md](docs/architecture.md) for detailed module boundaries and design rules.

## Why JSON Documents?

Read the full thesis: **[From Vibe Coding to Verified Code](BLOG.md)** — why the JSON document model is the right shape for AI code generation, and how AppSpec bridges the gap between fast-but-untrustable vibe coding and slow-but-reliable traditional engineering.

## License

MIT
