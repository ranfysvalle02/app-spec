#!/usr/bin/env python3
"""
AppSpec Demo — A magical single-file web app.

    python demo.py
    python demo.py --port 9000
    python demo.py --model openai/gpt-4o

Environment variables (also loadable via .env):
    APPSPEC_MODEL    LLM model (default: gemini/gemini-2.5-flash)
    GEMINI_API_KEY   API key for Gemini models
    OPENAI_API_KEY   API key for OpenAI models
    ANTHROPIC_API_KEY API key for Anthropic models
    MONGODB_URI      MongoDB connection string (default: mongodb://localhost:27017)
    PORT             Server port (default: 8000)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import io
import json
import logging
import os
import secrets
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("appspec_demo")

if os.environ.get("APPSPEC_LOG_FORMAT", "").lower() == "json":
    from pythonjsonlogger import jsonlogger
    _json_handler = logging.StreamHandler()
    _json_handler.setFormatter(jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    ))
    logging.root.handlers.clear()
    logging.root.addHandler(_json_handler)
    logging.root.setLevel(logging.INFO)

try:
    import uvicorn
    from fastapi import Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, PlainTextResponse
    from starlette.concurrency import run_in_threadpool
except ImportError:
    raise SystemExit(
        "Demo requires fastapi + uvicorn.\n"
        "Install with:  pip install fastapi uvicorn python-dotenv"
    )

# ── Patch mdb-engine v0.8.1: missing await on validate_manifest() ────────────
# Must run BEFORE importing mdb_engine so Python loads the patched source.
# See BUG_REPORT.md. Remove once mdb-engine publishes a fix.
def _patch_mdb_engine():
    import importlib.util, pathlib, importlib.metadata
    try:
        _ver = importlib.metadata.version("mdb-engine")
    except importlib.metadata.PackageNotFoundError:
        return
    if not _ver.startswith("0.8"):
        raise RuntimeError(
            f"mdb-engine {_ver} detected — the monkey-patch targets 0.8.x. "
            "Remove the patch and re-test before upgrading."
        )
    _BROKEN = "is_valid, error_msg, _ = engine.validate_manifest(pre_manifest)"
    _FIXED  = "is_valid, error_msg, _ = await engine.validate_manifest(pre_manifest)"
    spec = importlib.util.find_spec("mdb_engine")
    if not spec or not spec.origin:
        return
    target = pathlib.Path(spec.origin).parent / "core" / "fastapi_app.py"
    if not target.exists():
        return
    src = target.read_text()
    if _FIXED in src or _BROKEN not in src:
        return
    target.write_text(src.replace(_BROKEN, _FIXED, 1))
    for pyc in target.parent.glob("__pycache__/fastapi_app*"):
        pyc.unlink(missing_ok=True)

try:
    _patch_mdb_engine()
except Exception:
    pass
del _patch_mdb_engine

try:
    from mdb_engine import MongoDBEngine
except ImportError:
    raise SystemExit(
        "Demo requires mdb-engine.\n"
        "Install with:  pip install mdb-engine"
    )

# ── CLI args ──────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="AppSpec Demo")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    p.add_argument("--model", type=str, default=os.environ.get("APPSPEC_MODEL", ""))
    p.add_argument("--host", type=str, default="0.0.0.0")
    return p.parse_args()

_cli = _parse_args() if "uvicorn" not in sys.argv[0] else argparse.Namespace(
    port=int(os.environ.get("PORT", 8000)),
    model=os.environ.get("APPSPEC_MODEL", ""),
    host="0.0.0.0",
)

if _cli.model:
    os.environ["APPSPEC_MODEL"] = _cli.model

APP_SLUG = "appspec_demo"

engine = MongoDBEngine(
    mongo_uri=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
    db_name=os.environ.get("MDB_DB_NAME", "appspec_demo"),
)

app = engine.create_app(
    slug=APP_SLUG,
    manifest={
        "schema_version": "2.0",
        "slug": APP_SLUG,
        "name": "AppSpec Demo",
        "managed_indexes": {
            "generations": [
                {"type": "regular", "keys": {"created_at": -1}, "name": "created_at_sort"},
                {"type": "regular", "keys": {"slug": 1, "created_at": -1}, "name": "slug_time_idx"},
                {"type": "regular", "keys": {"session_id": 1}, "name": "session_id_idx", "unique": True},
            ]
        },
    },
)

# ── Bounded session cache (LRU, max 50 entries) ─────────────────────────────

_SESSION_MAX = int(os.environ.get("APPSPEC_SESSION_MAX", "50"))

class _LRUCache(collections.OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            oldest = next(iter(self))
            log.debug("Session cache evicting %s", oldest)
            del self[oldest]

_sessions: _LRUCache = _LRUCache(_SESSION_MAX)

# ── Rate limiter (per-IP, sliding window) ────────────────────────────────────

_RATE_LIMIT = int(os.environ.get("APPSPEC_RATE_LIMIT", "10"))  # per minute
_RATE_WINDOW = 60
_rate_log: dict[str, list[float]] = {}


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    hits = _rate_log.get(ip, [])
    hits = [t for t in hits if now - t < _RATE_WINDOW]
    _rate_log[ip] = hits
    if len(hits) >= _RATE_LIMIT:
        return False
    hits.append(now)
    return True


# ── Concurrency cap & timeout ─────────────────────────────────────────────────

_MAX_CONCURRENT = int(os.environ.get("APPSPEC_MAX_CONCURRENT", "3"))
_gen_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
_GEN_TIMEOUT = int(os.environ.get("APPSPEC_TIMEOUT", "120"))

# ── API key auth (optional — open in demo mode when unset) ────────────────────

_API_KEY = os.environ.get("APPSPEC_API_KEY", "")


def _check_api_key(request: Request) -> JSONResponse | None:
    """Return a 401 response if API key is configured but not provided."""
    if not _API_KEY:
        return None
    provided = request.headers.get("x-api-key", "")
    if provided == _API_KEY:
        return None
    return JSONResponse({"error": "Invalid or missing API key"}, status_code=401)


# ── Security headers middleware ──────────────────────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware


_CSP_TEMPLATE = (
    "default-src 'self'; "
    "script-src 'nonce-{nonce}' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "connect-src 'self'"
)

_CSP_API = (
    "default-src 'none'; "
    "frame-ancestors 'none'"
)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        nonce = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Content-Security-Policy"] = _CSP_TEMPLATE.format(nonce=nonce)
        else:
            response.headers["Content-Security-Policy"] = _CSP_API
        return response


app.add_middleware(_SecurityHeadersMiddleware)


def _backfill_sample_refs(spec) -> dict:
    """Backfill missing reference field values in sample_data using round-robin
    assignment from the referenced collection's seed records. Ensures generated
    apps (SQL and Mongo) don't crash on NOT NULL FK constraints."""
    sd = spec.to_dict().get("sample_data", {})
    if not sd:
        return sd
    entities = {e.collection: e for e in spec.entities}
    for coll, docs in sd.items():
        entity = entities.get(coll)
        if not entity:
            continue
        ref_fields = [f for f in entity.fields if f.type.value == "reference" and f.reference]
        for rf in ref_fields:
            target_docs = sd.get(rf.reference, [])
            if not target_docs:
                continue
            pick = 0
            for doc in docs:
                if doc.get(rf.name) not in (None, "", 0):
                    continue
                target = target_docs[pick % len(target_docs)]
                doc[rf.name] = target.get("_id") or target.get("id") or f"ref_{pick}"
                pick += 1
    return sd



_BSON_MAP = {
    "string": "string", "text": "string", "email": "string", "enum": "string",
    "integer": "int", "float": "double", "boolean": "bool", "datetime": "date",
    "reference": "objectId", "array": "array", "object": "object",
    "geo_point": "object", "vector": "array",
}


def _extract_mongodb_insights(spec) -> dict:
    """Extract collections, indexes, schema validation, and design rationale from an AppSpec."""
    entities = spec.entities if hasattr(spec, "entities") else []
    collections = []

    for entity in entities:
        fields = entity.fields if hasattr(entity, "fields") else []
        coll_name = entity.collection if hasattr(entity, "collection") else entity.name.lower()

        type_counts: dict[str, int] = {}
        for f in fields:
            ft = f.type.value if hasattr(f.type, "value") else str(f.type)
            type_counts[ft] = type_counts.get(ft, 0) + 1

        refs = [
            {"field": f.name, "target": f.reference}
            for f in fields
            if (f.type.value if hasattr(f.type, "value") else str(f.type)) == "reference"
        ]

        embeds = [
            {"name": e.name, "field_count": len(e.fields) if hasattr(e, "fields") else 0}
            for e in (entity.embedded_entities if hasattr(entity, "embedded_entities") else [])
        ]

        # --- Explicit indexes ---
        explicit_indexes = []
        for idx in (entity.indexes if hasattr(entity, "indexes") else []):
            keys = idx.keys if hasattr(idx, "keys") else {}
            idx_type = idx.type.value if hasattr(idx.type, "value") else str(idx.type)
            name = idx.name if idx.name else f"{coll_name}_{'_'.join(keys)}"
            rationale = _index_rationale(keys, idx_type, idx.unique, idx.sparse,
                                         getattr(idx, "expire_after_seconds", None))
            explicit_indexes.append({
                "name": name, "keys": keys, "type": idx_type,
                "unique": idx.unique, "sparse": idx.sparse,
                "ttl": getattr(idx, "expire_after_seconds", None),
                "rationale": rationale, "source": "explicit",
            })

        # --- Implicit indexes from field flags ---
        implicit_indexes = []
        filterable, sortable = [], []

        for f in fields:
            ft = f.type.value if hasattr(f.type, "value") else str(f.type)
            if f.is_unique:
                implicit_indexes.append({
                    "name": f"{coll_name}_{f.name}_unique",
                    "keys": {f.name: 1}, "type": "unique", "unique": True,
                    "sparse": not f.required, "ttl": None,
                    "rationale": f"Enforces uniqueness on {f.name}",
                    "source": "field:is_unique",
                })
            if ft == "reference":
                implicit_indexes.append({
                    "name": f"{coll_name}_{f.name}_ref",
                    "keys": {f.name: 1}, "type": "regular", "unique": False,
                    "sparse": False, "ttl": None,
                    "rationale": f"Accelerates $lookup joins on {f.name} → {f.reference}",
                    "source": "field:reference",
                })
            if ft == "geo_point":
                implicit_indexes.append({
                    "name": f"{coll_name}_{f.name}_geo",
                    "keys": {f.name: "2dsphere"}, "type": "2dsphere", "unique": False,
                    "sparse": False, "ttl": None,
                    "rationale": f"Enables geospatial queries on {f.name}",
                    "source": "field:geo_point",
                })
            if ft == "text":
                implicit_indexes.append({
                    "name": f"{coll_name}_{f.name}_text",
                    "keys": {f.name: "text"}, "type": "text", "unique": False,
                    "sparse": False, "ttl": None,
                    "rationale": f"Enables full-text search on {f.name}",
                    "source": "field:text",
                })
            if f.is_filterable:
                filterable.append(f.name)
            if f.is_sortable:
                sortable.append(f.name)

        # --- ESR compound index ---
        esr_index = None
        if filterable or sortable:
            esr_keys = {}
            esr_parts = []
            for fn in filterable:
                esr_keys[fn] = 1
                esr_parts.append({"field": fn, "role": "E"})
            for fn in sortable:
                esr_keys[fn] = -1
                esr_parts.append({"field": fn, "role": "S"})
            eq_str = ", ".join(filterable) if filterable else "none"
            sort_str = ", ".join(sortable) if sortable else "none"
            esr_index = {
                "name": f"{coll_name}_esr_compound",
                "keys": esr_keys, "type": "compound (ESR)",
                "unique": False, "sparse": False, "ttl": None,
                "parts": esr_parts,
                "rationale": f"ESR pattern — equality({eq_str}) → sort({sort_str})",
                "source": "esr",
            }

        # --- Schema validation summary ---
        required_fields = [f.name for f in fields if f.required]
        validation_rules = []
        for f in fields:
            ft = f.type.value if hasattr(f.type, "value") else str(f.type)
            bson = _BSON_MAP.get(ft, "string")
            rule = {"field": f.name, "bsonType": bson}
            if ft == "enum" and f.enum_values:
                rule["enum"] = f.enum_values
            if f.max_length:
                rule["maxLength"] = f.max_length
            if f.pattern:
                rule["pattern"] = f.pattern
            if f.min_value is not None:
                rule["minimum"] = f.min_value
            if f.max_value is not None:
                rule["maximum"] = f.max_value
            validation_rules.append(rule)

        collections.append({
            "name": entity.name,
            "collection": coll_name,
            "description": entity.description or "",
            "field_count": len(fields),
            "type_counts": type_counts,
            "references": refs,
            "embeds": embeds,
            "is_time_series": getattr(entity, "is_time_series", False),
            "time_field": getattr(entity, "time_field", ""),
            "explicit_indexes": explicit_indexes,
            "implicit_indexes": implicit_indexes,
            "esr_index": esr_index,
            "required_fields": required_fields,
            "validation_rules": validation_rules,
        })

    # --- Design rationale ---
    rationale = []
    for c in collections:
        for emb in c["embeds"]:
            rationale.append({
                "icon": "embed",
                "text": f'Embedded <b>{emb["name"]}</b> inside <b>{c["name"]}</b> — '
                        f'co-located reads, no extra $lookup',
            })
        for ref in c["references"]:
            rationale.append({
                "icon": "ref",
                "text": f'<b>{c["name"]}</b> references <b>{ref["target"]}</b> via '
                        f'<code>{ref["field"]}</code> — independent lifecycle, indexed for $lookup',
            })
        if c["esr_index"]:
            rationale.append({
                "icon": "index",
                "text": f'ESR compound index on <b>{c["collection"]}</b> — '
                        f'{c["esr_index"]["rationale"]}',
            })
        if c["is_time_series"]:
            rationale.append({
                "icon": "ts",
                "text": f'<b>{c["collection"]}</b> uses a time-series collection '
                        f'(timeField: <code>{c["time_field"]}</code>) for optimized temporal queries',
            })

    auth = spec.auth if hasattr(spec, "auth") else None
    if auth and getattr(auth, "enabled", False):
        roles = getattr(auth, "roles", [])
        strategy = getattr(auth, "strategy", "jwt")
        rationale.append({
            "icon": "auth",
            "text": f'{strategy.upper()} auth with RBAC roles: <b>{", ".join(roles) if roles else "default"}</b>',
        })

    total_indexes = sum(
        len(c["explicit_indexes"]) + len(c["implicit_indexes"]) + (1 if c["esr_index"] else 0)
        for c in collections
    )
    rationale.append({
        "icon": "schema",
        "text": f'$jsonSchema validation enforces required fields and bsonType constraints '
                f'across {len(collections)} collection{"s" if len(collections) != 1 else ""}',
    })

    return {
        "collections": collections,
        "rationale": rationale,
        "total_indexes": total_indexes,
    }


def _index_rationale(keys: dict, idx_type: str, unique: bool, sparse: bool, ttl) -> str:
    key_str = ", ".join(
        f"{k} {'↑' if v == 1 else '↓' if v == -1 else v}" for k, v in keys.items()
    )
    parts = []
    if unique:
        parts.append("enforces uniqueness")
    if idx_type == "text":
        parts.append("enables full-text search")
    elif idx_type == "2dsphere":
        parts.append("enables geospatial queries")
    elif idx_type == "vectorSearch":
        parts.append("enables vector similarity search")
    else:
        parts.append(f"optimizes queries on ({key_str})")
    if sparse:
        parts.append("sparse")
    if ttl:
        parts.append(f"TTL {ttl}s")
    return "; ".join(parts).capitalize()


def _build_mongodb_panel(spec) -> str:
    """Build the full-page MongoDB insights view, toggled via banner tabs."""
    db_engine = "mongodb"
    if hasattr(spec, "database") and hasattr(spec.database, "engine"):
        db_engine = spec.database.engine.value if hasattr(spec.database.engine, "value") else str(spec.database.engine)
    if db_engine != "mongodb":
        return ""

    insights = _extract_mongodb_insights(spec)
    insights_json = json.dumps(insights, default=str)

    return """
<style>
#mdb-view{display:none;position:fixed;top:44px;left:0;right:0;bottom:0;
  background:#0c0c0f;overflow-y:auto;font-family:system-ui,-apple-system,sans-serif;}
#mdb-view.active{display:block;}
#mdb-view::-webkit-scrollbar{width:6px;}
#mdb-view::-webkit-scrollbar-thumb{background:#2a2a30;border-radius:3px;}
.mdb-wrap{max-width:960px;margin:0 auto;padding:24px 28px 48px;}
.mdb-header{display:flex;align-items:center;gap:12px;margin-bottom:20px;}
.mdb-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
@media(max-width:700px){.mdb-grid{grid-template-columns:1fr;}}
.mdb-col{min-width:0;}
.mdb-section{margin-bottom:20px;}
.mdb-section-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.15em;
  color:#00ED64;margin-bottom:10px;display:flex;align-items:center;gap:6px;}
.mdb-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);
  border-radius:10px;padding:12px;margin-bottom:8px;transition:border-color .2s;}
.mdb-card:hover{background:rgba(255,255,255,0.05);border-color:rgba(0,237,100,0.15);}
.mdb-coll-name{font-size:13px;font-weight:600;color:#e4e4e7;}
.mdb-coll-sub{font-size:10px;color:#71717a;font-family:'SF Mono',monospace;margin-top:2px;}
.mdb-badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;font-size:9px;font-weight:600;margin:2px;}
.mdb-badge-type{background:rgba(99,102,241,0.12);color:#a5b4fc;}
.mdb-badge-ref{background:rgba(251,191,36,0.12);color:#fbbf24;}
.mdb-badge-embed{background:rgba(52,211,153,0.12);color:#34d399;}
.mdb-badge-ts{background:rgba(244,114,182,0.12);color:#f472b6;}
.mdb-idx{display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.03);}
.mdb-idx:last-child{border-bottom:none;}
.mdb-idx-badge{font-size:8px;font-weight:700;padding:2px 6px;border-radius:3px;flex-shrink:0;margin-top:2px;
  text-transform:uppercase;letter-spacing:0.1em;}
.mdb-idx-explicit{background:rgba(0,237,100,0.12);color:#00ED64;}
.mdb-idx-implicit{background:rgba(99,102,241,0.12);color:#a5b4fc;}
.mdb-idx-esr{background:rgba(251,191,36,0.12);color:#fbbf24;}
.mdb-idx-keys{font-size:11px;font-family:'SF Mono',monospace;color:#a1a1aa;}
.mdb-idx-name{font-size:10px;color:#71717a;margin-top:1px;}
.mdb-idx-rationale{font-size:10px;color:#52525b;margin-top:2px;font-style:italic;}
.mdb-esr-e{color:#34d399;font-weight:700;}
.mdb-esr-s{color:#fbbf24;font-weight:700;}
.mdb-esr-r{color:#f87171;font-weight:700;}
.mdb-rationale-item{display:flex;align-items:flex-start;gap:10px;padding:8px 0;
  border-bottom:1px solid rgba(255,255,255,0.03);font-size:11px;color:#a1a1aa;line-height:1.5;}
.mdb-rationale-item:last-child{border-bottom:none;}
.mdb-rationale-item b{color:#e4e4e7;font-weight:600;}
.mdb-rationale-item code{background:rgba(255,255,255,0.06);padding:1px 5px;border-radius:3px;
  font-size:10px;font-family:'SF Mono',monospace;color:#a5b4fc;}
.mdb-rationale-icon{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;
  justify-content:center;flex-shrink:0;margin-top:1px;font-size:11px;}
.mdb-ri-embed{background:rgba(52,211,153,0.12);}
.mdb-ri-ref{background:rgba(251,191,36,0.12);}
.mdb-ri-index{background:rgba(0,237,100,0.12);}
.mdb-ri-auth{background:rgba(99,102,241,0.12);}
.mdb-ri-schema{background:rgba(139,92,246,0.12);}
.mdb-ri-ts{background:rgba(244,114,182,0.12);}
.mdb-schema-row{display:flex;align-items:center;justify-content:space-between;padding:4px 0;
  font-size:10px;border-bottom:1px solid rgba(255,255,255,0.02);}
.mdb-schema-field{font-family:'SF Mono',monospace;color:#a1a1aa;}
.mdb-schema-bson{font-family:'SF Mono',monospace;color:#34d399;font-size:9px;}
.mdb-schema-constraint{color:#71717a;font-size:9px;margin-left:4px;}
.mdb-stat{text-align:center;padding:6px 0;}
.mdb-stat-val{font-size:22px;font-weight:700;color:#00ED64;}
.mdb-stat-label{font-size:9px;color:#52525b;text-transform:uppercase;letter-spacing:0.1em;}
</style>

<div id="mdb-view">
<div class="mdb-wrap">

  <div class="mdb-header">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M13.74 4.17c-.58-1.37-1.19-1.88-1.42-2.17-.18.27-.7.73-1.25 1.93C9.5 8.07 6 10.27 6 14.52 6 18.07 8.69 21 12 21s6-2.93 6-6.48c0-4.29-2.95-7.57-4.26-10.35Z" fill="#00ED64"/></svg>
    <div>
      <div style="font-size:16px;font-weight:700;color:#e4e4e7;">MongoDB Insights</div>
      <div style="font-size:11px;color:#52525b;">Schema design, indexes, rationale &amp; setup scripts</div>
    </div>
  </div>

  <div id="mdb-stats" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:24px;"></div>

  <div class="mdb-grid">
    <div class="mdb-col">
      <div id="mdb-collections-section" class="mdb-section"></div>
      <div id="mdb-rationale-section" class="mdb-section"></div>
    </div>
    <div class="mdb-col">
      <div id="mdb-indexes-section" class="mdb-section"></div>
      <div id="mdb-schema-section" class="mdb-section"></div>
    </div>
  </div>

  <div id="mdb-scripts-section" class="mdb-section"></div>

</div>
</div>

<script>
(function(){
  const I = __MDB_INSIGHTS__;
  const colls = I.collections || [];
  const totalFields = colls.reduce((a,c)=>a+c.field_count,0);

  // Stats
  const statsEl = document.getElementById('mdb-stats');
  if (statsEl) {
    const totalRefs = colls.reduce((a,c)=>a+c.references.length,0);
    statsEl.innerHTML = [
      ['Collections', colls.length, '#00ED64'],
      ['Fields', totalFields, '#a5b4fc'],
      ['Indexes', I.total_indexes, '#fbbf24'],
      ['References', totalRefs, '#34d399'],
    ].map(([l,v,c])=>`<div class="mdb-stat" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:10px;padding:10px;">
      <div class="mdb-stat-val" style="color:${c};">${v}</div><div class="mdb-stat-label">${l}</div></div>`).join('');
  }

  // Collections
  const collsEl = document.getElementById('mdb-collections-section');
  if (collsEl && colls.length) {
    let h = '<div class="mdb-section-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>Collections</div>';
    for (const c of colls) {
      const typeBadges = Object.entries(c.type_counts).map(([t,n])=>`<span class="mdb-badge mdb-badge-type">${t} &times;${n}</span>`).join('');
      const refBadges = c.references.map(r=>`<span class="mdb-badge mdb-badge-ref">&rarr; ${r.target}</span>`).join('');
      const embedBadges = c.embeds.map(e=>`<span class="mdb-badge mdb-badge-embed">&laquo; ${e.name} (${e.field_count}f)</span>`).join('');
      const tsBadge = c.is_time_series ? '<span class="mdb-badge mdb-badge-ts">time-series</span>' : '';
      h += `<div class="mdb-card">
        <div class="mdb-coll-name">${c.name}</div>
        <div class="mdb-coll-sub">${c.collection} &middot; ${c.field_count} fields</div>
        ${c.description ? '<div style="font-size:10px;color:#71717a;margin-top:4px;">'+c.description+'</div>' : ''}
        <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:2px;">${typeBadges}${refBadges}${embedBadges}${tsBadge}</div>
      </div>`;
    }
    collsEl.innerHTML = h;
  }

  // Indexes
  const idxEl = document.getElementById('mdb-indexes-section');
  if (idxEl) {
    let h = '<div class="mdb-section-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><path d="M4 6h16M4 12h10M4 18h6"/></svg>Indexes</div>';
    for (const c of colls) {
      const allIdx = [...c.explicit_indexes, ...c.implicit_indexes];
      if (c.esr_index) allIdx.push(c.esr_index);
      if (!allIdx.length) continue;
      h += '<div style="margin-bottom:12px;"><div style="font-size:11px;font-weight:600;color:#a1a1aa;margin-bottom:4px;">'+c.collection+'</div>';
      for (const idx of allIdx) {
        const badgeClass = idx.source === 'esr' ? 'mdb-idx-esr' : idx.source === 'explicit' ? 'mdb-idx-explicit' : 'mdb-idx-implicit';
        const label = idx.source === 'esr' ? 'ESR' : idx.source === 'explicit' ? 'DEF' : 'AUTO';
        let keysHtml;
        if (idx.parts) {
          keysHtml = idx.parts.map(p => {
            const cls = p.role === 'E' ? 'mdb-esr-e' : p.role === 'S' ? 'mdb-esr-s' : 'mdb-esr-r';
            return '<span class="'+cls+'">'+p.role+'</span>:'+p.field;
          }).join(' &rarr; ');
        } else {
          keysHtml = Object.entries(idx.keys).map(([k,v])=>k+':'+(v===1?'1':v===-1?'-1':v)).join(', ');
        }
        h += `<div class="mdb-idx">
          <span class="mdb-idx-badge ${badgeClass}">${label}</span>
          <div>
            <div class="mdb-idx-keys">${keysHtml}${idx.unique?' <span style="color:#f87171;font-size:9px;">UNIQUE</span>':''}${idx.ttl?' <span style="color:#fbbf24;font-size:9px;">TTL:'+idx.ttl+'s</span>':''}</div>
            <div class="mdb-idx-name">${idx.name}</div>
            <div class="mdb-idx-rationale">${idx.rationale}</div>
          </div>
        </div>`;
      }
      h += '</div>';
    }
    idxEl.innerHTML = h;
  }

  // Design rationale
  const ratEl = document.getElementById('mdb-rationale-section');
  if (ratEl && I.rationale.length) {
    const iconMap = {
      embed: '<div class="mdb-rationale-icon mdb-ri-embed" style="color:#34d399;">&#x2B9E;</div>',
      ref: '<div class="mdb-rationale-icon mdb-ri-ref" style="color:#fbbf24;">&#x2192;</div>',
      index: '<div class="mdb-rationale-icon mdb-ri-index" style="color:#00ED64;">&#x2261;</div>',
      auth: '<div class="mdb-rationale-icon mdb-ri-auth" style="color:#a5b4fc;">&#x26BF;</div>',
      schema: '<div class="mdb-rationale-icon mdb-ri-schema" style="color:#a78bfa;">&#x2714;</div>',
      ts: '<div class="mdb-rationale-icon mdb-ri-ts" style="color:#f472b6;">&#x23F1;</div>',
    };
    let h = '<div class="mdb-section-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><circle cx="12" cy="12" r="10"/><path d="M12 17h.01"/></svg>Design Rationale</div>';
    for (const r of I.rationale) {
      h += `<div class="mdb-rationale-item">${iconMap[r.icon]||''}<div>${r.text}</div></div>`;
    }
    ratEl.innerHTML = h;
  }

  // Schema validation
  const schEl = document.getElementById('mdb-schema-section');
  if (schEl) {
    let h = '<div class="mdb-section-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>$jsonSchema Validation</div>';
    for (const c of colls) {
      if (!c.validation_rules.length) continue;
      h += '<div style="margin-bottom:10px;"><div style="font-size:11px;font-weight:600;color:#a1a1aa;margin-bottom:4px;">'+c.collection;
      if (c.required_fields.length) h += ' <span style="font-size:9px;color:#52525b;font-weight:400;">('+c.required_fields.length+' required)</span>';
      h += '</div>';
      for (const r of c.validation_rules) {
        let extra = '';
        if (r.enum) extra += ' enum:['+r.enum.join(',')+']';
        if (r.maxLength) extra += ' max:'+r.maxLength;
        if (r.pattern) extra += ' /'+r.pattern+'/';
        if (r.minimum!=null) extra += ' &ge;'+r.minimum;
        if (r.maximum!=null) extra += ' &le;'+r.maximum;
        const req = c.required_fields.includes(r.field);
        h += `<div class="mdb-schema-row">
          <span class="mdb-schema-field">${req?'<b>'+r.field+'</b>':r.field}</span>
          <span><span class="mdb-schema-bson">${r.bsonType}</span>${extra?'<span class="mdb-schema-constraint">'+extra+'</span>':''}</span>
        </div>`;
      }
      h += '</div>';
    }
    schEl.innerHTML = h;
  }

  // Setup scripts
  const scrEl = document.getElementById('mdb-scripts-section');
  if (scrEl) {
    const scripts = [
      {file:'00-setup.js',      desc:'Creates collections (regular + time-series)', icon:'&#x25B6;', color:'#34d399'},
      {file:'01-validation.js',  desc:'Applies $jsonSchema validation rules',        icon:'&#x2714;', color:'#a78bfa'},
      {file:'02-indexes.js',     desc:'Creates all indexes (explicit, ESR, implicit)',icon:'&#x2261;', color:'#00ED64'},
      {file:'03-seed.js',        desc:'Inserts sample data into collections',         icon:'&#x2736;', color:'#fbbf24'},
    ];
    let h = '<div class="mdb-section-title"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><path d="M8 9l3 3-3 3"/><path d="M13 15h3"/><rect x="3" y="3" width="18" height="18" rx="2"/></svg>Setup Scripts</div>';
    h += '<div style="font-size:10px;color:#71717a;line-height:1.5;margin-bottom:12px;">Generated <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:9px;color:#00ED64;">mongosh</code>-compatible JavaScript in <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:9px;color:#a1a1aa;">mongo-init/</code> &mdash; auto-run via Docker or execute manually.</div>';

    h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">';
    for (const s of scripts) {
      h += `<div class="mdb-card" style="display:flex;align-items:flex-start;gap:8px;">
        <div style="width:20px;height:20px;border-radius:5px;background:rgba(0,237,100,0.08);border:1px solid rgba(0,237,100,0.2);display:flex;align-items:center;justify-content:center;font-size:9px;color:${s.color};flex-shrink:0;">${s.icon}</div>
        <div><div style="font-size:10px;font-family:monospace;color:#e4e4e7;">${s.file}</div>
        <div style="font-size:9px;color:#52525b;margin-top:1px;">${s.desc}</div></div>
      </div>`;
    }
    h += '</div>';

    h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">';

    h += '<div class="mdb-card">';
    h += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">';
    h += '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2"/><path d="M7 10h10M7 14h6"/></svg>';
    h += '<span style="font-size:10px;font-weight:600;color:#38bdf8;">Docker Auto-Init</span></div>';
    h += '<div style="font-size:9px;color:#71717a;line-height:1.5;">Mounted to <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:8px;color:#a1a1aa;">/docker-entrypoint-initdb.d/</code><br>Runs in alphabetical order on first <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:8px;color:#a1a1aa;">docker compose up</code>. Fully idempotent.</div>';
    h += '</div>';

    h += '<div class="mdb-card">';
    h += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">';
    h += '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>';
    h += '<span style="font-size:10px;font-weight:600;color:#fbbf24;">Why mongosh + JS?</span></div>';
    h += '<div style="font-size:9px;color:#71717a;line-height:1.6;">Built on <b style="color:#a1a1aa;">Node.js</b>: ES6+, <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:8px;color:#a5b4fc;">async/await</code>, <code style="background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px;font-size:8px;color:#a5b4fc;">require()</code> for NPM modules. Scripts are idempotent with try/catch.</div>';
    h += '</div>';

    h += '</div>';

    h += '<div class="mdb-card" style="margin-top:10px;">';
    h += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">';
    h += '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#00ED64" stroke-width="2"><path d="M8 9l3 3-3 3"/><path d="M13 15h3"/></svg>';
    h += '<span style="font-size:10px;font-weight:600;color:#00ED64;">Manual via mongosh</span></div>';
    h += '<div style="background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.04);border-radius:6px;padding:8px 10px;font-family:monospace;font-size:9px;color:#a1a1aa;line-height:1.7;overflow-x:auto;">';
    h += '<span style="color:#52525b;"># Run all init scripts</span><br>';
    h += '<span style="color:#00ED64;">mongosh</span> <span style="color:#fbbf24;">"mongodb://localhost:27017/mydb"</span> mongo-init/00-setup.js<br>';
    h += '<span style="color:#00ED64;">mongosh</span> <span style="color:#fbbf24;">"mongodb://localhost:27017/mydb"</span> mongo-init/01-validation.js<br>';
    h += '<span style="color:#00ED64;">mongosh</span> <span style="color:#fbbf24;">"mongodb://localhost:27017/mydb"</span> mongo-init/02-indexes.js<br>';
    h += '<span style="color:#00ED64;">mongosh</span> <span style="color:#fbbf24;">"mongodb://localhost:27017/mydb"</span> mongo-init/03-seed.js';
    h += '</div></div>';

    scrEl.innerHTML = h;
  }
})();
</script>
""".replace("__MDB_INSIGHTS__", insights_json)


def _build_preview_page(html: str, session_id: str, spec) -> str:
    """Inject a fetch shim + preview banner into the generated index.html."""
    if not html:
        return (
            "<html><body style='font-family:system-ui;padding:4rem;text-align:center'>"
            "<h1>No UI generated for this stack</h1></body></html>"
        )

    sample_data = spec.to_dict().get("sample_data", {})
    app_name = getattr(spec, "app_name", "App")

    shim_js = """<script>
(function(){
  const _S = __PREVIEW_SPEC__;
  const _D = __PREVIEW_DATA__;
  const db = {};
  let _autoId = 0;
  for (const [k, v] of Object.entries(_D)) {
    const rows = JSON.parse(JSON.stringify(v));
    db[k] = rows.map((row) => {
      if (!row._id && !row.id) row._id = `${k}_preview_${++_autoId}`;
      if (!row.id) row.id = row._id;
      return row;
    });
  }

  const entityByCollection = new Map();
  const entityByName = new Map();
  for (const ent of (_S.entities || [])) {
    if (ent.collection) entityByCollection.set(ent.collection, ent);
    if (ent.name) entityByName.set(String(ent.name).toLowerCase(), ent);
  }

  function resolveRefCollection(ref) {
    if (!ref) return null;
    if (db[ref]) return ref;
    const lower = String(ref).toLowerCase();
    if (db[lower]) return lower;
    for (const k of Object.keys(db)) {
      if (String(k).toLowerCase() === lower) return k;
    }
    const byName = entityByName.get(lower);
    if (byName && db[byName.collection]) return byName.collection;
    return null;
  }

  // Backfill missing reference IDs so edit/delete and relation UX behaves like real apps.
  for (const [coll, rows] of Object.entries(db)) {
    const ent = entityByCollection.get(coll) || entityByName.get(String(coll).toLowerCase());
    if (!ent || !Array.isArray(ent.fields)) continue;
    const refFields = ent.fields.filter(f => f.type === 'reference' && f.reference);
    if (!refFields.length) continue;

    for (const rf of refFields) {
      const targetColl = resolveRefCollection(rf.reference);
      const targetRows = targetColl ? (db[targetColl] || []) : [];
      if (!targetRows.length) continue;
      let pick = 0;
      for (const row of rows) {
        if (row[rf.name] !== undefined && row[rf.name] !== null && row[rf.name] !== '') continue;
        const target = targetRows[pick % targetRows.length];
        row[rf.name] = target._id || target.id;
        pick += 1;
      }
    }
  }

  function jsonResp(body, status) {
    return new Response(JSON.stringify(body), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const _origFetch = window.fetch;
  window.fetch = async function(url, opts) {
    const u = new URL(url, location.origin);
    const p = u.pathname.replace(/^\\/api/, '');
    const method = (opts && opts.method || 'GET').toUpperCase();

    if (p.startsWith('/auth/login') || p.startsWith('/auth/register')) {
      const fakeJwt = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.' +
        btoa(JSON.stringify({sub:'preview_user',role:'admin',exp:9999999999}))
          .replace(/=/g,'') + '.preview';
      return jsonResp({ access_token: fakeJwt });
    }

    const parts = p.replace(/^\\//, '').split('/');
    const coll = parts[0];
    const docId = parts[1];

    if (!coll || !db.hasOwnProperty(coll)) {
      return _origFetch.call(window, url, opts);
    }

    if (method === 'GET' && !docId) return jsonResp(db[coll]);
    if (method === 'GET' && docId) {
      const item = db[coll].find(d => (d._id || d.id) === docId);
      return item ? jsonResp(item) : jsonResp({detail:'Not found'}, 404);
    }
    if (method === 'POST') {
      let body = {};
      if (opts && opts.body) { try { if (typeof opts.body === 'string') body = JSON.parse(opts.body); } catch(_e) {} }
      body._id = 'preview_' + Math.random().toString(36).slice(2, 10);
      body.id = body._id;
      db[coll].push(body);
      return jsonResp(body, 201);
    }
    if (method === 'PUT' || method === 'PATCH') {
      let body = {};
      if (opts && opts.body) { try { if (typeof opts.body === 'string') body = JSON.parse(opts.body); } catch(_e) {} }
      const idx = db[coll].findIndex(d => (d._id || d.id) === docId);
      if (idx >= 0) { Object.assign(db[coll][idx], body); return jsonResp(db[coll][idx]); }
      return jsonResp({detail:'Not found'}, 404);
    }
    if (method === 'DELETE') {
      db[coll] = db[coll].filter(d => (d._id || d.id) !== docId);
      return new Response(null, { status: 204 });
    }
    return _origFetch.call(window, url, opts);
  };
})();
</script>
<script>
(function(){
  const DEMO = {
    email: 'demo@demo.com',
    password: 'demo1234',
    name: 'Demo User',
    username: 'demo',
    first_name: 'Demo',
    last_name: 'User',
    role: 'admin',
  };

  const FIELD_MAP = {
    email: ['email', 'e-mail', 'user_email', 'userEmail'],
    password: ['password', 'pass', 'passwd', 'user_password'],
    name: ['name', 'full_name', 'fullName', 'display_name', 'displayName'],
    username: ['username', 'user_name', 'login', 'user'],
    first_name: ['first_name', 'firstName', 'fname'],
    last_name: ['last_name', 'lastName', 'lname', 'surname'],
    role: ['role', 'user_role'],
  };

  function fillField(input, value) {
    if (input._demoFilled) return;
    const setter = Object.getOwnPropertyDescriptor(
      input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value'
    )?.set;
    if (setter) setter.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event('input', {bubbles:true}));
    input.dispatchEvent(new Event('change', {bubbles:true}));
    input._demoFilled = true;
  }

  function fillForm(root) {
    const inputs = root.querySelectorAll('input, select');
    for (const el of inputs) {
      const n = (el.name || el.id || el.getAttribute('autocomplete') || '').toLowerCase();
      const t = (el.type || '').toLowerCase();
      const p = (el.placeholder || '').toLowerCase();

      if (t === 'email' || n.includes('email') || p.includes('email'))
        { fillField(el, DEMO.email); continue; }
      if (t === 'password' || n.includes('password') || p.includes('password'))
        { fillField(el, DEMO.password); continue; }

      for (const [key, aliases] of Object.entries(FIELD_MAP)) {
        if (aliases.some(a => n.includes(a) || p.includes(a))) {
          fillField(el, DEMO[key]);
          break;
        }
      }
    }
  }

  function scan() { fillForm(document); }
  document.addEventListener('DOMContentLoaded', scan);
  setTimeout(scan, 300);
  setTimeout(scan, 800);

  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType === 1) fillForm(node);
      }
    }
  });
  if (document.body) obs.observe(document.body, {childList:true, subtree:true});
  else document.addEventListener('DOMContentLoaded', () => {
    obs.observe(document.body, {childList:true, subtree:true});
  });
})();
</script>""".replace("__PREVIEW_SPEC__", json.dumps(spec.to_dict(), default=str)).replace("__PREVIEW_DATA__", json.dumps(sample_data, default=str))

    is_mongo = False
    if hasattr(spec, "database") and hasattr(spec.database, "engine"):
        eng = spec.database.engine.value if hasattr(spec.database.engine, "value") else str(spec.database.engine)
        is_mongo = eng == "mongodb"

    tab_style = ("background:rgba(255,255,255,0.2);color:#fff;font-size:10px;font-weight:600;"
                 "padding:3px 12px;border-radius:5px;border:none;cursor:pointer;transition:all .2s;"
                 "font-family:system-ui,sans-serif;letter-spacing:0.02em;")
    tab_active_app = "background:rgba(255,255,255,0.95);color:#4f46e5;"
    tab_active_mdb = "background:#00ED64;color:#00422B;"

    tabs_html = ""
    if is_mongo:
        tabs_html = f"""
        <div style="display:flex;align-items:center;gap:4px;margin-left:12px;background:rgba(255,255,255,0.1);padding:2px;border-radius:7px;">
          <button id="tab-app" onclick="switchPreviewTab('app')" style="{tab_style}{tab_active_app}">App</button>
          <button id="tab-mdb" onclick="switchPreviewTab('mdb')" style="{tab_style}">
            <span style="display:inline-flex;align-items:center;gap:4px;">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none"><path d="M13.74 4.17c-.58-1.37-1.19-1.88-1.42-2.17-.18.27-.7.73-1.25 1.93C9.5 8.07 6 10.27 6 14.52 6 18.07 8.69 21 12 21s6-2.93 6-6.48c0-4.29-2.95-7.57-4.26-10.35Z" fill="currentColor"/></svg>
              MongoDB
            </span>
          </button>
        </div>"""

    toggle_js = """
    <script>
    function switchPreviewTab(tab) {
      const mdbView = document.getElementById('mdb-view');
      const tabApp = document.getElementById('tab-app');
      const tabMdb = document.getElementById('tab-mdb');
      if (!mdbView || !tabApp || !tabMdb) return;
      if (tab === 'mdb') {
        mdbView.classList.add('active');
        tabMdb.style.background = '#00ED64';
        tabMdb.style.color = '#00422B';
        tabApp.style.background = 'rgba(255,255,255,0.2)';
        tabApp.style.color = '#fff';
      } else {
        mdbView.classList.remove('active');
        tabApp.style.background = 'rgba(255,255,255,0.95)';
        tabApp.style.color = '#4f46e5';
        tabMdb.style.background = 'rgba(255,255,255,0.2)';
        tabMdb.style.color = '#fff';
      }
    }
    </script>""" if is_mongo else ""

    banner = f"""<div id="appspec-preview-banner" style="position:fixed;top:0;left:0;right:0;z-index:9999;
      background:linear-gradient(135deg,#6366f1,#4f46e5,#7c3aed);padding:9px 20px;
      display:flex;align-items:center;justify-content:space-between;font-family:system-ui,sans-serif;
      box-shadow:0 2px 16px rgba(99,102,241,0.35);">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="background:rgba(255,255,255,0.2);padding:2px 8px;border-radius:4px;
          font-size:10px;font-weight:700;color:#fff;letter-spacing:0.12em;">PREVIEW</span>
        <span style="color:rgba(255,255,255,0.95);font-size:13px;font-weight:600;">{app_name}</span>
        {tabs_html}
        <span style="color:rgba(255,255,255,0.4);font-size:10px;margin-left:4px;">
          <code style="background:rgba(255,255,255,0.12);padding:1px 5px;border-radius:3px;font-size:9px;color:rgba(255,255,255,0.8);">demo@demo.com</code>
          /
          <code style="background:rgba(255,255,255,0.12);padding:1px 5px;border-radius:3px;font-size:9px;color:rgba(255,255,255,0.8);">demo1234</code>
        </span>
      </div>
      <a href="/download/{session_id}" style="background:#fff;color:#4f46e5;padding:5px 16px;
        border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;
        transition:opacity 0.2s;" onmouseover="this.style.opacity='0.85'"
        onmouseout="this.style.opacity='1'">Download .zip</a>
    </div>
    {toggle_js}
    <style>body {{ padding-top: 44px !important; }}</style>"""

    mongodb_panel = _build_mongodb_panel(spec)

    html = html.replace("</head>", shim_js + "\n</head>", 1)
    body_open = html.find("<body")
    insert_at = html.find(">", body_open) + 1
    html = html[:insert_at] + banner + mongodb_panel + html[insert_at:]
    return html



# ── HTML ─────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AppSpec</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'] },
      colors: {
        surface:   { DEFAULT: '#0c0c0f', 50: '#111114', 100: '#16161a', 200: '#1c1c21', 300: '#24242b' },
        accent:    { DEFAULT: '#6366f1', dim: '#4f46e5', bright: '#818cf8', glow: 'rgba(99,102,241,0.15)' },
        mint:      { DEFAULT: '#34d399', dim: '#059669', glow: 'rgba(52,211,153,0.12)' },
      },
      animation: {
        'fade-in':     'fadeIn 0.5s ease-out',
        'fade-up':     'fadeUp 0.5s ease-out',
        'slide-right': 'slideRight 0.4s ease-out',
        'scale-in':    'scaleIn 0.3s ease-out',
        'glow-pulse':  'glowPulse 2s ease-in-out infinite',
        'dot-pulse':   'dotPulse 1.2s ease-in-out infinite',
        'shimmer':     'shimmer 2s linear infinite',
      },
      keyframes: {
        fadeIn:     { from: { opacity: '0' }, to: { opacity: '1' } },
        fadeUp:     { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideRight: { from: { opacity: '0', transform: 'translateX(-8px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
        scaleIn:    { from: { opacity: '0', transform: 'scale(0.95)' }, to: { opacity: '1', transform: 'scale(1)' } },
        glowPulse:  { '0%,100%': { opacity: '0.4' }, '50%': { opacity: '1' } },
        dotPulse:   { '0%,100%': { opacity: '0.3', transform: 'scale(0.85)' }, '50%': { opacity: '1', transform: 'scale(1)' } },
        shimmer:    { from: { backgroundPosition: '200% 0' }, to: { backgroundPosition: '-200% 0' } },
      }
    }
  }
}
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-typescript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-sql.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-yaml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-docker.min.js"></script>
<style>
  html { scroll-behavior: smooth; }
  *, *::before, *::after { box-sizing: border-box; }

  ::selection { background: rgba(99,102,241,0.3); color: #e2e8f0; }

  pre[class*="language-"] { margin:0; border-radius:0; font-size:0.78rem; background: #0c0c0f !important; }
  code[class*="language-"] { font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace; }

  .modal-open { overflow:hidden; }

  /* Stack cards — selected state must POP */
  .stack-card .peer:checked ~ div {
    background: rgba(99, 102, 241, 0.12) !important;
    border-color: rgba(129, 140, 248, 0.5) !important;
    box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.3), 0 4px 20px rgba(99, 102, 241, 0.15) !important;
  }
  .stack-card.db-card .peer:checked ~ div {
    background: rgba(52, 211, 153, 0.10) !important;
    border-color: rgba(52, 211, 153, 0.5) !important;
    box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.25), 0 4px 20px rgba(52, 211, 153, 0.12) !important;
  }
  .stack-card .peer:not(:checked) ~ div {
    opacity: 0.55;
  }
  .stack-card .peer:not(:checked) ~ div:hover {
    opacity: 0.8;
  }
  .stack-card .check-mark { display: none; }
  .stack-card .peer:checked ~ div .check-mark { display: flex; }

  /* Glass card effect */
  .glass { background: rgba(17,17,20,0.7); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.05); }

  /* Subtle noise texture */
  body::before {
    content: ''; position: fixed; inset: 0; z-index: -1; opacity: 0.03;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #2e2e36; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #3f3f46; }

  /* Textarea glow */
  textarea:focus { box-shadow: 0 0 0 2px rgba(99,102,241,0.2), 0 0 24px rgba(99,102,241,0.06); }

  /* Button press */
  .btn-press:active { transform: scale(0.97); }

  /* Gradient text */
  .grad-text { background: linear-gradient(135deg, #818cf8, #34d399); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }

  /* Generation mood — subtle only */
  .btn-generating {
    box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.25), 0 4px 16px rgba(99, 102, 241, 0.2);
  }

  .scroll-progress-wrap {
    position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 60;
    background: rgba(255,255,255,0.04);
  }
  .scroll-progress-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #818cf8, #6366f1, #34d399);
    box-shadow: 0 0 12px rgba(99,102,241,0.45);
    transition: width 120ms linear;
  }

  .reveal {
    opacity: 0;
    transform: translateY(18px) scale(0.99);
    transition: opacity 700ms cubic-bezier(0.2, 0.65, 0.2, 1), transform 700ms cubic-bezier(0.2, 0.65, 0.2, 1);
  }
  .reveal.visible {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

</style>
</head>
<body class="h-full bg-surface text-zinc-300 font-sans dark">
<div class="scroll-progress-wrap"><div id="scroll-progress" class="scroll-progress-bar"></div></div>

<div class="min-h-full flex flex-col">

  <!-- ═══ Header ═══ -->
  <header class="border-b border-white/[0.04] bg-surface/80 backdrop-blur-xl sticky top-0 z-40">
    <div class="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-mint flex items-center justify-center">
          <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <div>
          <h1 class="text-base font-semibold text-zinc-100 tracking-tight">AppSpec</h1>
          <p class="text-[11px] text-zinc-500 leading-tight">The Document Model for AI Code Generation</p>
        </div>
      </div>
      <a href="https://github.com/mongodb/appspec" target="_blank" class="text-zinc-500 hover:text-zinc-300 transition-colors">
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
      </a>
    </div>
  </header>

  <main class="flex-1 max-w-4xl mx-auto w-full px-6 py-8 space-y-6">

    <!-- ═══ Hero / Value Prop ═══ -->
    <section id="hero-section" class="animate-fade-in reveal visible">
      <!-- Collapsed bar (hidden initially, shown after generate) -->
      <div id="hero-collapsed" class="hidden cursor-pointer" onclick="toggleHero()">
        <div class="glass rounded-xl px-4 py-2.5 flex items-center justify-between hover:border-white/[0.08] transition-all duration-300 group">
          <div class="flex items-center gap-2.5">
            <div class="w-5 h-5 rounded bg-gradient-to-br from-accent/30 to-mint/30 flex items-center justify-center shrink-0">
              <svg class="w-3 h-3 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            </div>
            <span class="text-xs text-zinc-400">The <span class="text-zinc-300 font-medium">Document Model</span> for enterprise-safe AI code gen</span>
          </div>
          <div class="flex items-center gap-1.5 text-[10px] text-zinc-600 group-hover:text-zinc-400 transition-colors">
            <span>What is AppSpec?</span>
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          </div>
        </div>
      </div>

      <!-- Full hero (shown initially) -->
      <div id="hero-full" class="glass rounded-2xl p-8 relative overflow-hidden transition-all duration-500">
        <div class="absolute -top-24 -right-24 w-56 h-56 bg-accent/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="absolute -bottom-16 -left-16 w-40 h-40 bg-mint/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="relative">
          <h2 class="text-2xl font-bold text-zinc-100 tracking-tight">The <span class="grad-text">Document Model</span> that makes AI code gen enterprise-safe</h2>
          <p class="text-sm text-zinc-400 mt-3 max-w-2xl leading-relaxed">
            AI is great at creativity. It's terrible at consistency. AppSpec solves this by separating
            <em>what to build</em> (AI-generated JSON spec) from <em>how to build it</em> (deterministic templates).
            Language agnostic. Database agnostic. Every generated app compiles, passes validation,
            and follows your organization's security patterns &mdash; because templates enforce them, not luck.
          </p>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-8">
            <div class="p-4 rounded-xl bg-white/[0.03] border border-white/[0.05] hover:bg-white/[0.05] transition-colors group">
              <div class="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-300">
                <svg class="w-4 h-4 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
              </div>
              <h3 class="text-sm font-medium text-zinc-200">AI for Creativity</h3>
              <p class="text-xs text-zinc-500 mt-1.5 leading-relaxed">The LLM designs your app's data model, relationships, and endpoints as a validated JSON document. No code, no hallucinations.</p>
            </div>
            <div class="p-4 rounded-xl bg-white/[0.03] border border-white/[0.05] hover:bg-white/[0.05] transition-colors group">
              <div class="w-8 h-8 rounded-lg bg-mint/10 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-300">
                <svg class="w-4 h-4 text-mint" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
              </div>
              <h3 class="text-sm font-medium text-zinc-200">Templates for Safety</h3>
              <p class="text-xs text-zinc-500 mt-1.5 leading-relaxed">Deterministic Jinja2 templates enforce pinned dependency versions, auth patterns, Docker configs, and security best practices.</p>
            </div>
            <div class="p-4 rounded-xl bg-white/[0.03] border border-white/[0.05] hover:bg-white/[0.05] transition-colors group">
              <div class="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-300">
                <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
              </div>
              <h3 class="text-sm font-medium text-zinc-200">Stack Agnostic</h3>
              <p class="text-xs text-zinc-500 mt-1.5 leading-relaxed">Same spec targets Python or TypeScript, MongoDB or PostgreSQL. Switch stacks without rewriting your app definition.</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ Prompt ═══ -->
    <section id="prompt-section" class="glass rounded-2xl p-6 animate-fade-up reveal visible transition-opacity duration-300" style="animation-delay: 0.1s">
      <label for="prompt" class="block text-xs font-semibold text-zinc-500 uppercase tracking-widest mb-3">Describe your app</label>
      <textarea id="prompt" rows="2" placeholder="A veterinary clinic to manage pet owners, patients, and appointments..."
        class="w-full rounded-xl bg-surface-200/80 border border-white/[0.06] px-4 py-3.5 text-sm text-zinc-200 placeholder-zinc-600 focus:border-accent/40 outline-none resize-none transition-all duration-300"></textarea>
      <div class="mt-3 flex flex-wrap gap-2" id="idea-chips">
        <span class="text-[10px] text-zinc-600 self-center mr-1">Try:</span>
      </div>
    </section>

    <!-- ═══ Stack Builder ═══ -->
    <section class="animate-fade-up reveal visible relative overflow-hidden" style="animation-delay: 0.15s">
      <div class="grid grid-cols-2 gap-3">

        <!-- Language column -->
        <div class="space-y-2">
          <div class="text-[10px] font-bold text-zinc-600 uppercase tracking-[0.2em] px-1 mb-1">Language</div>

          <label class="stack-card group cursor-pointer block">
            <input type="radio" name="stack" value="python-fastapi" checked class="hidden peer">
            <div class="glass rounded-xl p-4 border border-white/[0.06] transition-all duration-300 relative">
              <div class="check-mark absolute top-3 right-3 w-5 h-5 rounded-full bg-accent items-center justify-center">
                <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
              </div>
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-white/[0.06] flex items-center justify-center shrink-0">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/python/python-original.svg" alt="Python" class="w-7 h-7">
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-bold text-zinc-100">Python</div>
                  <div class="text-[11px] text-zinc-500">FastAPI + Pydantic + async</div>
                </div>
              </div>
            </div>
          </label>

          <label class="stack-card group cursor-pointer block">
            <input type="radio" name="stack" value="typescript-express" class="hidden peer">
            <div class="glass rounded-xl p-4 border border-white/[0.06] transition-all duration-300 relative">
              <div class="check-mark absolute top-3 right-3 w-5 h-5 rounded-full bg-accent items-center justify-center">
                <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
              </div>
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-white/[0.06] flex items-center justify-center shrink-0">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/typescript/typescript-original.svg" alt="TypeScript" class="w-7 h-7 rounded">
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-bold text-zinc-100">TypeScript</div>
                  <div class="text-[11px] text-zinc-500">Express + strict types</div>
                </div>
              </div>
            </div>
          </label>
        </div>

        <!-- Database column -->
        <div class="space-y-2">
          <div class="text-[10px] font-bold text-zinc-600 uppercase tracking-[0.2em] px-1 mb-1">Database</div>

          <label class="stack-card db-card group cursor-pointer block">
            <input type="radio" name="engine" value="mongodb" checked class="hidden peer">
            <div class="glass rounded-xl p-4 border border-white/[0.06] transition-all duration-300 relative">
              <div class="check-mark absolute top-3 right-3 w-5 h-5 rounded-full bg-mint items-center justify-center">
                <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
              </div>
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-white/[0.06] flex items-center justify-center shrink-0">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/mongodb/mongodb-original.svg" alt="MongoDB" class="w-7 h-7">
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-bold text-zinc-100">MongoDB</div>
                  <div class="text-[11px] text-zinc-500">Document model &middot; flexible schema</div>
                </div>
              </div>
            </div>
          </label>

          <label class="stack-card db-card group cursor-pointer block">
            <input type="radio" name="engine" value="postgresql" class="hidden peer">
            <div class="glass rounded-xl p-4 border border-white/[0.06] transition-all duration-300 relative">
              <div class="check-mark absolute top-3 right-3 w-5 h-5 rounded-full bg-mint items-center justify-center">
                <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
              </div>
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-white/[0.06] flex items-center justify-center shrink-0">
                  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/postgresql/postgresql-original.svg" alt="PostgreSQL" class="w-7 h-7">
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-bold text-zinc-100">PostgreSQL</div>
                  <div class="text-[11px] text-zinc-500">Relational &middot; SQL &middot; ACID</div>
                </div>
              </div>
            </div>
          </label>
        </div>

      </div>

      <!-- ─ Generate bar ─ -->
      <div class="mt-4 flex items-center gap-3">
        <div id="recipe-bar" class="flex-1 glass rounded-xl px-4 py-3 flex items-center gap-3 overflow-hidden">
          <div class="flex items-center gap-2 text-xs">
            <span class="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-glow-pulse shrink-0"></span>
            <span id="recipe-lang" class="text-zinc-300 font-medium">Python + FastAPI</span>
            <svg class="w-3 h-3 text-zinc-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
            <span class="text-[10px] text-zinc-500 font-mono">AppSpec JSON</span>
            <svg class="w-3 h-3 text-zinc-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
            <span id="recipe-db" class="text-zinc-300 font-medium">MongoDB</span>
          </div>
        </div>
        <button id="generate-btn" onclick="startGeneration()"
          class="btn-press relative group bg-gradient-to-r from-accent to-indigo-500 hover:from-accent-dim hover:to-indigo-600 text-white text-sm font-semibold px-7 py-3 rounded-xl transition-all duration-300 shadow-lg shadow-accent/20 hover:shadow-accent/30 disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none shrink-0">
          <span id="btn-text" class="relative z-10">Generate</span>
          <div class="absolute inset-0 rounded-xl bg-gradient-to-r from-accent-bright to-indigo-400 opacity-0 group-hover:opacity-20 transition-opacity duration-300"></div>
        </button>
      </div>
    </section>

    <!-- ═══ Generation Mood Bar ═══ -->
    <section id="generation-stage" class="hidden glass rounded-xl px-4 py-3 animate-fade-up reveal">
      <div class="flex items-center justify-between gap-3 mb-2">
        <div class="text-xs font-medium text-zinc-300" id="gen-stage-text">Warming up the AI engine...</div>
        <div class="text-[10px] text-zinc-500 font-mono tabular-nums" id="gen-stage-percent">0%</div>
      </div>
      <div class="h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
        <div id="gen-progress" class="h-full rounded-full bg-gradient-to-r from-accent to-mint transition-all duration-500 ease-out" style="width: 0%"></div>
      </div>
    </section>

    <!-- ═══ Pipeline ═══ -->
    <section id="pipeline-section" class="hidden space-y-3 reveal">
      <h2 class="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Pipeline</h2>
      <div id="pipeline-steps" class="space-y-2"></div>
    </section>

    <!-- ═══ Results ═══ -->
    <section id="actions-section" class="hidden animate-fade-up reveal">
      <div class="glass rounded-2xl p-5 space-y-4">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-mint/15 flex items-center justify-center shrink-0">
            <svg class="w-4 h-4 text-mint" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>
          </div>
          <div>
            <div class="text-sm font-bold text-zinc-100">Your app is ready</div>
            <div id="file-count-label" class="text-[11px] text-zinc-500">0 files generated</div>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-2">
          <button onclick="openSpecModal()"
            class="btn-press group rounded-xl border border-white/[0.06] bg-white/[0.03] hover:bg-accent/10 hover:border-accent/30 p-3.5 text-left transition-all duration-200">
            <div class="flex items-center gap-2 mb-1.5">
              <span class="text-[10px] font-bold text-accent-bright bg-accent/15 w-5 h-5 rounded-full flex items-center justify-center shrink-0">1</span>
              <span class="text-xs font-semibold text-zinc-200 group-hover:text-accent-bright transition-colors">View AppSpec</span>
            </div>
            <div class="text-[10px] text-zinc-500 leading-relaxed">Inspect the JSON document that defines your entire app</div>
          </button>

          <button onclick="openPreview()"
            class="btn-press group rounded-xl border border-white/[0.06] bg-white/[0.03] hover:bg-accent/10 hover:border-accent/30 p-3.5 text-left transition-all duration-200">
            <div class="flex items-center gap-2 mb-1.5">
              <span class="text-[10px] font-bold text-accent-bright bg-accent/15 w-5 h-5 rounded-full flex items-center justify-center shrink-0">2</span>
              <span class="text-xs font-semibold text-zinc-200 group-hover:text-accent-bright transition-colors">Preview App</span>
            </div>
            <div class="text-[10px] text-zinc-500 leading-relaxed">Live interactive preview with sample data in your browser</div>
          </button>

          <a id="download-btn" href="#"
            class="btn-press group rounded-xl border border-white/[0.06] bg-white/[0.03] hover:bg-mint/10 hover:border-mint/30 p-3.5 text-left transition-all duration-200 block">
            <div class="flex items-center gap-2 mb-1.5">
              <span class="text-[10px] font-bold text-mint bg-mint/15 w-5 h-5 rounded-full flex items-center justify-center shrink-0">3</span>
              <span class="text-xs font-semibold text-zinc-200 group-hover:text-mint transition-colors">Download .zip</span>
            </div>
            <div class="text-[10px] text-zinc-500 leading-relaxed">Get the complete project &mdash; <span class="font-mono">docker compose up</span> and go</div>
          </a>
        </div>
      </div>
    </section>

    <!-- ═══ History ═══ -->
    <section id="history-section" class="animate-fade-up reveal visible" style="animation-delay: 0.2s">
      <div class="glass rounded-2xl overflow-hidden">
        <button onclick="document.getElementById('history-body').classList.toggle('hidden');this.querySelector('.chevron').classList.toggle('rotate-180');loadHistory()" class="w-full flex items-center justify-between px-6 py-4 text-left group">
          <div class="flex items-center gap-3">
            <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-accent/15 to-mint/15 flex items-center justify-center shrink-0">
              <svg class="w-3.5 h-3.5 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-zinc-200">History</span>
              <span id="history-count" class="text-[10px] text-zinc-600 font-mono"></span>
            </div>
          </div>
          <svg class="chevron w-4 h-4 text-zinc-500 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>

        <div id="history-body" class="hidden border-t border-white/[0.04]">
          <div id="history-list" class="p-4 space-y-2">
            <div class="text-center py-6 text-xs text-zinc-600">Loading...</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ About / FAQ ═══ -->
    <section class="animate-fade-up reveal visible" style="animation-delay: 0.25s">
      <div class="glass rounded-2xl overflow-hidden">
        <button onclick="document.getElementById('about-body').classList.toggle('hidden');this.querySelector('.chevron').classList.toggle('rotate-180')" class="w-full flex items-center justify-between px-6 py-4 text-left group">
          <div class="flex items-center gap-3">
            <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-accent/15 to-mint/15 flex items-center justify-center shrink-0">
              <svg class="w-3.5 h-3.5 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
            <span class="text-sm font-semibold text-zinc-200">About AppSpec</span>
          </div>
          <svg class="chevron w-4 h-4 text-zinc-500 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>

        <div id="about-body" class="hidden border-t border-white/[0.04]">
          <!-- Thesis -->
          <div class="px-6 pt-5 pb-2">
            <p class="text-sm text-zinc-300 leading-relaxed">
              <strong class="grad-text">Thesis:</strong> The Document Model is the missing piece that makes AI code generation enterprise-safe.
              Today's vibe-coding tools let AI write code directly &mdash; fast, creative, and dangerously inconsistent.
              AppSpec introduces a <em>structured contract</em> between AI and your codebase:
            </p>
          </div>

          <!-- Two-phase model -->
          <div class="px-6 pb-4">
            <div class="grid grid-cols-2 gap-3 mt-3">
              <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-3">
                <div class="text-[10px] font-bold text-accent-bright uppercase tracking-widest mb-1">AI = Creativity</div>
                <p class="text-xs text-zinc-400 leading-relaxed">The LLM designs your app as a validated JSON document &mdash; entities, relationships, auth, endpoints. It never writes a line of code.</p>
              </div>
              <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-3">
                <div class="text-[10px] font-bold text-mint uppercase tracking-widest mb-1">Templates = Control</div>
                <p class="text-xs text-zinc-400 leading-relaxed">Deterministic Jinja2 templates enforce your org's dependency versions, security patterns, Docker configs, and coding standards. Same spec &rarr; same output.</p>
              </div>
            </div>
            <p class="text-xs text-zinc-500 mt-3 leading-relaxed">
              Language agnostic. Database agnostic. The spec is the source of truth &mdash; not the generated code.
              Version-control the spec, diff it, review it, regenerate against new templates when standards evolve.
            </p>
          </div>

          <!-- FAQ -->
          <div class="px-6 pb-5 space-y-3">
            <div class="text-[10px] font-bold text-zinc-600 uppercase tracking-[0.2em]">FAQ</div>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                Why not just let AI write the code directly?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                Because AI-generated code is non-deterministic. Two prompts for the same app produce different dependency versions,
                different auth patterns, different error handling. In an enterprise, you need <strong>consistency</strong>:
                every service uses the same bcrypt version, the same JWT flow, the same Docker base image.
                Templates guarantee this. AI picks the <em>what</em>; your engineering team controls the <em>how</em>.
              </p>
            </details>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                Why is a JSON Document the right shape for this?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                JSON is the native output format of every major LLM. It's also the native document format of MongoDB,
                and the natural wire format for REST APIs. By choosing a JSON document as the spec format,
                AppSpec sits naturally at the intersection of AI (generation), storage (document database),
                and deployment (API contracts). The same spec targets Python + MongoDB, TypeScript + PostgreSQL,
                or any future stack &mdash; because the spec <em>is</em> the abstraction layer.
              </p>
            </details>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                How does this relate to SKILL.md / Agent Skills / MCP?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                They're complementary layers. A <strong>SKILL.md</strong> teaches an AI agent <em>how to think</em>
                (e.g. MongoDB schema design rules, ESR indexing, embed-vs-reference heuristics).
                <strong>AppSpec</strong> encodes <em>what to build</em> as a validated, deterministic contract.
                Skills improve the AI's creative output; AppSpec's validation pipeline catches anything
                the AI misses; templates enforce everything the enterprise requires. Three layers, zero gaps.
              </p>
            </details>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                What does "enterprise-safe" actually mean here?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                It means the generated code is <strong>auditable</strong> (spec is diffable and version-controlled),
                <strong>consistent</strong> (templates pin dependency versions and enforce auth/RBAC patterns),
                <strong>reproducible</strong> (same spec &rarr; same output, every time), and
                <strong>evolvable</strong> (update the templates when security standards change, regenerate all services).
                The AI never touches your production patterns &mdash; it only proposes a data model.
              </p>
            </details>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                What stacks and databases are supported?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                <strong>Python + FastAPI</strong> and <strong>TypeScript + Express</strong>,
                each with <strong>MongoDB</strong> or <strong>PostgreSQL</strong>. Every generated project
                includes a Dockerfile, docker-compose.yml, seed data, JWT auth with RBAC, ESR-optimized indexes,
                $jsonSchema validation, and a Tailwind CSS admin UI. Adding a new stack is pluggable &mdash;
                write a Jinja2 template set and register it as a target.
              </p>
            </details>

            <details class="group">
              <summary class="flex items-center gap-2 cursor-pointer text-xs font-medium text-zinc-300 hover:text-zinc-100 transition-colors py-1">
                <svg class="w-3 h-3 text-zinc-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                Can I edit the spec and regenerate?
              </summary>
              <p class="text-xs text-zinc-500 leading-relaxed pl-5 pb-1">
                Yes &mdash; that's the whole point. The spec is version-controlled, human-readable JSON.
                Change a field type, add an entity, toggle auth, switch databases &mdash; then regenerate.
                You get a new, consistent codebase that reflects exactly what the spec says.
                This is spec-driven development: the document is the contract, the code is derived.
              </p>
            </details>
          </div>
        </div>
      </div>
    </section>

  </main>

  <!-- ═══ Footer ═══ -->
  <footer class="border-t border-white/[0.04] mt-auto">
    <div class="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
      <span class="text-[11px] text-zinc-600">AppSpec &mdash; AI for creativity, templates for control</span>
      <div class="flex items-center gap-1 text-[11px] text-zinc-600">
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-mint animate-glow-pulse"></span>
        Ready
      </div>
    </div>
  </footer>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- ═══ File Browser Modal ═══                                            -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div id="file-modal" class="fixed inset-0 z-50 hidden">
  <div class="absolute inset-0 bg-black/70 backdrop-blur-md transition-opacity" onclick="closeFileModal()"></div>
  <div class="absolute inset-3 sm:inset-6 lg:inset-12 bg-surface-50 rounded-2xl shadow-2xl shadow-black/50 flex flex-col overflow-hidden z-10 border border-white/[0.04] animate-scale-in">
    <!-- Modal header -->
    <div class="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.04] bg-surface/80 backdrop-blur-sm shrink-0">
      <div class="flex items-center gap-3">
        <div class="w-6 h-6 rounded-md bg-accent/15 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
        </div>
        <span class="text-sm font-semibold text-zinc-200">Generated Files</span>
        <span id="modal-file-count" class="text-xs text-zinc-500"></span>
      </div>
      <button onclick="closeFileModal()" class="text-zinc-500 hover:text-zinc-200 transition-colors p-1.5 rounded-lg hover:bg-white/[0.04]">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
      </button>
    </div>
    <!-- Modal body -->
    <div class="flex flex-1 overflow-hidden">
      <div id="file-tree" class="w-64 border-r border-white/[0.04] bg-surface/50 overflow-y-auto p-2 text-xs shrink-0"></div>
      <div id="file-viewer" class="flex-1 overflow-auto flex flex-col bg-surface">
        <div class="flex-1 flex items-center justify-center text-zinc-600 text-sm select-none">
          <div class="text-center space-y-2">
            <svg class="w-8 h-8 mx-auto text-zinc-700" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
            <span>Select a file to view</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- ═══ AppSpec Viewer Modal ═══                                          -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div id="spec-modal" class="fixed inset-0 z-50 hidden">
  <div class="absolute inset-0 bg-black/70 backdrop-blur-md" onclick="closeSpecModal()"></div>
  <div class="absolute inset-3 sm:inset-y-6 sm:left-1/2 sm:-translate-x-1/2 sm:w-[min(92vw,960px)] bg-surface-50 rounded-2xl shadow-2xl shadow-black/50 flex flex-col overflow-hidden z-10 border border-white/[0.04] animate-scale-in" style="max-height: calc(100vh - 48px)">

    <!-- Modal header -->
    <div class="flex items-center justify-between px-5 py-3 border-b border-white/[0.04] bg-surface/80 backdrop-blur-sm shrink-0">
      <div class="flex items-center gap-3">
        <div class="w-6 h-6 rounded-md bg-gradient-to-br from-accent/20 to-mint/20 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-accent-bright" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <div>
          <div class="text-sm font-semibold text-zinc-200">AppSpec Document</div>
          <div class="text-[10px] text-zinc-500" id="spec-modal-subtitle">One JSON document. Your entire application.</div>
        </div>
      </div>
      <button onclick="closeSpecModal()" class="text-zinc-500 hover:text-zinc-200 transition-colors p-1.5 rounded-lg hover:bg-white/[0.04]">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
      </button>
    </div>

    <!-- Modal body: JSON left, summary right -->
    <div class="flex flex-1 overflow-hidden">
      <!-- JSON document — the star -->
      <div class="flex-1 overflow-auto flex flex-col">
        <div class="sticky top-0 bg-surface-100/90 backdrop-blur-sm text-zinc-500 text-[10px] px-4 py-2 font-mono flex items-center justify-between z-10 shrink-0 border-b border-white/[0.04]">
          <span class="text-zinc-400">appspec.json</span>
          <span class="text-zinc-600 tabular-nums" id="spec-json-lines"></span>
        </div>
        <div id="spec-json" class="flex-1 overflow-auto"></div>
      </div>

      <!-- Summary sidebar -->
      <div id="spec-sidebar" class="w-72 border-l border-white/[0.04] bg-surface/50 overflow-y-auto p-4 shrink-0 text-xs space-y-4"></div>
    </div>
  </div>
</div>

<script>
let currentSessionId = null;
let currentFiles = {};
let stepTimers = {};
let generationFailed = false;

function _esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

/* ── Icons ─────────────────────────────────────────────────────────── */

const ICONS = {
  running: `<span class="inline-flex w-5 h-5 items-center justify-center"><span class="w-2.5 h-2.5 rounded-full bg-accent-bright animate-dot-pulse"></span></span>`,
  done: `<svg class="w-5 h-5 text-mint" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>`,
  error: `<svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/></svg>`,
  warning: `<svg class="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M12 3l9.66 16.5H2.34L12 3z"/></svg>`,
  pending: `<span class="inline-flex w-5 h-5 items-center justify-center"><span class="w-2.5 h-2.5 rounded-full border border-zinc-700"></span></span>`,
};

const STEP_META = {
  schema:   { label: 'Schema Generation',   desc: 'LLM produces a structured JSON spec from your prompt' },
  validate: { label: 'Validation',           desc: 'Pydantic checks types, cross-references, naming, and safety' },
  seed:     { label: 'Seed Data',            desc: 'LLM generates realistic sample records for each entity' },
  codegen:  { label: 'Code Generation',      desc: 'Jinja2 templates produce deterministic source files' },
};

let generationTick = null;
const STEP_PROGRESS = { schema: 24, validate: 48, seed: 72, codegen: 92 };
const STEP_COPY = {
  schema: "Translating your idea into structured JSON",
  validate: "Verifying schema integrity and references",
  seed: "Synthesizing realistic sample records",
  codegen: "Rendering deterministic production files",
};

function setupScrollFx() {
  const bar = document.getElementById('scroll-progress');
  const onScroll = () => {
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const pct = Math.min(100, Math.max(0, (window.scrollY / max) * 100));
    if (bar) bar.style.width = `${pct}%`;
  };
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) entry.target.classList.add('visible');
    }
  }, { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
}

function updateRecipeBar() {
  const stack = document.querySelector('input[name="stack"]:checked')?.value || 'python-fastapi';
  const engine = document.querySelector('input[name="engine"]:checked')?.value || 'mongodb';
  const stackLabel = stack === 'typescript-express' ? 'TypeScript + Express' : 'Python + FastAPI';
  const dbLabel = engine === 'postgresql' ? 'PostgreSQL' : 'MongoDB';
  const langEl = document.getElementById('recipe-lang');
  const dbEl = document.getElementById('recipe-db');
  if (langEl) langEl.textContent = stackLabel;
  if (dbEl) dbEl.textContent = dbLabel;
  const bar = document.getElementById('recipe-bar');
  if (bar) {
    bar.style.borderColor = 'rgba(99,102,241,0.25)';
    bar.style.transition = 'border-color 0.6s ease';
    setTimeout(() => { bar.style.borderColor = ''; }, 600);
  }
}

function setGenerationMood(active) {
  const btn = document.getElementById('generate-btn');
  const btnText = document.getElementById('btn-text');
  const stage = document.getElementById('generation-stage');
  const prompt = document.getElementById('prompt');
  const promptSection = document.getElementById('prompt-section');
  const radios = document.querySelectorAll('.stack-card input[type="radio"]');
  const cards = document.querySelectorAll('.stack-card');
  const recipeBar = document.getElementById('recipe-bar');

  if (active) {
    btn.classList.add('btn-generating');
    stage.classList.remove('hidden');
    if (prompt) { prompt.disabled = true; prompt.classList.add('opacity-50', 'cursor-not-allowed'); }
    if (promptSection) promptSection.classList.add('opacity-60');
    radios.forEach(r => r.disabled = true);
    cards.forEach(c => { c.classList.add('pointer-events-none', 'opacity-60'); });
    if (recipeBar) recipeBar.classList.add('opacity-60');
    let frame = 0;
    generationTick = setInterval(() => {
      frame = (frame + 1) % 4;
      btnText.textContent = `Generating${'.'.repeat(frame)}`;
    }, 400);
    return;
  }

  btn.classList.remove('btn-generating');
  if (generationTick) { clearInterval(generationTick); generationTick = null; }
  btnText.textContent = 'Generate';
  if (prompt) { prompt.disabled = false; prompt.classList.remove('opacity-50', 'cursor-not-allowed'); }
  if (promptSection) promptSection.classList.remove('opacity-60');
  radios.forEach(r => r.disabled = false);
  cards.forEach(c => { c.classList.remove('pointer-events-none', 'opacity-60'); });
  if (recipeBar) recipeBar.classList.remove('opacity-60');
}

function setStage(step, status) {
  const progress = document.getElementById('gen-progress');
  const percent = document.getElementById('gen-stage-percent');
  const text = document.getElementById('gen-stage-text');
  if (!progress || !percent || !text) return;

  if (status === 'error') {
    progress.style.width = '100%';
    progress.classList.remove('from-accent', 'to-mint');
    progress.classList.add('bg-red-400');
    percent.textContent = '100%';
    text.textContent = 'Generation interrupted';
    return;
  }

  if (step && STEP_PROGRESS[step]) {
    progress.classList.remove('bg-red-400');
    progress.classList.add('from-accent', 'to-mint');
    const p = STEP_PROGRESS[step];
    progress.style.width = `${p}%`;
    percent.textContent = `${p}%`;
    text.textContent = STEP_COPY[step] || 'Generating app';
  }

  if (status === 'done') {
    progress.style.width = '100%';
    percent.textContent = '100%';
    text.textContent = 'Your app is ready';
  }
}

/* ── Pipeline rendering ────────────────────────────────────────────── */

function addStep(id, status, detail, extras) {
  const container = document.getElementById('pipeline-steps');
  let el = document.getElementById('step-' + id);
  const meta = STEP_META[id] || { label: id, desc: '' };

  if (!el) {
    el = document.createElement('div');
    el.id = 'step-' + id;
    el.style.opacity = '0'; el.style.transform = 'translateY(8px)';
    container.appendChild(el);
    stepTimers[id] = Date.now();
    requestAnimationFrame(() => {
      el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      el.style.opacity = '1'; el.style.transform = 'translateY(0)';
    });
  }

  const elapsed = ((Date.now() - stepTimers[id]) / 1000).toFixed(1);
  const isTerminal = ['done','error','warning'].includes(status);
  const timerHtml = isTerminal ? `<span class="text-[10px] text-zinc-600 font-mono tabular-nums">${elapsed}s</span>` : '';

  const colors = {
    running: { border: 'border-accent/20', bg: 'bg-accent/[0.04]' },
    done:    { border: 'border-mint/15', bg: 'bg-mint/[0.03]' },
    error:   { border: 'border-red-500/20', bg: 'bg-red-500/[0.04]' },
    warning: { border: 'border-amber-500/15', bg: 'bg-amber-500/[0.03]' },
    pending: { border: 'border-white/[0.04]', bg: 'bg-transparent' },
  };
  const c = colors[status] || colors.pending;

  let detailHtml = '';
  if (detail) {
    detailHtml = `<div class="text-xs text-zinc-400 mt-1.5">${_esc(detail)}</div>`;
  }

  let extrasHtml = '';
  if (extras && extras.length > 0) {
    extrasHtml = `<div class="mt-2.5 flex flex-wrap gap-1.5">${extras.map(e =>
      `<span class="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-white/[0.03] border border-white/[0.06] text-zinc-500">${_esc(e)}</span>`
    ).join('')}</div>`;
  }

  el.className = `rounded-xl border ${c.border} ${c.bg} p-4 transition-colors duration-500`;
  el.innerHTML = `
    <div class="flex items-start gap-3">
      <div class="mt-0.5 shrink-0">${ICONS[status] || ICONS.pending}</div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between gap-2">
          <div class="text-sm font-medium text-zinc-200">${_esc(meta.label)}</div>
          ${timerHtml}
        </div>
        <div class="text-[11px] text-zinc-600 mt-0.5">${_esc(meta.desc)}</div>
        ${detailHtml}
        ${extrasHtml}
      </div>
    </div>
  `;
}

/* ── File modal ────────────────────────────────────────────────────── */

function openFileModal() {
  const modal = document.getElementById('file-modal');
  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');
  renderFileTree(currentFiles);
  const first = Object.keys(currentFiles).sort()[0];
  if (first) showFile(first, document.querySelector('.file-btn'));
}

function closeFileModal() {
  document.getElementById('file-modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeFileModal(); closeSpecModal(); }
});

function renderFileTree(files) {
  const tree = document.getElementById('file-tree');
  const sorted = Object.keys(files).sort();
  const ext_colors = {
    py:'text-indigo-400', ts:'text-blue-400', js:'text-amber-400',
    sql:'text-purple-400', html:'text-orange-400', yml:'text-pink-400',
    yaml:'text-pink-400', json:'text-zinc-400', txt:'text-zinc-500',
    jinja:'text-teal-400', Dockerfile:'text-cyan-400'
  };

  tree.innerHTML = sorted.map(f => {
    const ext = f.split('.').pop();
    const c = ext_colors[ext] || 'text-zinc-500';
    const lines = (files[f].match(/\n/g)||[]).length + 1;
    return `<button class="file-btn w-full text-left px-3 py-2 rounded-lg flex items-center gap-2.5 hover:bg-white/[0.04] transition-all duration-200 group" onclick="showFile('${f}', this)">
      <span class="shrink-0 ${c} opacity-60 group-hover:opacity-100 transition-opacity"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg></span>
      <span class="truncate flex-1 text-zinc-400 group-hover:text-zinc-200 transition-colors">${f}</span>
      <span class="text-[10px] text-zinc-700 group-hover:text-zinc-500 shrink-0 tabular-nums transition-colors">${lines}L</span>
    </button>`;
  }).join('');
}

function langForFile(name) {
  const ext = name.split('.').pop();
  return {py:'python',ts:'typescript',js:'javascript',sql:'sql',json:'json',yml:'yaml',yaml:'yaml',html:'markup',sh:'bash',bash:'bash',Dockerfile:'docker'}[ext] || (name==='Dockerfile'?'docker':'plaintext');
}

function showFile(name, btnEl) {
  document.querySelectorAll('.file-btn').forEach(b => {
    b.classList.remove('bg-accent/10');
    b.querySelector('.truncate')?.classList.remove('text-accent-bright','font-semibold');
  });
  if (btnEl) {
    btnEl.classList.add('bg-accent/10');
    btnEl.querySelector('.truncate')?.classList.add('text-accent-bright','font-semibold');
  }

  const content = currentFiles[name] || '';
  const lang = langForFile(name);
  const escaped = content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const lines = content.split('\n').length;
  const viewer = document.getElementById('file-viewer');
  viewer.innerHTML = `
    <div class="sticky top-0 bg-surface-100/90 backdrop-blur-sm text-zinc-400 text-xs px-4 py-2.5 font-mono flex items-center justify-between z-10 shrink-0 border-b border-white/[0.04]">
      <span class="text-zinc-300">${name}</span>
      <span class="text-zinc-600 tabular-nums">${lines} lines</span>
    </div>
    <div class="flex-1 overflow-auto"><pre class="!bg-surface"><code class="language-${lang}">${escaped}</code></pre></div>
  `;
  Prism.highlightAllUnder(viewer);
}

/* ── AppSpec Viewer Modal ──────────────────────────────────────────── */

let _specData = null;

function openSpecModal() {
  document.getElementById('spec-modal').classList.remove('hidden');
  document.body.classList.add('modal-open');
  if (_specData) renderSpecSidebar(_specData);
}

function closeSpecModal() {
  document.getElementById('spec-modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function renderSpecSidebar(spec) {
  const sb = document.getElementById('spec-sidebar');
  if (!sb) return;
  const db = spec.database?.engine || 'mongodb';
  const entities = spec.entities || [];
  const endpoints = spec.endpoints || [];
  const totalFields = entities.reduce((a, e) => a + (e.fields || []).length, 0);

  const methodColors = { GET: 'text-emerald-400', POST: 'text-blue-400', PUT: 'text-amber-400', DELETE: 'text-red-400', PATCH: 'text-purple-400' };

  let entitiesHtml = entities.map(e => {
    const refs = (e.fields || []).filter(f => f.type === 'reference');
    const refHtml = refs.length ? `<div class="mt-1 flex flex-wrap gap-1">${refs.map(r => `<span class="text-[9px] text-amber-400/70">→ ${_esc(r.reference)}</span>`).join(' ')}</div>` : '';
    return `<div class="py-2 border-b border-white/[0.04] last:border-0">
      <div class="flex items-center justify-between">
        <span class="font-semibold text-zinc-200">${_esc(e.name)}</span>
        <span class="text-zinc-600 tabular-nums">${(e.fields || []).length}f</span>
      </div>
      <div class="text-[10px] text-zinc-500 font-mono mt-0.5">${_esc(e.collection)}</div>
      ${refHtml}
    </div>`;
  }).join('');

  let endpointsHtml = endpoints.map(ep => {
    const mc = methodColors[ep.method] || 'text-zinc-500';
    return `<div class="flex items-center gap-2 py-1">
      <span class="text-[9px] font-bold ${mc} w-8 shrink-0">${_esc(ep.method)}</span>
      <span class="text-[10px] text-zinc-400 font-mono truncate">${_esc(ep.path)}</span>
    </div>`;
  }).join('');

  sb.innerHTML = `
    <div>
      <div class="text-lg font-bold text-zinc-100">${_esc(spec.app_name) || '—'}</div>
      <div class="text-[10px] text-zinc-500 font-mono mt-0.5">${_esc(spec.slug) || '—'}</div>
      ${spec.description ? `<div class="text-[11px] text-zinc-400 mt-2 leading-relaxed">${_esc(spec.description)}</div>` : ''}
    </div>

    <div class="grid grid-cols-2 gap-2">
      <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-2.5">
        <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider">Database</div>
        <div class="text-sm font-semibold text-zinc-200 mt-1">${db === 'postgresql' ? 'PostgreSQL' : 'MongoDB'}</div>
      </div>
      <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-2.5">
        <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider">Auth</div>
        <div class="text-sm font-semibold mt-1">${spec.auth?.enabled ? '<span class="text-mint">On</span>' : '<span class="text-zinc-500">Off</span>'}</div>
        ${spec.auth?.roles ? `<div class="flex flex-wrap gap-1 mt-1">${spec.auth.roles.map(r => `<span class="text-[9px] px-1.5 py-0.5 rounded bg-mint/10 text-mint/80">${_esc(r)}</span>`).join('')}</div>` : ''}
      </div>
      <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-2.5">
        <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider">Entities</div>
        <div class="text-sm font-semibold text-zinc-200 mt-1">${entities.length}</div>
      </div>
      <div class="rounded-lg bg-white/[0.03] border border-white/[0.05] p-2.5">
        <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider">Fields</div>
        <div class="text-sm font-semibold text-zinc-200 mt-1">${totalFields}</div>
      </div>
    </div>

    <div>
      <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider mb-2">Entities</div>
      ${entitiesHtml}
    </div>

    <div>
      <div class="text-[9px] font-bold text-zinc-600 uppercase tracking-wider mb-2">Endpoints <span class="text-zinc-700">(${endpoints.length})</span></div>
      ${endpointsHtml}
    </div>
  `;
}

document.querySelectorAll('input[name="stack"], input[name="engine"]').forEach((el) => {
  el.addEventListener('change', updateRecipeBar);
});
updateRecipeBar();
setupScrollFx();

// ── Idea chips ────────────────────────────────────────────────
const IDEAS = [
  "Pet clinic for owners, patients & appointments",
  "Task manager with projects, teams & deadlines",
  "Restaurant reservation system with menus",
  "Fitness tracker with workouts & progress",
  "Library catalog with loans & members",
  "Invoice system for freelancers & clients",
  "Event planner with venues, tickets & RSVPs",
  "Recipe book with ingredients & ratings",
  "Job board with companies & applications",
  "Student grade book with courses & exams",
];
(function initIdeas() {
  const container = document.getElementById('idea-chips');
  if (!container) return;
  const shuffled = IDEAS.sort(() => Math.random() - 0.5).slice(0, 6);
  for (const idea of shuffled) {
    const btn = document.createElement('button');
    btn.textContent = idea;
    btn.className = 'px-2.5 py-1 rounded-lg text-[10px] text-zinc-400 bg-white/[0.04] border border-white/[0.06] hover:bg-accent/10 hover:border-accent/30 hover:text-zinc-200 transition-all duration-200 cursor-pointer';
    btn.onclick = () => {
      document.getElementById('prompt').value = idea;
      document.getElementById('prompt').focus();
      document.getElementById('prompt').dispatchEvent(new Event('input', {bubbles:true}));
    };
    container.appendChild(btn);
  }
})();

// ── Auto-load history on page init ────────────────────────────
loadHistory();

function collapseHero() {
  const full = document.getElementById('hero-full');
  const collapsed = document.getElementById('hero-collapsed');
  if (!full || !collapsed) return;
  full.style.maxHeight = full.scrollHeight + 'px';
  full.style.overflow = 'hidden';
  requestAnimationFrame(() => {
    full.style.transition = 'max-height 0.5s cubic-bezier(0.4,0,0.2,1), opacity 0.35s ease, padding 0.5s ease';
    full.style.maxHeight = '0';
    full.style.opacity = '0';
    full.style.paddingTop = '0';
    full.style.paddingBottom = '0';
  });
  setTimeout(() => {
    full.classList.add('hidden');
    collapsed.classList.remove('hidden');
    collapsed.style.opacity = '0';
    collapsed.style.transform = 'translateY(-4px)';
    requestAnimationFrame(() => {
      collapsed.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
      collapsed.style.opacity = '1';
      collapsed.style.transform = 'translateY(0)';
    });
  }, 500);
}

function expandHero() {
  const full = document.getElementById('hero-full');
  const collapsed = document.getElementById('hero-collapsed');
  if (!full || !collapsed) return;
  collapsed.classList.add('hidden');
  full.classList.remove('hidden');
  full.style.maxHeight = '0';
  full.style.opacity = '0';
  full.style.paddingTop = '';
  full.style.paddingBottom = '';
  requestAnimationFrame(() => {
    full.style.transition = 'max-height 0.5s cubic-bezier(0.4,0,0.2,1), opacity 0.4s ease';
    full.style.maxHeight = full.scrollHeight + 'px';
    full.style.opacity = '1';
  });
  setTimeout(() => { full.style.maxHeight = ''; full.style.overflow = ''; }, 550);
}

function toggleHero() {
  const full = document.getElementById('hero-full');
  if (full && full.classList.contains('hidden')) expandHero();
  else collapseHero();
}

/* ── Generation ────────────────────────────────────────────────────── */

function startGeneration() {
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) { document.getElementById('prompt').focus(); return; }
  const engine = document.querySelector('input[name="engine"]:checked').value;
  const stack = document.querySelector('input[name="stack"]:checked').value;

  const btn = document.getElementById('generate-btn');
  btn.disabled = true;
  setGenerationMood(true);

  collapseHero();

  document.getElementById('pipeline-section').classList.remove('hidden');
  document.getElementById('pipeline-section').classList.add('visible');
  document.getElementById('actions-section').classList.add('hidden');
  document.getElementById('generation-stage').classList.remove('hidden');
  document.getElementById('generation-stage').classList.add('visible');
  document.getElementById('pipeline-steps').innerHTML = '';
  currentFiles = {};
  currentSessionId = null;
  stepTimers = {};
  generationFailed = false;
  setStage('schema', 'running');

  function handleEvent(d) {
    if (d.step) {
      addStep(d.step, d.status || 'running', d.detail || '', d.extras || null);
      setStage(d.step, d.status || 'running');
      if ((d.status || 'running') === 'error' || d.step === 'error') generationFailed = true;
    }
    if (d.files) {
      currentFiles = d.files;
      currentSessionId = d.session_id;
      const count = Object.keys(d.files).length;
      document.getElementById('file-count-label').textContent = `${count} files ready to browse`;
      document.getElementById('modal-file-count').textContent = `${count} files`;
      document.getElementById('download-btn').href = '/download/' + d.session_id;
      document.getElementById('actions-section').classList.remove('hidden');
      document.getElementById('actions-section').classList.add('visible');
    }
    if (d.spec_json) {
      _specData = JSON.parse(d.spec_json);
      const pretty = JSON.stringify(_specData, null, 2);
      const escaped = pretty.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const lineCount = pretty.split('\n').length;
      document.getElementById('spec-json').innerHTML = `<pre class="!bg-surface"><code class="language-json">${escaped}</code></pre>`;
      Prism.highlightAllUnder(document.getElementById('spec-json'));
      const linesEl = document.getElementById('spec-json-lines');
      if (linesEl) linesEl.textContent = `${lineCount} lines`;
      document.getElementById('spec-modal-subtitle').textContent =
        `${_specData.app_name || 'App'} — ${(_specData.entities || []).length} entities, ${(_specData.endpoints || []).length} endpoints`;
      renderSpecSidebar(_specData);
    }
    if (d.done) {
      btn.disabled = false;
      setGenerationMood(false);
      if (!generationFailed) {
        setStage('codegen', 'done');
        loadHistory();
        setTimeout(() => {
          const actions = document.getElementById('actions-section');
          if (actions) actions.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 400);
      }
    }
  }

  fetch('/generate/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, engine, stack }),
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      generationFailed = true;
      addStep('error', 'error', err.error || 'Server error');
      btn.disabled = false;
      setGenerationMood(false);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try { handleEvent(JSON.parse(line.slice(6))); } catch(_e) {}
      }
    }
    if (buffer.startsWith('data: ')) {
      try { handleEvent(JSON.parse(buffer.slice(6))); } catch(_e) {}
    }
  }).catch(() => {
    btn.disabled = false;
    generationFailed = true;
    setGenerationMood(false);
    setStage('schema', 'error');
    addStep('error', 'error', 'Connection to server lost');
  });
}

/* ── History ───────────────────────────────────────────────────────── */

let _historyLoaded = false;

async function loadHistory() {
  try {
    const res = await fetch('/api/generations');
    const items = await res.json();
    const list = document.getElementById('history-list');
    const countEl = document.getElementById('history-count');

    if (items.length) {
      const pyCount = items.filter(i => i.stack !== 'typescript-express').length;
      const tsCount = items.filter(i => i.stack === 'typescript-express').length;
      const mdbCount = items.filter(i => i.engine !== 'postgresql').length;
      const pgCount = items.filter(i => i.engine === 'postgresql').length;
      if (countEl) countEl.innerHTML = `<span class="inline-flex items-center gap-2">`
        + `<span class="px-1.5 py-0.5 rounded bg-accent/15 text-accent-bright font-bold">${items.length}</span>`
        + (pyCount ? `<span class="px-1.5 py-0.5 rounded bg-indigo-400/10 text-indigo-300">Py ${pyCount}</span>` : '')
        + (tsCount ? `<span class="px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-300">TS ${tsCount}</span>` : '')
        + (mdbCount ? `<span class="px-1.5 py-0.5 rounded bg-mint/10 text-mint">MDB ${mdbCount}</span>` : '')
        + (pgCount ? `<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">PG ${pgCount}</span>` : '')
        + `</span>`;
      const body = document.getElementById('history-body');
      if (body && body.classList.contains('hidden') && !_historyLoaded) {
        body.classList.remove('hidden');
        const chevron = document.querySelector('#history-section .chevron');
        if (chevron) chevron.classList.add('rotate-180');
      }
    }

    if (!items.length) {
      if (countEl) countEl.textContent = '';
      list.innerHTML = `<div class="text-center py-6 text-xs text-zinc-600">No generations yet. Describe an app above and click Generate.</div>`;
      return;
    }
    list.innerHTML = items.map(item => {
      const date = item.created_at ? new Date(item.created_at) : null;
      const timeStr = date ? date.toLocaleDateString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
      const dbBadge = item.engine === 'postgresql'
        ? '<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 text-[9px] font-medium">PostgreSQL</span>'
        : '<span class="px-1.5 py-0.5 rounded bg-mint/10 text-mint text-[9px] font-medium">MongoDB</span>';
      const stackBadge = item.stack === 'typescript-express'
        ? '<span class="px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-300 text-[9px] font-medium">TypeScript</span>'
        : '<span class="px-1.5 py-0.5 rounded bg-indigo-400/10 text-indigo-300 text-[9px] font-medium">Python</span>';
      const sid = _esc(item.session_id);
      return `<div class="rounded-xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04] transition-colors p-3.5 group">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-sm font-semibold text-zinc-200 truncate">${_esc(item.app_name || item.slug)}</span>
              <span class="text-[10px] text-zinc-600 font-mono">${_esc(item.slug)}</span>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              ${stackBadge} ${dbBadge}
              <span class="text-[10px] text-zinc-500">${item.entity_count || 0} entities</span>
              <span class="text-[10px] text-zinc-600">&middot;</span>
              <span class="text-[10px] text-zinc-500">${item.endpoint_count || 0} endpoints</span>
              <span class="text-[10px] text-zinc-600">&middot;</span>
              <span class="text-[10px] text-zinc-500">${item.file_count || 0} files</span>
            </div>
            ${item.prompt ? `<div class="text-[10px] text-zinc-600 mt-1.5 truncate italic">"${_esc(item.prompt)}"</div>` : ''}
          </div>
          <div class="flex flex-col items-end gap-2 shrink-0">
            <span class="text-[10px] text-zinc-600 tabular-nums whitespace-nowrap">${timeStr}</span>
            <div class="flex items-center gap-1.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
              <button onclick="openPreviewFromHistory('${sid}')" class="text-[10px] text-indigo-300 hover:text-indigo-200 font-medium px-2 py-1 rounded-md bg-indigo-500/10 hover:bg-indigo-500/15 transition-colors">Preview</button>
              <button onclick="viewHistorySpec('${sid}')" class="text-[10px] text-accent-bright hover:text-accent font-medium px-2 py-1 rounded-md bg-accent/10 hover:bg-accent/15 transition-colors">Spec</button>
              <a href="/download/${sid}" class="text-[10px] text-mint hover:text-mint-dim font-medium px-2 py-1 rounded-md bg-mint/10 hover:bg-mint/15 transition-colors">Download</a>
            </div>
          </div>
        </div>
      </div>`;
    }).join('');
    _historyLoaded = true;
  } catch (e) {
    const list = document.getElementById('history-list');
    if (list) list.innerHTML = `<div class="text-center py-6 text-xs text-zinc-600">Could not load history (is MongoDB running?)</div>`;
  }
}

async function viewHistorySpec(sessionId) {
  try {
    const res = await fetch(`/api/generations/${sessionId}`);
    const data = await res.json();
    if (data.spec) {
      _specData = data.spec;
      const pretty = JSON.stringify(_specData, null, 2);
      const escaped = pretty.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const lineCount = pretty.split('\n').length;
      document.getElementById('spec-json').innerHTML = `<pre class="!bg-surface"><code class="language-json">${escaped}</code></pre>`;
      Prism.highlightAllUnder(document.getElementById('spec-json'));
      const linesEl = document.getElementById('spec-json-lines');
      if (linesEl) linesEl.textContent = `${lineCount} lines`;
      document.getElementById('spec-modal-subtitle').textContent =
        `${_specData.app_name || 'App'} — ${(_specData.entities || []).length} entities, ${(_specData.endpoints || []).length} endpoints`;
      renderSpecSidebar(_specData);
      openSpecModal();
    }
  } catch (e) { /* ignore */ }
}

/* ── Preview (opens in new tab) ────────────────────────────── */

function openPreview() {
  if (!currentSessionId) return;
  window.open('/preview/' + currentSessionId, '_blank');
}

function openPreviewFromHistory(sessionId) {
  window.open('/preview/' + sessionId, '_blank');
}
</script>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz():
    """Liveness probe — process is alive."""
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz():
    """Readiness probe — DB reachable and dependencies present."""
    checks = {"process": "ok"}
    try:
        db = await engine.get_scoped_db(APP_SLUG)
        await db.generations.find_one({}, {"_id": 1})
        checks["mongodb"] = "ok"
    except Exception as exc:
        checks["mongodb"] = f"error: {str(exc)[:80]}"
    try:
        import appspec  # noqa: F401
        checks["appspec"] = "ok"
    except ImportError:
        checks["appspec"] = "missing"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(checks, status_code=200 if ready else 503)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    nonce = getattr(request.state, "csp_nonce", "")
    return HTML.replace("<script>", f'<script nonce="{nonce}">').replace(
        "<script src=", f'<script nonce="{nonce}" src='
    )


from pydantic import BaseModel, Field as PydField


class _GenerateRequest(BaseModel):
    prompt: str = PydField(..., max_length=500)
    engine: str = PydField("mongodb")
    stack: str = PydField("python-fastapi")


@app.post("/generate/stream")
async def generate_stream(request: Request, body: _GenerateRequest):
    """SSE endpoint: runs the full AppSpec pipeline and streams progress events."""
    prompt = body.prompt
    engine_name = body.engine
    stack = body.stack
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        log.warning("Rate limit exceeded for %s", client_ip)
        return JSONResponse(
            {"error": "Rate limit exceeded. Try again in a minute."},
            status_code=429,
        )
    log.info("Generation started: prompt=%r engine=%s stack=%s ip=%s", prompt[:60], engine_name, stack, client_ip)

    if _gen_semaphore.locked() and _gen_semaphore._value == 0:
        return JSONResponse(
            {"error": f"Server busy — {_MAX_CONCURRENT} generations already running. Try again shortly."},
            status_code=503,
        )

    async def event_stream():
        session_id = str(uuid.uuid4())
        deadline = time.monotonic() + _GEN_TIMEOUT

        def send(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        def _check_timeout():
            if time.monotonic() > deadline:
                raise TimeoutError("Generation timed out")

        async with _gen_semaphore:
          try:
            # ── 1. Schema ────────────────────────────────────────────────
            yield send({"step": "schema", "status": "running"})

            try:
                from appspec.llm import create_spec, create_sample_data
            except ImportError:
                yield send({"step": "schema", "status": "error",
                             "detail": "LLM support not installed. Run: pip install appspec[llm]"})
                yield send({"done": True})
                return

            try:
                _check_timeout()
                spec = await create_spec(prompt, model=os.environ.get("APPSPEC_MODEL", ""))
            except Exception as exc:
                yield send({"step": "schema", "status": "error", "detail": str(exc)[:200]})
                yield send({"done": True})
                return

            if spec.database.engine.value != engine_name:
                from appspec.models import AppSpec as _AS
                data = spec.to_dict()
                data["database"] = {"engine": engine_name}
                spec = _AS.from_dict(data)

            entity_tags = [f"{e.name} ({len(e.fields)} fields)" for e in spec.entities]
            yield send({
                "step": "schema", "status": "done",
                "detail": f"{spec.app_name} — {len(spec.entities)} entities, {len(spec.endpoints)} endpoints, auth={'on' if spec.auth.enabled else 'off'}",
                "extras": entity_tags,
            })

            if await request.is_disconnected():
                log.info("Client disconnected after schema step (session %s)", session_id)
                return

            # ── 2. Validate ──────────────────────────────────────────────
            _check_timeout()
            yield send({"step": "validate", "status": "running"})

            from appspec.validation import validate
            result = await run_in_threadpool(validate, spec)

            if not result.valid:
                error_details = [f"{i.path}: {i.message}" for i in result.errors]
                yield send({"step": "validate", "status": "error",
                             "detail": f"{len(result.errors)} error(s)",
                             "extras": error_details[:8]})
                yield send({"done": True})
                return

            checks = []
            checks.append("Naming conventions: passed")
            checks.append("Cross-references: passed")
            checks.append("Safety audit: passed")
            if result.warnings:
                checks.append(f"{len(result.warnings)} warning(s)")
            yield send({
                "step": "validate", "status": "done",
                "detail": "All checks passed" + (f" with {len(result.warnings)} warning(s)" if result.warnings else ""),
                "extras": checks,
            })

            if await request.is_disconnected():
                log.info("Client disconnected after validate step (session %s)", session_id)
                return

            # ── 3. Seed data ─────────────────────────────────────────────
            _check_timeout()
            yield send({"step": "seed", "status": "running"})

            try:
                seed_data = await create_sample_data(spec, model=os.environ.get("APPSPEC_MODEL", ""))
                if seed_data:
                    from appspec.models import AppSpec as _AS2
                    d = spec.to_dict()
                    d["sample_data"] = seed_data
                    spec = _AS2.from_dict(d)
                    seed_data = _backfill_sample_refs(spec)
                    if seed_data:
                        d = spec.to_dict()
                        d["sample_data"] = seed_data
                        spec = _AS2.from_dict(d)
                    total = sum(len(v) for v in seed_data.values())
                    seed_tags = [f"{k}: {len(v)} records" for k, v in seed_data.items()]
                    yield send({
                        "step": "seed", "status": "done",
                        "detail": f"{total} records across {len(seed_data)} collections",
                        "extras": seed_tags,
                    })
                else:
                    yield send({"step": "seed", "status": "warning", "detail": "LLM returned empty seed data"})
            except Exception as exc:
                yield send({"step": "seed", "status": "warning", "detail": f"Skipped — {str(exc)[:80]}"})

            if await request.is_disconnected():
                log.info("Client disconnected after seed step (session %s)", session_id)
                return

            # ── 4. Code generation ───────────────────────────────────────
            _check_timeout()
            yield send({"step": "codegen", "status": "running"})

            try:
                from appspec.generation.composer import compose_full_project
                files = await run_in_threadpool(compose_full_project, spec, stack)
            except Exception as exc:
                yield send({"step": "codegen", "status": "error", "detail": str(exc)[:200]})
                yield send({"done": True})
                return

            file_tags = sorted(files.keys())
            yield send({
                "step": "codegen", "status": "done",
                "detail": f"{len(files)} files generated deterministically from templates",
                "extras": file_tags,
            })

            _sessions[session_id] = {"files": files, "spec": spec}

            # ── 5. Persist to MongoDB ─────────────────────────────────
            try:
                db = await engine.get_scoped_db(APP_SLUG)
                await db.generations.insert_one({
                    "session_id": session_id,
                    "prompt": prompt,
                    "engine": engine_name,
                    "stack": stack,
                    "spec": spec.to_dict(),
                    "files": files,
                    "app_name": spec.app_name,
                    "slug": spec.slug,
                    "entity_count": len(spec.entities),
                    "endpoint_count": len(spec.endpoints),
                    "file_count": len(files),
                    "created_at": datetime.now(timezone.utc),
                })
            except Exception:
                log.exception("Failed to persist generation %s to MongoDB", session_id)

            yield send({"files": files, "session_id": session_id, "spec_json": spec.to_json()})
            yield send({"done": True})

          except TimeoutError:
            log.warning("Generation timed out after %ds (session %s)", _GEN_TIMEOUT, session_id)
            yield send({"step": "error", "status": "error",
                         "detail": f"Generation timed out after {_GEN_TIMEOUT}s"})
            yield send({"done": True})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/download/{session_id}")
async def download(request: Request, session_id: str):
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err
    session = _sessions.get(session_id)

    if not session:
        try:
            db = await engine.get_scoped_db(APP_SLUG)
            doc = await db.generations.find_one({"session_id": session_id})
        except Exception:
            log.exception("MongoDB lookup failed for session %s", session_id)
            doc = None
        if not doc:
            return PlainTextResponse("Session not found", status_code=404)
        from appspec.models import AppSpec as _AS
        spec = _AS.from_dict(doc["spec"])
        if "files" in doc:
            files = doc["files"]
        else:
            from appspec.generation.composer import compose_full_project
            files = compose_full_project(spec, doc.get("stack", "python-fastapi"))
        session = {"files": files, "spec": spec}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp, content in sorted(session["files"].items()):
            zf.writestr(fp, content)
        zf.writestr("appspec.json", session["spec"].to_json())

    buf.seek(0)
    slug = session["spec"].slug
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


# ── Preview ──────────────────────────────────────────────────────────────────


@app.get("/preview/{session_id}")
async def preview(request: Request, session_id: str):
    """Serve a fully self-contained preview page — no server-side files needed."""
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err
    session = _sessions.get(session_id)

    if not session:
        try:
            db = await engine.get_scoped_db(APP_SLUG)
            doc = await db.generations.find_one({"session_id": session_id})
        except Exception:
            log.exception("MongoDB lookup failed for session %s", session_id)
            doc = None
        if not doc:
            return PlainTextResponse("Preview not found", status_code=404)
        from appspec.models import AppSpec as _AS
        spec = _AS.from_dict(doc["spec"])
        if "files" in doc:
            files = doc["files"]
        else:
            from appspec.generation.composer import compose_full_project
            files = compose_full_project(spec, doc.get("stack", "python-fastapi"))
        session = {"files": files, "spec": spec}

    raw_html = session["files"].get("static/index.html", "")
    if not raw_html:
        return PlainTextResponse("No UI generated for this stack", status_code=404)

    return HTMLResponse(_build_preview_page(raw_html, session_id, session["spec"]))


# ── History API ──────────────────────────────────────────────────────────────


@app.get("/api/generations")
async def list_generations(request: Request):
    """Return summaries of all past generations, newest first."""
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err
    try:
        db = await engine.get_scoped_db(APP_SLUG)
        cursor = db.generations.find(
            {},
            {
                "session_id": 1, "prompt": 1, "engine": 1, "stack": 1,
                "app_name": 1, "slug": 1, "entity_count": 1,
                "endpoint_count": 1, "file_count": 1, "created_at": 1,
                "_id": 0,
            },
        ).sort("created_at", -1).limit(50)
        results = await cursor.to_list(50)
        for doc in results:
            if isinstance(doc.get("created_at"), datetime):
                doc["created_at"] = doc["created_at"].isoformat()
            p = doc.get("prompt", "")
            if p and len(p) > 60:
                doc["prompt"] = p[:60] + "..."
        return results
    except Exception:
        log.exception("Failed to list generations")
        return JSONResponse([], status_code=503)


@app.get("/api/generations/{session_id}")
async def get_generation(request: Request, session_id: str):
    """Return the full spec JSON for a past generation."""
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err
    session = _sessions.get(session_id)
    if session:
        return {"spec": session["spec"].to_dict(), "session_id": session_id}

    try:
        db = await engine.get_scoped_db(APP_SLUG)
        doc = await db.generations.find_one({"session_id": session_id})
    except Exception:
        log.exception("MongoDB lookup failed for generation %s", session_id)
        doc = None
    if not doc:
        return PlainTextResponse("Generation not found", status_code=404)
    return {
        "spec": doc["spec"],
        "session_id": doc["session_id"],
        "stack": doc.get("stack", "python-fastapi"),
    }


if __name__ == "__main__":
    _model = os.environ.get("APPSPEC_MODEL", "gemini/gemini-2.5-flash")
    _mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    _db_name = os.environ.get("MDB_DB_NAME", "appspec_demo")
    _has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    _has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    _has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    _keys = []
    if _has_gemini: _keys.append("Gemini")
    if _has_openai: _keys.append("OpenAI")
    if _has_anthropic: _keys.append("Anthropic")

    _mongo_display = _mongo_uri
    if len(_mongo_display) > 34:
        _mongo_display = _mongo_display[:31] + "..."

    print(f"""
  ╔══════════════════════════════════════════════╗
  ║           AppSpec Demo                       ║
  ╠══════════════════════════════════════════════╣
  ║  URL     http://localhost:{str(_cli.port):<19s}  ║
  ║  Model   {_model:<34s}  ║
  ║  Keys    {', '.join(_keys) if _keys else 'None found (set in .env)':<34s}  ║
  ║  Mongo   {_mongo_display:<34s}  ║
  ║  DB      {_db_name:<34s}  ║
  ╚══════════════════════════════════════════════╝
""")

    if not _keys:
        print("  ⚠  No API keys detected. Set GEMINI_API_KEY, OPENAI_API_KEY,")
        print("     or ANTHROPIC_API_KEY in your .env file or environment.\n")

    uvicorn.run(app, host=_cli.host, port=_cli.port, log_level="warning")
