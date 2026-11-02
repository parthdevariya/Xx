from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import Session as DbSession
from .models import User, utcnow
from .security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, decode_token
from .services.audit import audit

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token:
        return None
    data = decode_token(token, "session")
    if not data:
        return None
    sess = db.get(DbSession, data.get("sid"))
    if sess is None or sess.revoked_at is not None:
        return None
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires < utcnow():
        return None
    user = db.get(User, data.get("sub"))
    if user is None or not user.is_active:
        return None
    request.state.session_id = sess.id
    request.state.auth_via_cookie = bool(request.cookies.get(SESSION_COOKIE))
    return user


def current_user(request: Request, user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    if request.method not in SAFE_METHODS and getattr(request.state, "auth_via_cookie", False):
        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get(CSRF_HEADER)
        if not cookie or not header or cookie != header:
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")
    return user


def require(*permissions: str) -> Callable:
    def dep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        missing = [p for p in permissions if p not in user.permission_codes]
        if missing:
            audit(db, actor=user, category="security", action="permission_denied", outcome="denied",
                  detail={"path": request.url.path, "method": request.method, "missing": missing}, request=request)
            db.commit()
            raise HTTPException(status_code=403, detail=f"Missing permission: {', '.join(missing)}")
        return user
    return dep
