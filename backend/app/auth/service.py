from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
import sys
import uuid

from fastapi import Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.models import AdminLoginAttempt, AuthSession
from app.db.session import SessionLocal, get_db
from app.models import AdminUser


SESSION_TTL = timedelta(days=30)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_LIMIT = 5
OWNER_COOKIE = "owner_session"
ADMIN_COOKIE = "admin_session"
OWNER_CSRF_COOKIE = "owner_csrf"
ADMIN_CSRF_COOKIE = "admin_csrf"


class AuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, expected_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_session(
    db: Session, *, owner_id: str | None = None, admin_id: str | None = None
) -> tuple[AuthSession, str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    session = AuthSession(
        id=str(uuid.uuid4()),
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf),
        owner_id=owner_id,
        admin_id=admin_id,
        expires_at=utcnow() + SESSION_TTL,
    )
    db.add(session)
    db.flush()
    return session, token, csrf


def find_session(db: Session, token: str | None, *, role: str) -> AuthSession | None:
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None or _aware(session.expires_at) <= utcnow():
        return None
    if role == "owner" and session.owner_id is None:
        return None
    if role == "admin" and session.admin_id is None:
        return None
    if role == "admin":
        admin = db.get(AdminUser, session.admin_id)
        if admin is None or not admin.active:
            return None
    return session


def validate_csrf(request: Request, session: AuthSession) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    supplied = request.headers.get("X-CSRF-Token")
    if not supplied or not hmac.compare_digest(hash_token(supplied), session.csrf_hash):
        raise AuthError(403, "CSRF_INVALID", "CSRF validation failed")


def require_owner(request: Request, db: Session = Depends(get_db)) -> str:
    session = find_session(db, request.cookies.get(OWNER_COOKIE), role="owner")
    if session is None:
        raise AuthError(401, "AUTH_REQUIRED", "Authentication required")
    validate_csrf(request, session)
    return session.owner_id  # type: ignore[return-value]


def require_admin(request: Request, db: Session = Depends(get_db)) -> str:
    session = find_session(db, request.cookies.get(ADMIN_COOKIE), role="admin")
    if session is None:
        raise AuthError(401, "AUTH_REQUIRED", "Authentication required")
    validate_csrf(request, session)
    return session.admin_id  # type: ignore[return-value]


def validate_origin(request: Request) -> None:
    allowed = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
    origin = request.headers.get("Origin", "").rstrip("/")
    if not origin or not hmac.compare_digest(origin, allowed):
        raise AuthError(403, "CSRF_INVALID", "Origin validation failed")


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return hash_token(host)


def login_is_limited(db: Session, username: str, key: str) -> bool:
    cutoff = utcnow() - LOGIN_WINDOW
    count = db.scalar(
        select(func.count()).select_from(AdminLoginAttempt).where(
            AdminLoginAttempt.username == username,
            AdminLoginAttempt.client_key == key,
            AdminLoginAttempt.attempted_at >= cutoff,
        )
    )
    return bool(count is not None and count >= LOGIN_LIMIT)


def record_login_failure(db: Session, username: str, key: str) -> None:
    db.add(AdminLoginAttempt(id=str(uuid.uuid4()), username=username, client_key=key))
    db.commit()


def clear_login_failures(db: Session, username: str, key: str) -> None:
    db.execute(
        delete(AdminLoginAttempt).where(
            AdminLoginAttempt.username == username, AdminLoginAttempt.client_key == key
        )
    )


def bootstrap_admin_from_env(db: Session) -> str:
    username = os.getenv("ADMIN_BOOTSTRAP_USERNAME")
    password = os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
    if not username or not password:
        raise RuntimeError("ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_PASSWORD are required")
    existing = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if existing is not None:
        raise RuntimeError("administrator already exists")
    admin_id = str(uuid.uuid4())
    db.add(AdminUser(id=admin_id, username=username, password_hash=hash_password(password)))
    db.commit()
    return admin_id


if __name__ == "__main__":
    if sys.argv[1:] != ["bootstrap-admin"]:
        raise SystemExit("usage: python -m app.auth.service bootstrap-admin")
    try:
        with SessionLocal() as bootstrap_db:
            created_id = bootstrap_admin_from_env(bootstrap_db)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    print(f"administrator created: {created_id}")
