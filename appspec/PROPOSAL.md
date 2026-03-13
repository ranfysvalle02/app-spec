# AppSpec: The Document Model for AI Code Generation

## From Mind to Machine — Safely

Every engineering leader who has deployed AI coding agents has experienced the same frustration: **AI can write code at the speed of light, but it often writes the *wrong* code.** The models are capable. The problem is **underspecification** — they are guessing your architecture, your edge cases, and your business logic from a two-sentence chat prompt.

This is not a model problem. It is a systems problem. And the solution already exists: **the Document Model**.

---

## The Trust Problem

Enterprise adoption of AI code generation is stalled by three fundamental issues:

### 1. Non-Deterministic Output

Ask an LLM to build a user authentication system twice. You will get two different implementations — different libraries, different patterns, different security postures. You cannot audit what you cannot reproduce.

### 2. Hallucinated Patterns

LLMs invent libraries that do not exist, skip security middleware they were not told about, and produce code that "looks right" but violates architectural invariants. A human must review every line, which negates the speed advantage.

### 3. No Separation of Concerns

When an LLM writes code from a prompt, it simultaneously decides *what* to build (the specification) and *how* to build it (the implementation). These are fundamentally different concerns that should be handled by different systems with different guarantees.

---

## The Insight: Documents, Not Code

The solution comes from an unlikely place: database design.

In 2007, MongoDB introduced the Document Model — the idea that application data should be stored as flexible, self-describing JSON documents rather than rigid relational tables. Documents are structured enough to validate but flexible enough to model any domain. This insight powered MongoDB to become the most popular modern database.

**AppSpec applies the same insight to code generation.**

Instead of asking an LLM to produce *code* (unstructured, non-deterministic, unauditable), we ask it to produce a *document* — a structured JSON specification that describes what the application is. This document is then consumed by deterministic templates that produce identical code every time.

```
Traditional:  Prompt → LLM → Code (non-deterministic, unauditable)

AppSpec:      Prompt → LLM → Document (JSON) → Validate → Templates → Code (deterministic, auditable)
```

---

## The Three Pillars

### Pillar 1: The Document Model

An AppSpec document is a JSON object with a defined schema that describes *what* an application is — its entities, relationships, endpoints, authentication, and UI — without prescribing *how* to build it.

```json
{
  "schema_version": "1.0",
  "app_name": "Veterinary Clinic",
  "slug": "vet-clinic",
  "entities": [
    {
      "name": "Patient",
      "collection": "patients",
      "fields": [
        {"name": "name", "type": "string", "required": true},
        {"name": "species", "type": "enum", "enum_values": ["dog", "cat", "bird"]},
        {"name": "owner_id", "type": "reference", "reference": "owners"},
        {"name": "weight_kg", "type": "float", "min_value": 0}
      ]
    }
  ]
}
```

The document is:
- **Validatable** — A Pydantic V2 schema enforces types, constraints, and cross-references before any code is generated.
- **Storable** — It maps 1:1 to JSON (and optionally BSON). No ORM translation, no schema migration.
- **Versionable** — A `schema_version` field enables forward migration as the spec evolves.
- **Language-agnostic** — It describes the application domain, not the implementation language.
- **Database-agnostic** — A `database.engine` field selects MongoDB or PostgreSQL. The same spec drives code generation for any supported engine.

### Pillar 2: JSON Response

Modern LLMs support structured output via `response_format`, tool calling, and function schemas. Instead of asking the LLM to write Python or TypeScript, we ask it to fill in a JSON document that conforms to the AppSpec schema.

Every field is typed. Every constraint is explicit. The output can be validated instantly — before a single line of code is generated. If the LLM hallucinates a field type or invents an entity that does not exist, validation catches it.

This is the same pattern that makes MongoDB's document validation powerful: define the shape of your data, then enforce it.

### Pillar 3: Deterministic Code Generation

Given a validated AppSpec document, Jinja2 templates produce source code. The templates are deterministic: same document in, same code out. Every time.

Templates are organized as **targets** — pluggable code generation backends. A **database adapter** layer (`db.py`) translates field types, ID strategies, and infrastructure per engine:

| Target | Stack | Engine |
|--------|-------|--------|
| `python-fastapi` | Python + FastAPI + PyMongo or SQLAlchemy | MongoDB, PostgreSQL |
| `typescript-express` | TypeScript + Express + Mongoose | MongoDB |
| `mongodb-artifacts` | MongoDB-native JS scripts | MongoDB |
| `sql-artifacts` | PostgreSQL SQL scripts | PostgreSQL |
| `tailwind-ui` | Tailwind CSS + vanilla JS | Any |

Adding a new target (Go, Rust, Java) or a new database engine means writing templates or implementing the `DatabaseAdapter` interface — not modifying the core.

Key properties:
- **Reproducible** — Delete all generated code, re-run `appspec generate`, get identical output.
- **Auditable** — Diff the spec to understand code changes. No more reading 800-line PRs.
- **Safe** — Templates enforce security patterns by construction. CSRF protection, parameterized queries, no `eval()`. The template guarantees it — the LLM cannot opt out.

---

## The Workflow

### For an Individual Developer

1. Describe your app in a prompt or write a spec by hand.
2. The LLM produces an AppSpec document (structured JSON).
3. `appspec validate` checks the document against the schema.
4. `appspec render` produces human-readable Markdown for review.
5. `appspec generate --target python-fastapi` produces code.
6. Commit the spec and generated code together. The spec is the source of truth.

### For a Team

1. A developer creates a change proposal in `appspec/changes/`.
2. The proposal includes a `spec-delta.json` showing exactly what changes.
3. The team reviews the *spec*, not the code. Markdown is readable in minutes.
4. On approval, `appspec change apply` merges the delta into `appspec.json`.
5. `appspec generate` produces the updated code deterministically.
6. CI verifies that the generated code matches the spec (no hand-edits).

### For an Enterprise

1. All AppSpec documents are persisted to MongoDB Atlas.
2. A governance dashboard queries specs across all services: "Which services allow unauthenticated write endpoints?"
3. Atlas Vector Search enables spec-level RAG: when an agent designs a new payment service, it retrieves every past payment spec in the organization.
4. Aggregation pipelines track velocity: entities added per sprint, endpoints per service, auth coverage.

---

## The MongoDB Connection

AppSpec documents are JSON. MongoDB stores JSON (BSON). The mapping is native — no ORM, no translation layer.

### Storage

```bash
appspec push --uri "mongodb+srv://cluster.mongodb.net/specs"
```

The compiled `appspec.json` is upserted into an `app_specs` collection, versioned by slug and timestamp. Every spec ever written is preserved.

### Search

```bash
appspec search --uri "mongodb+srv://..." "real-time sensor data with time-series"
```

Full-text search across all specs in the organization. Find prior art instantly.

### RAG (Retrieval-Augmented Generation)

Store vector embeddings of spec descriptions and entity definitions in MongoDB Atlas. When an agent is asked to build a new service, it queries the spec store for semantically similar past specs — pulling in institutional knowledge automatically.

### Analytics

MongoDB aggregation pipelines enable organizational intelligence:
- How many entities does each service define?
- Which services have auth disabled on write endpoints?
- What is the average number of endpoints per entity across the org?
- How has spec complexity grown over time?

---

## AppSpec and OpenSpec: Complementary Approaches

[OpenSpec](https://openspec.dev) (27k+ GitHub stars, YC W25) popularized spec-driven development — the idea that AI coding agents should read a specification before writing code. AppSpec stands on this foundation and takes a complementary approach: where OpenSpec excels at human-readable planning in Markdown, AppSpec adds a machine-readable JSON layer that enables validation, code generation, and queryable storage.

| Dimension | OpenSpec | AppSpec |
|-----------|----------|---------|
| Core format | Markdown (freeform) | JSON Document (schema-validated) |
| Validation | Human review | Pydantic V2 schema enforcement |
| Code generation | None (delegates to agents) | Deterministic Jinja2 targets |
| Human layer | Markdown (primary format) | Markdown (rendered from JSON) |
| Machine layer | Markdown parsing | Native JSON / BSON |
| Storage | Git | Git + MongoDB |
| Search | File grep | Full-text + Atlas Vector Search |

OpenSpec's insight — that specs should persist across sessions and live in the repo — is correct and foundational. AppSpec builds on it by making the spec a structured document that machines can validate, store, query, and generate code from. Teams can use both: OpenSpec for high-level planning, AppSpec for the machine-validated contract that drives code generation.

---

## The Bottom Line

The Document Model solved the impedance mismatch between applications and databases. AppSpec solves the impedance mismatch between human intent and AI-generated code.

- **AI produces documents** (structured, validatable, storable)
- **Humans review documents** (rendered as Markdown, diffable in Git)
- **Templates produce code** (deterministic, reproducible, safe)

The spec is the source of truth. The code is a deterministic function of the spec. The spec lives in MongoDB alongside every other spec in the organization, searchable and queryable.

This is how AI code generation becomes enterprise-safe: not by making models smarter, but by giving them the right data model.

---

## Get Started

```bash
pip install appspec
appspec init
appspec validate
appspec generate --target python-fastapi
```

See the [README](README.md) for full documentation.
