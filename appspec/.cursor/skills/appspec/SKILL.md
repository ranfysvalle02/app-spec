---
name: appspec
description: Guide for working with AppSpec — the Document Model for AI Code Generation. Use when reading, writing, or evolving application specifications, generating code from specs, creating change proposals, or working with appspec.json files.
---

# AppSpec Agent Guide

## 1. What is AppSpec

AppSpec is a spec-driven development framework. Application specifications are **JSON documents** with a Pydantic V2 schema. Deterministic Jinja2 templates generate code from these documents. Humans review the spec as rendered Markdown.

**Core principle:** AI produces the *spec* (structured JSON). Templates produce the *code* (deterministic). Humans review the *spec* (Markdown). Never generate code directly — always go through the spec.

---

## 2. Folder Structure

Every AppSpec project has this layout:

```
myproject/
  appspec/
    appspec.json             # Source of truth — the full AppSpec document
    specs/                   # Human-readable Markdown (rendered from JSON)
      data-model/
        spec.md              # Entities, fields, relationships, indexes
      api/
        spec.md              # Endpoints, auth, filters, sorting
      features/
        spec.md              # Features, UI, custom pages
    changes/                 # Change proposals
      <change-id>/
        proposal.md          # What and why
        design.md            # Technical decisions
        tasks.md             # Implementation breakdown
        spec-delta.json      # Structured diff to appspec.json
```

---

## 3. Reading Specs

When you need context about a project:

1. **Read `appspec/appspec.json`** for the full structured spec — entities, endpoints, auth config, UI, sample data.
2. **Read `appspec/specs/data-model/spec.md`** for a human-readable view of the data model.
3. **Read `appspec/specs/api/spec.md`** for endpoint documentation.
4. **Read `appspec/specs/features/spec.md`** for feature and UI documentation.

The JSON is the source of truth. The Markdown is a rendered view.

---

## 4. Writing / Editing Specs

When asked to design a feature or modify the application:

1. **Edit `appspec/appspec.json`** — this is where all changes go.
2. **Run `appspec validate`** to check for errors.
3. **Run `appspec render`** to regenerate the Markdown specs.

### Adding an Entity

Add to the `entities` array in `appspec.json`:

```json
{
  "name": "Appointment",
  "collection": "appointments",
  "description": "A scheduled appointment between a patient and a vet",
  "fields": [
    {"name": "patient_id", "type": "reference", "reference": "patients", "required": true},
    {"name": "scheduled_at", "type": "datetime", "required": true, "is_sortable": true},
    {"name": "status", "type": "enum", "enum_values": ["scheduled", "completed", "cancelled"], "is_filterable": true},
    {"name": "notes", "type": "text", "required": false}
  ],
  "relationships": ["Patient"]
}
```

### Adding Endpoints

Add to the `endpoints` array:

```json
{"method": "GET", "path": "/appointments", "entity": "Appointment", "operation": "list", "filters": ["status"], "sort_fields": ["scheduled_at"]},
{"method": "POST", "path": "/appointments", "entity": "Appointment", "operation": "create", "auth_required": true}
```

---

## 5. Change Proposals

For significant changes, create a change proposal:

```bash
appspec change new add-vector-search
```

This creates `appspec/changes/add-vector-search/` with:
- `proposal.md` — describe the change and its motivation
- `design.md` — technical decisions
- `tasks.md` — implementation breakdown
- `spec-delta.json` — the structured diff to `appspec.json`

Fill in the proposal files, then apply when approved.

---

## 6. Code Generation

Generate code from the validated spec:

```bash
appspec generate --target python-fastapi --output generated/
appspec generate --target typescript-express --output generated/
appspec generate --target mongodb-artifacts --output generated/
```

**Never hand-edit generated files.** Change the spec and regenerate.

---

## 7. Key Schema Rules

- **Entity names** must be PascalCase (e.g., `Patient`, `Appointment`)
- **Collection names** must be snake_case (e.g., `patients`, `appointments`)
- **Slugs** must be kebab-case (e.g., `vet-clinic`)
- **Enum fields** require `enum_values` list
- **Reference fields** require `reference` pointing to a valid collection name
- **Vector fields** require `vector_dimensions` > 0
- **Time-series entities** require `time_field`
- All cross-references are validated (entity relationships, field references, endpoint entities)

---

## 8. CLI Reference

```bash
appspec init [--name "App Name"]     # Scaffold new appspec/ folder
appspec validate                      # Check spec for errors
appspec render                        # JSON -> Markdown
appspec show [--json | --md]          # Display current spec
appspec generate --target <name>      # Deterministic code generation
appspec targets                       # List available targets
appspec change new <id>               # Create change proposal
appspec change diff <id>              # Show spec delta
appspec push --uri <mongo_uri>        # Persist to MongoDB
```

---

## 9. Rules

- **DO** edit `appspec.json` as the source of truth, then run `appspec render`.
- **DO** validate after every change: `appspec validate`.
- **DO** use change proposals for non-trivial modifications.
- **DO** produce structured JSON when designing features — not freeform code.
- **DO NOT** hand-edit generated code. Change the spec and regenerate.
- **DO NOT** put secrets, API keys, or connection strings in the spec.
- **DO NOT** skip validation before committing.
- **DO NOT** use `eval()`, `exec()`, or dangerous patterns in sample data or metadata.
