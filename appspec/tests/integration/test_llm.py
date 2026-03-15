"""Tests for the LLM integration module.

Uses mocked LLM responses to test the full pipeline without API calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from appspec.models import AppSpec
from appspec.validation import validate


MOCK_SCHEMA_RESPONSE = json.dumps({
    "schema_version": "1.0",
    "app_name": "Vet Clinic",
    "slug": "vet-clinic",
    "description": "Veterinary clinic with patients and owners",
    "auth": {
        "enabled": True,
        "strategy": "jwt",
        "roles": ["vet", "admin"],
        "default_role": "vet",
    },
    "entities": [
        {
            "name": "Owner",
            "collection": "owners",
            "description": "A pet owner",
            "fields": [
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "email", "required": True, "is_unique": True},
                {"name": "phone", "type": "string", "required": False},
                {"name": "created_at", "type": "datetime", "required": True, "is_sortable": True},
            ],
        },
        {
            "name": "Patient",
            "collection": "patients",
            "description": "An animal patient",
            "fields": [
                {"name": "name", "type": "string", "required": True},
                {
                    "name": "species",
                    "type": "enum",
                    "enum_values": ["dog", "cat", "bird"],
                    "is_filterable": True,
                },
                {
                    "name": "owner_id",
                    "type": "reference",
                    "reference": "owners",
                    "required": True,
                    "is_filterable": True,
                },
                {"name": "weight_kg", "type": "float", "min_value": 0, "required": False},
                {"name": "created_at", "type": "datetime", "required": True, "is_sortable": True},
            ],
            "relationships": ["Owner"],
        },
    ],
    "endpoints": [
        {"method": "GET", "path": "/owners", "entity": "Owner", "operation": "list"},
        {"method": "GET", "path": "/owners/{id}", "entity": "Owner", "operation": "get"},
        {"method": "POST", "path": "/owners", "entity": "Owner", "operation": "create"},
        {"method": "GET", "path": "/patients", "entity": "Patient", "operation": "list",
         "filters": ["species", "owner_id"]},
        {"method": "POST", "path": "/patients", "entity": "Patient", "operation": "create"},
        {"method": "GET", "path": "/patients/{id}", "entity": "Patient", "operation": "get"},
        {"method": "PUT", "path": "/patients/{id}", "entity": "Patient", "operation": "update"},
        {"method": "DELETE", "path": "/patients/{id}", "entity": "Patient", "operation": "delete"},
    ],
    "sample_data": {},
})

MOCK_SEED_RESPONSE = json.dumps({
    "owners": [
        {"name": "Jane Smith", "email": "jane@example.com", "phone": "555-0100", "created_at": "2025-01-10T09:00:00Z"},
        {"name": "John Doe", "email": "john@example.com", "phone": "555-0101", "created_at": "2025-01-11T10:00:00Z"},
        {"name": "Maria Garcia", "email": "maria@example.com", "phone": "555-0102", "created_at": "2025-01-12T11:00:00Z"},
        {"name": "James Wilson", "email": "james@example.com", "phone": "555-0103", "created_at": "2025-01-13T12:00:00Z"},
        {"name": "Sarah Lee", "email": "sarah@example.com", "phone": "555-0104", "created_at": "2025-01-14T13:00:00Z"},
    ],
    "patients": [
        {"name": "Buddy", "species": "dog", "owner_id": "owner_1", "weight_kg": 25.0, "created_at": "2025-02-01T09:00:00Z"},
        {"name": "Whiskers", "species": "cat", "owner_id": "owner_2", "weight_kg": 4.5, "created_at": "2025-02-02T10:00:00Z"},
        {"name": "Tweety", "species": "bird", "owner_id": "owner_3", "weight_kg": 0.3, "created_at": "2025-02-03T11:00:00Z"},
        {"name": "Rex", "species": "dog", "owner_id": "owner_4", "weight_kg": 35.0, "created_at": "2025-02-04T12:00:00Z"},
        {"name": "Luna", "species": "cat", "owner_id": "owner_5", "weight_kg": 3.8, "created_at": "2025-02-05T13:00:00Z"},
    ],
})


def _mock_response(content: str):
    """Build a mock litellm response object."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class TestCreateSpec:
    """Tests for create_spec (schema generation, no seed data)."""

    @pytest.mark.asyncio
    async def test_create_spec_success(self):
        from appspec.llm.pipeline import create_spec

        mock_acompletion = AsyncMock(return_value=_mock_response(MOCK_SCHEMA_RESPONSE))

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = mock_acompletion
            spec = await create_spec("A vet clinic", model="test-model")

        assert isinstance(spec, AppSpec)
        assert spec.slug == "vet-clinic"
        assert len(spec.entities) == 2
        assert len(spec.endpoints) == 8
        assert spec.auth.enabled is True
        assert spec.sample_data == {}

        result = validate(spec)
        assert result.valid
        assert mock_acompletion.await_args.kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_create_spec_retries_on_bad_json(self):
        from appspec.llm.pipeline import create_spec

        bad_response = _mock_response('{"not": "valid appspec"}')
        good_response = _mock_response(MOCK_SCHEMA_RESPONSE)

        mock_acompletion = AsyncMock(side_effect=[bad_response, good_response])

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = mock_acompletion
            spec = await create_spec("A vet clinic", model="test-model")

        assert spec.slug == "vet-clinic"
        assert mock_acompletion.call_count == 2

    @pytest.mark.asyncio
    async def test_create_spec_fails_after_retries(self):
        from appspec.llm.pipeline import create_spec

        bad_response = _mock_response('{"garbage": true}')
        mock_acompletion = AsyncMock(return_value=bad_response)

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = mock_acompletion
            with pytest.raises(ValueError, match="Failed to parse"):
                await create_spec("bad prompt", model="test-model", max_retries=1)

    @pytest.mark.asyncio
    async def test_create_spec_empty_response(self):
        from appspec.llm.pipeline import create_spec

        empty_response = _mock_response("")
        good_response = _mock_response(MOCK_SCHEMA_RESPONSE)

        mock_acompletion = AsyncMock(side_effect=[empty_response, good_response])

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = mock_acompletion
            spec = await create_spec("A vet clinic", model="test-model")

        assert spec.slug == "vet-clinic"

    @pytest.mark.asyncio
    async def test_ensure_endpoints_fills_empty(self):
        """If LLM returns empty endpoints, _ensure_endpoints generates CRUD for all entities."""
        from appspec.llm.pipeline import create_spec

        no_endpoints = json.loads(MOCK_SCHEMA_RESPONSE)
        no_endpoints["endpoints"] = []
        mock = AsyncMock(return_value=_mock_response(json.dumps(no_endpoints)))

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = mock
            spec = await create_spec("A vet clinic", model="test-model")

        assert len(spec.endpoints) == 10  # 5 CRUD ops x 2 entities


class TestCreateSampleData:
    """Tests for create_sample_data (seed data generation)."""

    @pytest.mark.asyncio
    async def test_create_sample_data_success(self):
        from appspec.llm.pipeline import create_spec, create_sample_data

        schema_mock = AsyncMock(return_value=_mock_response(MOCK_SCHEMA_RESPONSE))
        seed_mock = AsyncMock(return_value=_mock_response(MOCK_SEED_RESPONSE))

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = schema_mock
            spec = await create_spec("A vet clinic", model="test-model")

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = seed_mock
            data = await create_sample_data(spec, model="test-model")

        assert "owners" in data
        assert "patients" in data
        assert len(data["owners"]) == 10
        assert len(data["patients"]) == 10
        assert data["owners"][0]["name"] == "Jane Smith"
        assert data["patients"][0]["name"] == "Buddy"
        assert seed_mock.await_args.kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_create_sample_data_fallback_when_keys_invalid(self):
        from appspec.llm.pipeline import create_spec, create_sample_data

        schema_mock = AsyncMock(return_value=_mock_response(MOCK_SCHEMA_RESPONSE))
        bad_seed_mock = AsyncMock(return_value=_mock_response(json.dumps({"wrong_key": [{"x": 1}]})))

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = schema_mock
            spec = await create_spec("A vet clinic", model="test-model")

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = bad_seed_mock
            data = await create_sample_data(spec, model="test-model", max_retries=0)

        assert "owners" in data
        assert "patients" in data
        assert len(data["owners"]) == 10
        assert len(data["patients"]) == 10
        assert "owner_id" not in data["patients"][0]
        assert "name" in data["owners"][0]


class TestEndToEnd:
    """Full pipeline: schema -> validate -> seed -> generate code."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, tmp_path):
        from appspec.llm.pipeline import create_spec, create_sample_data
        from appspec.generation.registry import generate
        from appspec.compiler import compile_to_folder

        schema_mock = AsyncMock(return_value=_mock_response(MOCK_SCHEMA_RESPONSE))
        seed_mock = AsyncMock(return_value=_mock_response(MOCK_SEED_RESPONSE))

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = schema_mock
            spec = await create_spec("A vet clinic", model="test-model")

        with patch("appspec.llm.pipeline.litellm") as mock_litellm:
            mock_litellm.acompletion = seed_mock
            seed_data = await create_sample_data(spec, model="test-model")

        data = spec.to_dict()
        data["sample_data"] = seed_data
        spec = AppSpec.from_dict(data)

        compile_to_folder(spec, tmp_path / "appspec")
        assert (tmp_path / "appspec" / "appspec.json").exists()

        py_files = generate(spec, "python-fastapi")
        assert "main.py" in py_files
        assert "routes.py" in py_files
        assert "docker-compose.yml" in py_files

        from appspec.generation.composer import compose_full_project
        composed = compose_full_project(spec, "python-fastapi")
        assert any(k.startswith("mongo-init/") for k in composed)

        mongo_files = generate(spec, "mongodb-artifacts")
        assert "seed.js" in mongo_files
        assert "mongo-init/03-seed.js" in mongo_files

        assert "Buddy" in mongo_files["seed.js"]
        assert "Jane Smith" in mongo_files["mongo-init/03-seed.js"]
