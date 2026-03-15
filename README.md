# AppSpec

**AI for creativity. Templates for control.**

Today's vibe-coding tools let AI write code directly — fast, creative, and dangerously inconsistent. Two prompts for the same app produce different dependency versions, different auth patterns, different bugs. AppSpec rejects the premise. Instead of asking the LLM to write code, it asks the LLM to fill in a **structured JSON document** — entities, relationships, auth, endpoints. Then deterministic Jinja2 templates render the code. Same spec in, same code out. Every time.

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

The AI handles the *what*. Your templates handle the *how*. The spec is version-controlled, diffable, and human-reviewable. The code is derived.

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

AppSpec separates the two things every AI code generation tool conflates: deciding *what* to build and deciding *how* to build it.

| Layer | Who | What |
|-------|-----|------|
| **Prompt** | You | One sentence describing the app |
| **Schema** | Gemini | Structured JSON: entities, fields, endpoints, auth, database engine |
| **Validation** | Pydantic | Type checking, cross-reference verification, engine compatibility, safety audit |
| **Seed Data** | Gemini | 5 realistic records per table/collection (parallel call) |
| **Adapter** | `db.py` | Translates field types, IDs, docker config per engine |
| **Code** | Jinja2 | Deterministic templates — same spec in, same code out |
| **DB Init** | Init scripts | MongoDB JS or PostgreSQL SQL — auto-seeded on `docker compose up` |

The LLM touches two things: the schema and the seed data. Everything else is deterministic. If the LLM produces a bad spec, Pydantic catches it and retries. The LLM cannot opt out of security middleware because it never touches the code. Templates enforce parameterized queries, JWT auth, RBAC, and input validation by construction.

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

Targets that don't support the spec's engine are automatically skipped during generation. Adding a new stack is pluggable — write a Jinja2 template set and register it as a target.

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
    └── tests/                   # 230 tests (unit / integration / contract)
```

See [docs/architecture.md](docs/architecture.md) for detailed module boundaries and design rules.

## Why JSON Documents?

Read the full thesis: **[From Vibe Coding to Verified Code](BLOG.md)**

The short version: when LLMs graduated to structured outputs, the format the industry converged on was `response_format: json`. Not SQL. Not rows and foreign keys. Nested, flexible, self-describing documents — the shape MongoDB has spoken natively since 2007. JSON is the only format that sits at the intersection of LLM output, schema validation, document storage, clean diffs, and template rendering. The document model didn't need to bend to fit AI code generation. AI code generation simply arrived in a shape the document already understood.

## License

MIT
