import os
import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import (
    ADMIN_COOKIE,
    ADMIN_CSRF_COOKIE,
    OWNER_COOKIE,
    OWNER_CSRF_COOKIE,
    AuthError,
    clear_login_failures,
    client_key,
    find_session,
    hash_token,
    login_is_limited,
    new_session,
    record_login_failure,
    validate_csrf,
    validate_origin,
    verify_password,
    utcnow,
)
from app.db.session import get_db
from app.models import AdminUser, User


router = APIRouter()


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


def _secure_cookie() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def _set_session_cookies(response: Response, role: str, token: str, csrf: str) -> None:
    session_cookie = OWNER_COOKIE if role == "owner" else ADMIN_COOKIE
    csrf_cookie = OWNER_CSRF_COOKIE if role == "owner" else ADMIN_CSRF_COOKIE
    response.set_cookie(
        session_cookie,
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        csrf_cookie,
        csrf,
        max_age=30 * 24 * 60 * 60,
        httponly=False,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )


@router.post("/identity/anonymous")
def anonymous_identity(request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    existing = find_session(db, request.cookies.get(OWNER_COOKIE), role="owner")
    existing_csrf = request.cookies.get(OWNER_CSRF_COOKIE)
    if existing is not None and existing_csrf and existing.csrf_hash == hash_token(existing_csrf):
        response.status_code = 200
        return {"ownerId": existing.owner_id, "csrfToken": existing_csrf}

    if existing is not None:
        existing.revoked_at = utcnow()
        _session, token, csrf = new_session(db, owner_id=existing.owner_id)
        db.commit()
        response.status_code = 200
        _set_session_cookies(response, "owner", token, csrf)
        return {"ownerId": existing.owner_id, "csrfToken": csrf}

    owner = User(id=str(uuid.uuid4()))
    db.add(owner)
    db.flush()
    _session, token, csrf = new_session(db, owner_id=owner.id)
    db.commit()
    response.status_code = 201
    _set_session_cookies(response, "owner", token, csrf)
    return {"ownerId": owner.id, "csrfToken": csrf}


@router.get("/identity")
def identity(request: Request, db: Session = Depends(get_db)):
    admin = find_session(db, request.cookies.get(ADMIN_COOKIE), role="admin")
    if admin is not None:
        csrf = request.cookies.get(ADMIN_CSRF_COOKIE)
        if csrf and hash_token(csrf) == admin.csrf_hash:
            return {"ownerId": admin.admin_id, "role": "admin", "csrfToken": csrf}
    owner = find_session(db, request.cookies.get(OWNER_COOKIE), role="owner")
    if owner is not None:
        csrf = request.cookies.get(OWNER_CSRF_COOKIE)
        if csrf and hash_token(csrf) == owner.csrf_hash:
            return {"ownerId": owner.owner_id, "role": "anonymous", "csrfToken": csrf}
    raise AuthError(401, "AUTH_REQUIRED", "Authentication required")


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    sessions = []
    for cookie, role in ((OWNER_COOKIE, "owner"), (ADMIN_COOKIE, "admin")):
        session = find_session(db, request.cookies.get(cookie), role=role)
        if session is not None:
            sessions.append(session)
    if not sessions:
        raise AuthError(401, "AUTH_REQUIRED", "Authentication required")
    matching = next(
        (session for session in sessions if request.headers.get("X-CSRF-Token") and hash_token(request.headers["X-CSRF-Token"]) == session.csrf_hash),
        None,
    )
    if matching is None:
        validate_csrf(request, sessions[0])
    matching.revoked_at = utcnow()
    db.commit()
    role = "owner" if matching.owner_id else "admin"
    response.delete_cookie(OWNER_COOKIE if role == "owner" else ADMIN_COOKIE, path="/")
    response.delete_cookie(OWNER_CSRF_COOKIE if role == "owner" else ADMIN_CSRF_COOKIE, path="/")


@router.post("/admin/login")
def admin_login(payload: AdminLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    key = client_key(request)
    if login_is_limited(db, payload.username, key):
        raise AuthError(429, "RATE_LIMITED", "Too many login attempts")
    admin = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if admin is None or not admin.active or not verify_password(payload.password, admin.password_hash):
        record_login_failure(db, payload.username, key)
        raise AuthError(401, "AUTH_REQUIRED", "Invalid credentials")
    clear_login_failures(db, payload.username, key)
    _session, token, csrf = new_session(db, admin_id=admin.id)
    db.commit()
    _set_session_cookies(response, "admin", token, csrf)
    return {"csrfToken": csrf}
