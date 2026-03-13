"""Tests for the MongoDB persistence module (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from appspec.models import AppSpec, DataField, EntitySpec, FieldType


def _make_spec() -> AppSpec:
    return AppSpec(
        app_name="Mongo Test",
        slug="mongo-test",
        entities=[
            EntitySpec(
                name="Item",
                collection="items",
                description="A test item",
                fields=[DataField(name="title", type=FieldType.STRING)],
            )
        ],
    )


class TestAppSpecStore:
    @pytest.mark.asyncio
    async def test_persist_upserts_document(self):
        from appspec.store.mongodb import AppSpecStore

        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()

        mock_collection.find_one_and_update = AsyncMock(return_value={
            "_id": "abc123", "slug": "mongo-test"
        })
        mock_collection.create_index = AsyncMock()

        mock_versions = MagicMock()
        mock_versions.insert_one = AsyncMock()
        mock_versions.create_index = AsyncMock()

        mock_db.__getitem__ = lambda self, name: mock_collection if name == "app_specs" else mock_versions

        with patch("appspec.store.mongodb.AsyncMongoClient", return_value=mock_client):
            store = AppSpecStore("mongodb://localhost:27017")
            store._client = mock_client
            store._db = mock_db

            doc_id = await store.persist(_make_spec())

        assert doc_id == "abc123"
        mock_collection.find_one_and_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_returns_spec(self):
        from appspec.store.mongodb import AppSpecStore

        spec = _make_spec()
        doc = spec.to_dict()
        doc["_id"] = "abc123"
        doc["created_at"] = "2025-01-01"
        doc["updated_at"] = "2025-01-02"

        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=doc)
        mock_collection.create_index = AsyncMock()

        mock_db = MagicMock()
        mock_db.__getitem__ = lambda self, name: mock_collection

        with patch("appspec.store.mongodb.AsyncMongoClient"):
            store = AppSpecStore("mongodb://localhost:27017")
            store._db = mock_db

            result = await store.get("mongo-test")

        assert result is not None
        assert result.slug == "mongo-test"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self):
        from appspec.store.mongodb import AppSpecStore

        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.create_index = AsyncMock()

        mock_db = MagicMock()
        mock_db.__getitem__ = lambda self, name: mock_collection

        with patch("appspec.store.mongodb.AsyncMongoClient"):
            store = AppSpecStore("mongodb://localhost:27017")
            store._db = mock_db

            result = await store.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_spec(self):
        from appspec.store.mongodb import AppSpecStore

        mock_collection = MagicMock()
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_collection.create_index = AsyncMock()

        mock_versions = MagicMock()
        mock_versions.delete_many = AsyncMock()
        mock_versions.create_index = AsyncMock()

        mock_db = MagicMock()
        mock_db.__getitem__ = lambda self, name: mock_collection if name == "app_specs" else mock_versions

        with patch("appspec.store.mongodb.AsyncMongoClient"):
            store = AppSpecStore("mongodb://localhost:27017")
            store._db = mock_db

            result = await store.delete("mongo-test")

        assert result is True

    @pytest.mark.asyncio
    async def test_analytics_returns_stats(self):
        from appspec.store.mongodb import AppSpecStore

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{
            "_id": None,
            "total_specs": 5,
            "total_entities": 15,
            "total_endpoints": 40,
            "auth_enabled_count": 3,
        }])

        mock_collection = MagicMock()
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)
        mock_collection.create_index = AsyncMock()

        mock_db = MagicMock()
        mock_db.__getitem__ = lambda self, name: mock_collection

        with patch("appspec.store.mongodb.AsyncMongoClient"):
            store = AppSpecStore("mongodb://localhost:27017")
            store._db = mock_db

            stats = await store.analytics()

        assert stats["total_specs"] == 5
        assert stats["total_entities"] == 15
