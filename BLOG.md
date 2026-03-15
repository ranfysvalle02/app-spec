# From Vibe Coding to Verified Code

**Why the JSON document model is the right shape for AI code generation — and how it bridges the gap between moving fast and shipping safe.**

---

## The Vibe Coding Moment

Something remarkable happened in 2024. Developers discovered they could describe an application in plain English, press Tab, and watch an AI agent write the entire thing. Cursor, Claude Code, GitHub Copilot, Windsurf — the tools multiplied. The community gave it a name: **vibe coding**.

Vibe coding is intoxicating. You describe a veterinary clinic app in one sentence. Thirty seconds later you have routes, models, a database schema, and a UI. It *feels* like the future.

Then you look at the code.

The authentication middleware is missing. The database queries are vulnerable to injection. The ORM models don't match the schema. The API returns 500 errors on edge cases the LLM didn't think about. You ask the agent to fix it, and it produces a different implementation — different libraries, different patterns, different bugs.

You've moved fast. But you've built on sand.

This is not a hypothetical. Every engineering leader who has evaluated AI code generation for production use has hit the same wall: **the output is non-deterministic, unauditable, and unreproducible**. Ask a model to build the same feature twice and you get two different implementations. You cannot audit what you cannot reproduce. You cannot trust what you cannot audit.

Enterprise adoption of AI code generation is stalled — not because the models aren't capable, but because the *output format* is wrong.

---

## Why Code Is the Wrong Output

When you ask an LLM to write code from a prompt, the model is simultaneously making two fundamentally different decisions:

1. **What to build** — the entities, relationships, business rules, API surface, authentication policy
2. **How to build it** — the framework, the library versions, the design patterns, the error handling strategy

These are different concerns with different owners. The *what* is a product decision. The *how* is an engineering decision. Conflating them in a single LLM output means neither is done well.

Worse, code is **unstructured output**. A Python file is a string. You can't validate it against a schema until you run it. You can't diff the *intent* — only the implementation. When the LLM changes one field name, the diff touches twelve files. The reviewer has to reconstruct the intent from scattered code changes.

This is the fundamental problem: **code is a terrible serialization format for application intent**.

---

## The Document Model Insight

Somewhere between JSON's first curly brace and AI's first structured output, a quiet inevitability took root.

In 2007, MongoDB introduced an idea that reshaped how applications store data: the **document model**. Instead of forcing application data into rigid relational tables with fixed schemas, let data be stored as flexible, self-describing JSON documents. The principle was simple: *data that is accessed together should be stored together.* Documents are structured enough to validate but flexible enough to model any domain.

That insight has a second act.

Instead of asking an LLM to produce *code* — unstructured, non-deterministic, unauditable — ask it to produce a **document**: a structured JSON specification that describes *what* the application is. Not how to build it. What it is.

```
Traditional:  Prompt → LLM → Code (non-deterministic, unauditable)

Document:     Prompt → LLM → JSON Spec → Validate → Templates → Code
                                 ↑              ↑            ↑
                            structured    Pydantic     deterministic
```

The LLM's job shrinks from "write an application" to "fill in a structured document." The document is validated instantly. If the LLM hallucinates a field type or invents an entity that doesn't exist, validation catches it before a single line of code is generated.

Then deterministic templates consume the validated document and produce source code. Same document in, same code out. Every time.

The *what* and the *how* are finally separated. The LLM handles the what. Templates handle the how. **Humans review the what. Machines enforce the how.**

---

## JSON: The Universal Intermediate Representation

Why JSON specifically? Because when LLMs graduated to structured outputs, the format the industry converged on was `response_format: json`. Not SQL. Not rows and foreign keys. Not protobuf. Nested, flexible, self-describing documents — the shape MongoDB has spoken natively since 2007.

JSON sits at the intersection of five critical properties that no other format shares:

**1. LLMs speak JSON natively.**
Every major model supports `response_format: { type: "json_object" }`. Structured output isn't a hack — it's a first-class capability. When you ask an LLM to produce JSON conforming to a schema, the output is dramatically more reliable than freeform code generation. The model is filling in a form, not writing a novel.

**2. Pydantic validates JSON instantly.**
A Pydantic V2 model defines the exact shape of a valid application spec — every field typed, every constraint explicit, every cross-reference verified. Validation takes milliseconds, not minutes. If the LLM produces an invalid spec, you retry with the validation errors as feedback. The loop is fast and self-correcting.

**3. MongoDB stores JSON natively.**
A JSON application spec maps 1:1 to a BSON document in MongoDB. No ORM. No translation layer. No impedance mismatch. Store it, query it, aggregate across it, search it semantically. The spec isn't just a file in a repo — it's a queryable record in an organizational knowledge base.

**4. Git diffs JSON cleanly.**
A JSON document diffs line-by-line. When a developer adds a field to an entity, the diff shows exactly one added object in the `fields` array. Compare this to a code diff where adding a field touches the model, the route, the validation, the migration, and the UI template. The spec diff is the *intent*. The code diff is the *consequence*.

**5. Markdown renders from JSON trivially.**
Jinja2 templates convert a JSON spec into human-readable Markdown in milliseconds. Reviewers don't read JSON — they read tables, bullet points, and section headers that describe the application's entities, endpoints, and auth policy. The Markdown is generated, not authored. It's always in sync with the spec.

No other format sits at the intersection of all five. JSON is the universal intermediate representation for AI-generated application architecture.

---

## The AppSpec Architecture

AppSpec is a working implementation of this idea. Here's what it does — and more importantly, what it *doesn't* let the LLM do.

### Layer 1: The Document

An AppSpec document is a JSON object with a defined schema:

```json
{
  "schema_version": "1.0",
  "app_name": "Veterinary Clinic",
  "slug": "vet-clinic",
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
  ]
}
```

This document describes *what* the application is. Not which framework to use. Not which ORM. Not which CSS library. What it is: its entities, their relationships, its API surface, its authentication policy.

### Layer 2: Validation

A Pydantic V2 schema enforces the document's structure before any code is generated:

- Entity names must be PascalCase. Collection names must be snake_case.
- Reference fields must point to collections that exist in the spec.
- Enum fields must include their allowed values.
- Endpoints must reference entities that exist.
- A safety audit scans for hardcoded secrets and dangerous patterns.
- Engine compatibility checks warn about features that don't translate cleanly (e.g., embedded documents in PostgreSQL).

If the LLM produces a spec that fails validation, the errors are fed back as a retry prompt. The LLM corrects its output. The loop typically converges in one or two retries.

### Layer 3: Deterministic Code Generation

Given a validated spec, Jinja2 templates produce source code. Templates are organized as **targets** — pluggable code generation backends:

| Target | What It Produces |
|--------|-----------------|
| `python-fastapi` | Full Python backend: FastAPI + PyMongo async (MongoDB) or SQLAlchemy (PostgreSQL) |
| `typescript-express` | Full TypeScript backend: Express + Mongoose |
| `mongodb-artifacts` | MongoDB-native scripts: indexes, validation, seed data |
| `sql-artifacts` | PostgreSQL scripts: schema, indexes, seed SQL |
| `tailwind-ui` | Tailwind CSS CRUD interface (backend-agnostic) |

The key property: **templates are deterministic**. Delete all generated code, re-run `appspec generate`, get identical output. The spec is the source of truth. The code is a function of the spec.

Templates also enforce security patterns by construction. Parameterized queries, CSRF protection, input validation — the template guarantees these. The LLM cannot opt out of security middleware because it never touches the code.

---

## Bridging the Gap

There are two failure modes in software engineering today:

**Vibe coding** is fast but untrustable. You move at the speed of thought, but the output is non-deterministic, unauditable, and fragile. It works for prototypes. It fails for production.

**Traditional engineering** is trustable but slow. Code reviews, architecture documents, migration plans, test suites — every safeguard adds time. The feedback loop stretches from hours to days to weeks.

AppSpec is the bridge.

The spec is a **contract** between human intent and machine output. It's fast to produce (one LLM call), fast to review (Markdown tables, not 800-line diffs), and fast to generate code from (deterministic templates, not another LLM call).

The workflow:

1. A developer describes what they want in plain English.
2. The LLM produces a structured JSON spec.
3. Pydantic validates it instantly.
4. The developer reviews it as rendered Markdown — readable in minutes.
5. Deterministic templates produce the code.
6. The spec and code are committed together. The spec is the source of truth.

For teams, the workflow adds a review step: change proposals include a `spec-delta.json` showing exactly what changes. The team reviews the *spec*, not the code. On approval, templates regenerate the code deterministically.

This is not vibe coding. And it's not traditional engineering. It's a third thing: **verified AI-assisted development**. The AI handles the tedious translation from intent to structure. Humans handle the judgment calls. Templates handle the implementation. Everyone does what they're best at.

---

## The MongoDB Advantage: Specs as Queryable Documents

Here's where the document model metaphor becomes literal infrastructure.

An AppSpec document is JSON. MongoDB stores JSON (BSON). The mapping is native — no ORM, no translation layer, no impedance mismatch. But native storage is just the floor. What matters is what you can *do* with the documents once they're there.

### Every Spec, Preserved

Every version of every spec is upserted into an `app_specs` collection, versioned by slug and timestamp. Nothing is lost. You can reconstruct any service's architecture at any point in time.

### Queryable Architecture

MongoDB's aggregation framework turns your spec collection into an organizational intelligence layer:

```javascript
// Which services have auth disabled on write endpoints?
db.app_specs.aggregate([
  { $unwind: "$endpoints" },
  { $match: {
    "endpoints.method": { $in: ["POST", "PUT", "DELETE"] },
    "endpoints.auth_required": false
  }},
  { $group: { _id: "$slug", open_writes: { $sum: 1 } } }
])
```

This query runs against your live spec collection. No ETL pipeline. No data warehouse. The specs *are* the data. The rest of the industry would tell you to export the specs, transform them, load them into an analytics platform, then query. MongoDB developers just write a query.

### Semantic Search Across Specs

With Atlas Vector Search, you can query specs by meaning — not just by field name. When an AI agent is asked to build a new service, it retrieves semantically similar past specs, pulling in institutional knowledge automatically. This is RAG at the architecture level: the agent learns from every spec the organization has ever produced.

A coordinate is an array. A graph edge is a reference. An embedding is an array of floats. Every one of these is native JSON. The same principle that made MongoDB the right database for operational data in 2009 makes it the right database for AI agent memory in 2026.

### The Audit Trail

Every spec mutation — creation, field addition, endpoint change, auth policy update — is a document event. And the document model is uniquely suited to audit trails:

- **Events are polymorphic.** A "field added" event has different data than an "auth policy changed" event. Documents handle this natively — no nullable columns, no EAV anti-patterns.
- **Before/after snapshots are embedded.** Each event contains the relevant state before and after the change. Reconstructing history is a single document read, not a join across normalized tables.
- **Aggregation pipelines** answer governance questions directly: "Who changed auth settings in the last 30 days?" "Which specs had LLM-generated changes that produced validation warnings?"

The audit trail answers the question every enterprise security team asks about AI code generation: **"What did the AI change, and did a human approve it?"**

Every LLM-generated change is tagged with the model used, the prompt that triggered it, and the validation result. Full traceability from human intent to generated code, with the spec as the auditable intermediate artifact.

---

## The Unbroken Thread

The document model didn't need to bend to fit AI code generation. AI code generation simply arrived in a shape the document already understood.

A spec is a JSON document. An entity is a nested object. A relationship is a reference. A validation rule is a field constraint. An API endpoint is a typed entry. Every pattern that makes an application specification useful was already native to JSON — natively supported by the document model in a way that rows and columns can never claim.

Vibe coding showed us the speed. Traditional engineering showed us the safety. The document model shows us how to have both.

- **AI produces documents** — structured, validatable, storable
- **Humans review documents** — rendered as Markdown, diffable in Git
- **Templates produce code** — deterministic, reproducible, safe
- **MongoDB stores documents** — queryable, searchable, auditable

The spec is the source of truth. The code is a deterministic function of the spec. The spec lives in MongoDB alongside every other spec in the organization — searchable, queryable, and auditable.

This is how AI code generation becomes enterprise-safe: not by making models smarter, but by giving them the right data model.

Data that is accessed together should be stored together. That was the right call for a user profile in 2009. It is the right call for an application specification in 2026.

---

## Try It

```bash
pip install appspec
appspec create "A veterinary clinic app with owners, patients, and appointments"
cd vet-clinic/python-fastapi
docker compose up --build
```

One sentence in. Full-stack app out. Validated, deterministic, auditable.

[GitHub](https://github.com/ranfysvalle02/app-spec) | [PROPOSAL.md](appspec/PROPOSAL.md) | MIT License
