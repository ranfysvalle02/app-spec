"""Tests for auth code generation across all targets."""

from appspec.generation.registry import generate
from appspec.models import (
    AppSpec,
    AuthSpec,
    CrudOperation,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
)


def _make_spec(auth_enabled: bool = True, auth_required: bool = False, roles: list[str] | None = None) -> AppSpec:
    return AppSpec(
        app_name="Auth Test",
        slug="auth-test",
        description="Testing auth codegen",
        auth=AuthSpec(
            enabled=auth_enabled,
            strategy="jwt",
            roles=roles or (["admin", "user"] if auth_enabled else []),
            default_role="user" if auth_enabled else "",
        ),
        entities=[
            EntitySpec(
                name="Widget",
                collection="widgets",
                description="A widget",
                fields=[
                    DataField(name="name", type=FieldType.STRING),
                ],
            )
        ],
        endpoints=[
            Endpoint(
                method=HttpMethod.GET, path="/widgets", entity="Widget",
                operation=CrudOperation.LIST,
                auth_required=auth_required,
                roles=["admin"] if auth_required else [],
            ),
            Endpoint(
                method=HttpMethod.POST, path="/widgets", entity="Widget",
                operation=CrudOperation.CREATE,
                auth_required=auth_required,
            ),
            Endpoint(
                method=HttpMethod.GET, path="/widgets/{id}", entity="Widget",
                operation=CrudOperation.GET,
            ),
            Endpoint(
                method=HttpMethod.PUT, path="/widgets/{id}", entity="Widget",
                operation=CrudOperation.UPDATE,
            ),
            Endpoint(
                method=HttpMethod.DELETE, path="/widgets/{id}", entity="Widget",
                operation=CrudOperation.DELETE,
            ),
        ],
    )


class TestPythonFastAPIAuth:
    def test_auth_enabled_generates_auth_file(self):
        files = generate(_make_spec(auth_enabled=True), "python-fastapi")
        assert "auth.py" in files
        assert "get_current_user" in files["auth.py"]
        assert "PyJWT" in files["requirements.txt"]
        assert "passlib" in files["requirements.txt"]

    def test_auth_disabled_no_auth_file(self):
        files = generate(_make_spec(auth_enabled=False), "python-fastapi")
        assert "auth.py" not in files
        assert "PyJWT" not in files["requirements.txt"]

    def test_auth_enabled_main_imports_auth(self):
        files = generate(_make_spec(auth_enabled=True), "python-fastapi")
        assert "from auth import auth_router" in files["main.py"]
        assert "auth_router" in files["main.py"]

    def test_auth_disabled_main_no_auth_import(self):
        files = generate(_make_spec(auth_enabled=False), "python-fastapi")
        assert "auth_router" not in files["main.py"]

    def test_protected_endpoints_use_depends(self):
        files = generate(_make_spec(auth_enabled=True, auth_required=True), "python-fastapi")
        assert "Depends(get_current_user)" in files["routes.py"] or "Depends(require_roles" in files["routes.py"]

    def test_unprotected_endpoints_no_depends(self):
        files = generate(_make_spec(auth_enabled=True, auth_required=False), "python-fastapi")
        assert "Depends(get_current_user)" not in files["routes.py"]

    def test_auth_roles_in_auth_file(self):
        files = generate(_make_spec(auth_enabled=True), "python-fastapi")
        assert "require_roles" in files["auth.py"]
        assert "admin" in files["auth.py"]

    def test_register_endpoint(self):
        files = generate(_make_spec(auth_enabled=True), "python-fastapi")
        assert "/register" in files["auth.py"]
        assert "/login" in files["auth.py"]


class TestTypeScriptExpressAuth:
    def test_auth_enabled_generates_auth_file(self):
        files = generate(_make_spec(auth_enabled=True), "typescript-express")
        assert "auth.ts" in files
        assert "authenticate" in files["auth.ts"]
        assert "jsonwebtoken" in files["package.json"]
        assert "bcryptjs" in files["package.json"]

    def test_auth_disabled_no_auth_file(self):
        files = generate(_make_spec(auth_enabled=False), "typescript-express")
        assert "auth.ts" not in files
        assert "jsonwebtoken" not in files["package.json"]

    def test_auth_enabled_server_imports_auth(self):
        files = generate(_make_spec(auth_enabled=True), "typescript-express")
        assert "authRouter" in files["server.ts"]

    def test_auth_disabled_server_no_auth_import(self):
        files = generate(_make_spec(auth_enabled=False), "typescript-express")
        assert "authRouter" not in files["server.ts"]

    def test_protected_endpoints_use_middleware(self):
        files = generate(_make_spec(auth_enabled=True, auth_required=True), "typescript-express")
        assert "authenticate" in files["routes.ts"]

    def test_unprotected_endpoints_no_middleware(self):
        files = generate(_make_spec(auth_enabled=True, auth_required=False), "typescript-express")
        routes = files["routes.ts"]
        lines = [line for line in routes.split("\n") if "authenticate," in line and "import" not in line]
        assert len(lines) == 0


class TestTailwindUIAuth:
    def test_auth_enabled_has_login_screen(self):
        files = generate(_make_spec(auth_enabled=True), "tailwind-ui")
        html = files["index.html"]
        assert "auth-screen" in html
        assert "auth-form" in html
        assert "Sign in" in html.lower() or "sign in" in html.lower()

    def test_auth_disabled_no_login_screen(self):
        files = generate(_make_spec(auth_enabled=False), "tailwind-ui")
        html = files["index.html"]
        assert "auth-screen" not in html

    def test_auth_sends_bearer_token(self):
        files = generate(_make_spec(auth_enabled=True), "tailwind-ui")
        html = files["index.html"]
        assert "Bearer" in html
        assert "Authorization" in html

    def test_auth_has_logout(self):
        files = generate(_make_spec(auth_enabled=True), "tailwind-ui")
        html = files["index.html"]
        assert "logout" in html.lower()
