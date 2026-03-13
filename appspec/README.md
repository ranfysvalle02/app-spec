# AppSpec

**The Document Model for AI Code Generation.**

AI produces structured JSON specs. Humans review Markdown. Deterministic templates generate code. Enterprise-safe by design.

## The Problem

AI code generation is fast but untrustworthy. LLMs produce non-deterministic output, hallucinate patterns, and conflate *what* to build with *how* to build it. Enterprises cannot adopt tools they cannot audit.

## The Solution

AppSpec separates AI code generation into three layers:

| Layer | Format | Who | Purpose |
|-------|--------|-----|---------|
| **Spec** | JSON | AI produces | Structured, schema-validated application description |
| **Review** | Markdown | Humans read | Readable, diffable, lives in Git |
| **Code** | Source files | Templates produce | Deterministic, reproducible, auditable |

```
Prompt → LLM → AppSpec (JSON) → Validate (Pydantic) → Review (Markdown) → Generate (Jinja2) → Code
```

Same spec in, same code out. Every time.

## Quick Start

```bash
pip install appspec

# Initialize a new spec in your project
appspec init

# Edit the spec
vim appspec/appspec.json

# Validate
appspec validate

# Render human-readable Markdown
appspec render

# Generate code
appspec generate --target python-fastapi
```

## The AppSpec Document

An AppSpec is a JSON document that describes *what* an application is — not *how* to build it:

```json
{
  "schema_version": "1.0",
  "app_name": "Pet Clinic",
  "slug": "pet-clinic",
  "description": "Veterinary clinic management with patients, owners, and appointments",
  "auth": {
    "enabled": true,
    "strategy": "jwt",
    "roles": ["vet", "receptionist", "admin"]
  },
  "entities": [
    {
      "name": "Patient",
      "collection": "patients",
      "fields": [
        {"name": "name", "type": "string", "required": true},
        {"name": "species", "type": "enum", "enum_values": ["dog", "cat", "bird", "reptile"]},
        {"name": "owner_id", "type": "reference", "reference": "owners"},
        {"name": "weight_kg", "type": "float", "min_value": 0}
      ]
    }
  ],
  "endpoints": [
    {"method": "GET", "path": "/patients", "entity": "Patient", "operation": "list"}
  ]
}
```

This document is:
- **Validatable** — Pydantic enforces types, constraints, and cross-references
- **Storable** — Maps 1:1 to a MongoDB document (BSON-native)
- **Versionable** — `schema_version` enables forward migration
- **Extensible** — `metadata` dict for domain-specific extensions
- **Language-agnostic** — Describes *what*, not *how*

## Code Generation Targets

AppSpec ships with pluggable code generation targets:

| Target | Stack | Engine |
|--------|-------|--------|
| `python-fastapi` | Python + FastAPI + PyMongo/SQLAlchemy | MongoDB, PostgreSQL |
| `typescript-express` | TypeScript + Express + Mongoose | MongoDB |
| `mongodb-artifacts` | MongoDB-native JS scripts | MongoDB |
| `sql-artifacts` | PostgreSQL SQL scripts | PostgreSQL |
| `tailwind-ui` | Tailwind CSS + vanilla JS | Any (REST API) |

```bash
appspec generate --target python-fastapi    # Python backend
appspec generate --target sql-artifacts     # PostgreSQL scripts
appspec generate --target mongodb-artifacts # MongoDB scripts
appspec targets                             # List all available targets
```

Targets are deterministic Jinja2 template packs. Targets that don't support the spec's engine are automatically skipped. Add your own by creating a target module.

## MongoDB Integration

AppSpec documents are JSON. MongoDB stores JSON. The mapping is native.

```bash
# Persist spec to MongoDB Atlas
appspec push --uri "mongodb+srv://..."

# Search across all specs in your org
appspec search --uri "mongodb+srv://..." "payment processing"
```

Store specs in MongoDB for:
- Cross-project querying and governance
- Atlas Vector Search for spec-level RAG
- Aggregation-based analytics and compliance auditing

## Agent Integration (SKILL.md)

AppSpec includes a SKILL.md that teaches AI coding agents (Cursor, Claude Code, Copilot) to:
- Read `appspec/appspec.json` for structured project context
- Produce structured JSON when designing features
- Create change proposals for review before implementation
- Generate code from validated specs

## Philosophy

> The Document Model + JSON Response + Deterministic Code Gen = Enterprise-Safe AI Code Generation.

See [PROPOSAL.md](PROPOSAL.md) for the full thesis.

## License

MIT
