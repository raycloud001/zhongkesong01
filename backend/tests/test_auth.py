from datetime import datetime, timezone
from pathlib import Path
import subprocess

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.service import (
    require_admin,
    require_owner,
    hash_password,
)
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import create_app
from app.models import AdminUser, User
from app.auth.models import AuthSession


ORIGIN = "http://frontend.test"


@pytest.fixture()
def app_and_session(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", ORIGIN)
    monkeypatch.setenv("APP_ENV", "development")
    engine = build_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    router = APIRouter()

    @router.post("/owner-write")
    def owner_write(owner_id: str = Depends(require_owner)):
        return {"ownerId": owner_id}

    @router.get("/admin-only")
    def admin_only(admin_id: str = Depends(require_admin)):
        return {"adminId": admin_id}

    app = create_app(api_router=router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    yield app, factory
    engine.dispose()


def test_anonymous_identity_is_reused_and_only_hashes_are_stored(app_and_session):
    app, factory = app_and_session
    client = TestClient(app)

    created = client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN})
    assert created.status_code == 201
    identity = created.json()
    assert identity["ownerId"]
    assert identity["csrfToken"]
    assert "HttpOnly" in created.headers["set-cookie"]
    assert "SameSite=lax" in created.headers["set-cookie"]
    assert "Max-Age=2592000" in created.headers["set-cookie"]

    restored = client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN})
    assert restored.status_code == 200
    assert restored.json() == identity
    current = client.get("/api/v1/identity")
    assert current.json() == {**identity, "role": "anonymous"}

    raw_cookie = client.cookies.get("owner_session")
    with factory() as db:
        session = db.scalar(select(AuthSession))
        assert session.owner_id == identity["ownerId"]
        assert session.token_hash != raw_cookie
        assert session.csrf_hash != identity["csrfToken"]
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        assert (expires_at - datetime.now(timezone.utc)).days in {29, 30}


def test_bootstrap_routes_require_exact_allowed_origin(app_and_session):
    app, factory = app_and_session
    client = TestClient(app)
    with factory() as db:
        db.add(AdminUser(id="admin-1", username="root", password_hash=hash_password("correct")))
        db.commit()

    for headers in ({}, {"Origin": "https://attacker.invalid"}):
        anonymous = client.post("/api/v1/identity/anonymous", headers=headers)
        login = client.post(
            "/api/v1/admin/login",
            headers=headers,
            json={"username": "root", "password": "correct"},
        )
        assert anonymous.status_code == 403
        assert login.status_code == 403
        assert anonymous.json()["error"]["code"] == "CSRF_INVALID"


def test_csrf_is_required_for_owner_write_and_logout_revokes_session(app_and_session):
    app, _factory = app_and_session
    client = TestClient(app)
    identity = client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN}).json()

    denied = client.post("/api/v1/owner-write")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "CSRF_INVALID"
    allowed = client.post(
        "/api/v1/owner-write", headers={"X-CSRF-Token": identity["csrfToken"]}
    )
    assert allowed.status_code == 200

    logout = client.post(
        "/api/v1/logout", headers={"X-CSRF-Token": identity["csrfToken"]}
    )
    assert logout.status_code == 204
    assert client.get("/api/v1/identity").status_code == 401


def test_identity_rejects_a_tampered_csrf_cookie(app_and_session):
    app, _factory = app_and_session
    client = TestClient(app)
    client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN})
    client.cookies.set("owner_csrf", "tampered")

    response = client.get("/api/v1/identity")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_anonymous_bootstrap_rotates_missing_csrf_without_replacing_owner(app_and_session):
    app, factory = app_and_session
    client = TestClient(app)
    first = client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN}).json()
    client.cookies.delete("owner_csrf")

    rotated = client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN})
    assert rotated.status_code == 200
    assert rotated.json()["ownerId"] == first["ownerId"]
    assert rotated.json()["csrfToken"] != first["csrfToken"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_admin_login_uses_separate_session_and_admin_guard(app_and_session):
    app, factory = app_and_session
    with factory() as db:
        password_hash = hash_password("correct horse battery staple")
        assert password_hash.startswith("scrypt$")
        assert "correct horse" not in password_hash
        db.add(AdminUser(id="admin-1", username="operator", password_hash=password_hash))
        db.commit()

    anonymous_client = TestClient(app)
    anonymous_client.post("/api/v1/identity/anonymous", headers={"Origin": ORIGIN})
    denied = anonymous_client.get("/api/v1/admin-only")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "AUTH_REQUIRED"

    admin_client = TestClient(app)
    login = admin_client.post(
        "/api/v1/admin/login",
        headers={"Origin": ORIGIN},
        json={"username": "operator", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["csrfToken"]
    assert admin_client.get("/api/v1/admin-only").json() == {"adminId": "admin-1"}
    assert anonymous_client.cookies.get("owner_session")
    assert admin_client.cookies.get("admin_session")

    with factory() as db:
        db.get(AdminUser, "admin-1").active = False
        db.commit()
    disabled = admin_client.get("/api/v1/admin-only")
    assert disabled.status_code == 401
    assert disabled.json()["error"]["code"] == "AUTH_REQUIRED"


def test_failed_admin_logins_are_rate_limited_in_database(app_and_session):
    app, factory = app_and_session
    with factory() as db:
        db.add(AdminUser(id="admin-1", username="operator", password_hash=hash_password("correct")))
        db.commit()

    client = TestClient(app)
    for _ in range(5):
        response = client.post(
            "/api/v1/admin/login",
            headers={"Origin": ORIGIN},
            json={"username": "operator", "password": "wrong"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/v1/admin/login",
        headers={"Origin": ORIGIN},
        json={"username": "operator", "password": "correct"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_production_cookie_is_secure(app_and_session, monkeypatch):
    app, _factory = app_and_session
    monkeypatch.setenv("APP_ENV", "production")
    response = TestClient(app).post(
        "/api/v1/identity/anonymous", headers={"Origin": ORIGIN}
    )
    assert "Secure" in response.headers["set-cookie"]


def test_alembic_metadata_matches_auth_migration(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'auth-migration.db'}"
    base_command = [
        str(backend_dir.parent / ".venv" / "bin" / "alembic"),
        "-c",
        str(backend_dir / "alembic.ini"),
        "-x",
        f"database_url={database_url}",
    ]
    upgrade = subprocess.run(
        [*base_command, "upgrade", "head"],
        cwd=backend_dir,
        text=True,
        capture_output=True,
    )
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    schema_check = subprocess.run(
        [*base_command, "check"],
        cwd=backend_dir,
        text=True,
        capture_output=True,
    )
    assert schema_check.returncode == 0, schema_check.stdout + schema_check.stderr
    assert "No new upgrade operations detected" in schema_check.stdout
