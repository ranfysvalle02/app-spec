"""
AppSpec MongoDB Adapter
========================

Persist, query, and search AppSpec documents in MongoDB Atlas.
Requires the ``mongodb`` extra: ``pip install appspec[mongodb]``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from pymongo import AsyncMongoClient
except ImportError:
    AsyncMongoClient = None  # type: ignore[assignment,misc]


COLLECTION_NAME = "app_specs"
VERSION_COLLECTION = "app_spec_versions"


class AppSpecStore:
    """MongoDB persistence for AppSpec documents.

    Usage::

        store = AppSpecStore("mongodb+srv://...")
        await store.connect()
        await store.persist(spec)
        results = await store.search("payment processing")
        await store.close()
    """

    def __init__(self, uri: str, db_name: str = "appspec") -> None:
        if AsyncMongoClient is None:
            raise ImportError(
                "MongoDB support requires pymongo>=4.16. Install with: pip install appspec[mongodb]"
            )
        self._uri = uri
        self._db_name = db_name
        self._client: Any = None
        self._db: Any = None

    async def connect(self) -> None:
        self._client = AsyncMongoClient(self._uri)
        self._db = self._client[self._db_name]
        await self._ensure_indexes()

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def _ensure_indexes(self) -> None:
        coll = self._db[COLLECTION_NAME]
        await coll.create_index("slug", unique=True)
        await coll.create_index("updated_at")
        await coll.create_index(
            [("app_name", "text"), ("description", "text"), ("slug", "text")],
            name="text_search",
        )

        versions = self._db[VERSION_COLLECTION]
        await versions.create_index([("slug", 1), ("version", -1)])

    async def persist(self, spec: "AppSpec") -> str:  # noqa: F821
        """Upsert the spec document. Returns the document _id as string."""

        doc = spec.to_dict()
        now = datetime.now(timezone.utc)
        doc["updated_at"] = now

        result = await self._db[COLLECTION_NAME].find_one_and_update(
            {"slug": spec.slug},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
            return_document=True,
        )

        version_doc = {**doc, "version": now.isoformat(), "slug": spec.slug}
        await self._db[VERSION_COLLECTION].insert_one(version_doc)

        return str(result["_id"])

    async def get(self, slug: str, version: str = "latest") -> "AppSpec | None":  # noqa: F821
        """Retrieve a spec by slug."""
        from appspec.models import AppSpec

        if version == "latest":
            doc = await self._db[COLLECTION_NAME].find_one({"slug": slug})
        else:
            doc = await self._db[VERSION_COLLECTION].find_one(
                {"slug": slug, "version": version}
            )

        if not doc:
            return None

        doc.pop("_id", None)
        doc.pop("created_at", None)
        doc.pop("updated_at", None)
        doc.pop("version", None)
        return AppSpec.from_dict(doc)

    async def list_specs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List all stored specs (summary only)."""
        cursor = self._db[COLLECTION_NAME].find(
            {},
            {"slug": 1, "app_name": 1, "description": 1, "updated_at": 1, "_id": 0},
        ).sort("updated_at", -1).limit(limit)
        return await cursor.to_list(limit)

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search across all specs."""
        cursor = self._db[COLLECTION_NAME].find(
            {"$text": {"$search": query}},
            {"score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        results = await cursor.to_list(limit)
        for doc in results:
            doc["_id"] = str(doc["_id"])
        return results

    async def vector_search(
        self, query_embedding: list[float], limit: int = 5, index_name: str = "spec_vector_index"
    ) -> list[dict[str, Any]]:
        """Atlas Vector Search for semantic spec retrieval.

        Requires a vector search index on the ``app_specs`` collection
        with the field ``description_embedding``.
        """
        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "description_embedding",
                    "queryVector": query_embedding,
                    "numCandidates": limit * 10,
                    "limit": limit,
                }
            },
            {
                "$project": {
                    "slug": 1,
                    "app_name": 1,
                    "description": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        cursor = self._db[COLLECTION_NAME].aggregate(pipeline)
        results = await cursor.to_list(limit)
        for doc in results:
            doc["_id"] = str(doc["_id"])
        return results

    async def analytics(self) -> dict[str, Any]:
        """Aggregation pipeline: spec counts, entity distributions, etc."""
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_specs": {"$sum": 1},
                    "total_entities": {"$sum": {"$size": "$entities"}},
                    "total_endpoints": {"$sum": {"$size": {"$ifNull": ["$endpoints", []]}}},
                    "auth_enabled_count": {
                        "$sum": {"$cond": [{"$eq": ["$auth.enabled", True]}, 1, 0]}
                    },
                }
            }
        ]
        result = await self._db[COLLECTION_NAME].aggregate(pipeline).to_list(1)
        if result:
            stats = result[0]
            stats.pop("_id", None)
            return stats
        return {
            "total_specs": 0,
            "total_entities": 0,
            "total_endpoints": 0,
            "auth_enabled_count": 0,
        }

    async def audit(self) -> list[dict[str, Any]]:
        """Flag specs with potential governance issues.

        Returns a list of audit findings: auth disabled on write endpoints,
        missing descriptions, no endpoints, etc.
        """
        pipeline = [
            {
                "$project": {
                    "slug": 1,
                    "app_name": 1,
                    "auth_enabled": "$auth.enabled",
                    "entity_count": {"$size": "$entities"},
                    "endpoint_count": {"$size": {"$ifNull": ["$endpoints", []]}},
                    "has_description": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$description", ""]}}, 0]}, True, False]},
                    "write_endpoints": {
                        "$size": {
                            "$filter": {
                                "input": {"$ifNull": ["$endpoints", []]},
                                "cond": {"$in": ["$$this.method", ["POST", "PUT", "PATCH", "DELETE"]]}
                            }
                        }
                    },
                }
            }
        ]
        cursor = self._db[COLLECTION_NAME].aggregate(pipeline)
        all_specs = await cursor.to_list(500)

        findings: list[dict[str, Any]] = []
        for spec in all_specs:
            slug = spec.get("slug", "unknown")
            spec["_id"] = str(spec.get("_id", ""))

            if not spec.get("auth_enabled") and spec.get("write_endpoints", 0) > 0:
                findings.append({
                    "slug": slug,
                    "severity": "warning",
                    "issue": "Auth disabled with write endpoints",
                    "detail": f"{spec['write_endpoints']} write endpoint(s) without auth",
                })
            if not spec.get("has_description"):
                findings.append({
                    "slug": slug,
                    "severity": "info",
                    "issue": "Missing app description",
                })
            if spec.get("endpoint_count", 0) == 0:
                findings.append({
                    "slug": slug,
                    "severity": "warning",
                    "issue": "No endpoints defined",
                })
        return findings

    async def delete(self, slug: str) -> bool:
        """Delete a spec and its version history."""
        r1 = await self._db[COLLECTION_NAME].delete_one({"slug": slug})
        await self._db[VERSION_COLLECTION].delete_many({"slug": slug})
        return r1.deleted_count > 0
