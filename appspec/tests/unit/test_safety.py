"""Tests for safety validation patterns — secrets and dangerous code detection."""

from appspec.models import AppSpec, DataField, EntitySpec, FieldType
from appspec.validation import validate


def _make_spec(**overrides) -> AppSpec:
    base = {
        "app_name": "Safe App",
        "slug": "safe-app",
        "entities": [
            EntitySpec(
                name="Item",
                collection="items",
                description="A safe item",
                fields=[DataField(name="title", type=FieldType.STRING)],
            )
        ],
    }
    base.update(overrides)
    return AppSpec(**base)


class TestSecretDetection:
    def test_detects_hardcoded_password(self):
        spec = _make_spec(
            metadata={"config": "password = 'hunter2'"}
        )
        result = validate(spec)
        assert any("secret" in i.message.lower() or "password" in i.message.lower()
                    for i in result.errors)

    def test_detects_hardcoded_api_key(self):
        spec = _make_spec(
            metadata={"config": "api_key = 'sk-abc123xyz'"}
        )
        result = validate(spec)
        assert any("secret" in i.message.lower() or "api" in i.message.lower()
                    for i in result.errors)

    def test_detects_mongodb_uri_with_creds(self):
        spec = _make_spec(
            metadata={"connection": "mongodb+srv://user:pass@cluster.mongodb.net/db"}
        )
        result = validate(spec)
        assert any("secret" in i.message.lower() for i in result.errors)

    def test_clean_spec_no_secrets(self):
        spec = _make_spec()
        result = validate(spec)
        assert not any(i.severity == "error" and "secret" in i.message.lower()
                       for i in result.issues)


class TestDangerousPatterns:
    def test_detects_eval(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Danger",
                    collection="dangers",
                    description="Uses eval() for dynamic code",
                    fields=[DataField(name="code", type=FieldType.STRING)],
                )
            ]
        )
        result = validate(spec)
        assert any("dangerous" in i.message.lower() or "eval" in i.message.lower()
                    for i in result.warnings)

    def test_detects_exec(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Runner",
                    collection="runners",
                    description="Runs exec() on input",
                    fields=[DataField(name="cmd", type=FieldType.STRING)],
                )
            ]
        )
        result = validate(spec)
        assert any("dangerous" in i.message.lower() or "exec" in i.message.lower()
                    for i in result.warnings)

    def test_detects_subprocess(self):
        spec = _make_spec(
            entities=[
                EntitySpec(
                    name="Shell",
                    collection="shells",
                    description="Uses subprocess to run commands",
                    fields=[DataField(name="cmd", type=FieldType.STRING)],
                )
            ]
        )
        result = validate(spec)
        assert any("dangerous" in i.message.lower() or "subprocess" in i.message.lower()
                    for i in result.warnings)
