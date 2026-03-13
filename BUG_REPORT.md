# Bug Report: Missing `await` on `validate_manifest()` in `fastapi_app.py`

**Package:** `mdb-engine`
**Version:** `0.8.1`
**Severity:** Critical (application fails to start)
**File:** `mdb_engine/core/fastapi_app.py`, line 162

## Summary

The `lifespan` function in `MDBFastAPIApp` calls `engine.validate_manifest(pre_manifest)` without `await`, even though `validate_manifest` is an `async def` method. This causes a `TypeError` on startup, making it impossible to use inline manifests (the `manifest=` parameter of `create_app`).

## Root Cause

```python
# fastapi_app.py:162 (CURRENT — broken)
is_valid, error_msg, _ = engine.validate_manifest(pre_manifest)
```

`validate_manifest` is defined as `async def` in both:
- `mdb_engine/core/app_lifecycle.py:40`
- `mdb_engine/core/app_registration.py:64`

Calling it without `await` returns a coroutine object. Python then tries to unpack that coroutine as a 3-tuple, which fails immediately.

## Fix

```python
# fastapi_app.py:162 (FIXED)
is_valid, error_msg, _ = await engine.validate_manifest(pre_manifest)
```

One character change: add `await`.

## Reproduction

```python
from mdb_engine import MongoDBEngine

engine = MongoDBEngine(
    mongo_uri="mongodb://localhost:27017",
    db_name="test_db",
)

app = engine.create_app(
    slug="test_app",
    manifest={
        "schema_version": "2.0",
        "slug": "test_app",
        "name": "Test App",
    },
)

# Run with: uvicorn or python script.py
# Result: Application startup fails with TypeError
```

## Full Traceback

```
RuntimeWarning: coroutine 'AppLifecycleMixin.validate_manifest' was never awaited
  is_valid, error_msg, _ = engine.validate_manifest(pre_manifest)

ERROR:    Traceback (most recent call last):
  File ".../starlette/routing.py", line 694, in lifespan
    async with self.lifespan_context(app) as maybe_state:
  File ".../contextlib.py", line 210, in __aenter__
    return await anext(self.gen)
  File ".../fastapi/routing.py", line 134, in merged_lifespan
    async with original_context(app) as maybe_original_state:
  File ".../contextlib.py", line 210, in __aenter__
    return await anext(self.gen)
  File ".../mdb_engine/core/fastapi_app.py", line 162, in lifespan
    is_valid, error_msg, _ = engine.validate_manifest(pre_manifest)
TypeError: cannot unpack non-iterable coroutine object

ERROR:    Application startup failed. Exiting.
```

## Environment

- Python 3.11.13
- mdb-engine 0.8.1
- FastAPI (latest)
- macOS (darwin 25.3.0)

## Workaround

Until a fix is released, patch the installed file directly:

```bash
# Find the file
python -c "import mdb_engine; print(mdb_engine.__file__)"

# Edit mdb_engine/core/fastapi_app.py line 162:
# Change:  is_valid, error_msg, _ = engine.validate_manifest(pre_manifest)
# To:      is_valid, error_msg, _ = await engine.validate_manifest(pre_manifest)
```

## Notes

- The `manifest_path` code path on line 159 correctly uses `await engine.load_manifest(...)`, so this is clearly an oversight on the inline-manifest branch.
- The `lifespan` function is already `async`, so adding `await` is safe and correct.
