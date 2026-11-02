from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, current_user_optional
from ..models import Role, User, utcnow
from ..models import Session as DbSession
from ..ratelimit import limit
from ..security import (CSRF_COOKIE, SESSION_COOKIE, create_session_token, hash_password, new_csrf_token,
                        validate_password_strength, verify_password)
from ..services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
LOCK_AFTER, LOCK_MINUTES = 8, 15


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field("", max_length=120)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role.code,
            "role_name": u.role.name, "permissions": sorted(u.permission_codes)}


def _set_cookies(response: Response, token: str, max_age: int) -> None:
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax",
                        max_age=max_age, path="/")
    response.set_cookie(CSRF_COOKIE, new_csrf_token(), httponly=False, secure=s.cookie_secure, samesite="lax",
                        max_age=max_age, path="/")


def start_session(db: Session, user: User, request: Request, response: Response) -> None:
    sess = DbSession(user_id=user.id, expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
                     ip=request.client.host if request.client else "",
                     user_agent=request.headers.get("user-agent", "")[:400])
    db.add(sess)
    db.flush()
    token, exp = create_session_token(user.id, sess.id)
    _set_cookies(response, token, get_settings().session_hours * 3600)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, "login", get_settings().login_rate_limit_per_min)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    now = utcnow()
    if user and user.locked_until and (user.locked_until if user.locked_until.tzinfo else
                                       user.locked_until.replace(tzinfo=now.tzinfo)) > now:
        audit(db, actor=user, category="auth", action="login_locked", outcome="denied", request=request)
        db.commit()
        raise HTTPException(status_code=423, detail="Account temporarily locked after repeated failures.")
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= LOCK_AFTER:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
                audit(db, actor=user, category="security", action="account_locked", request=request)
        audit(db, actor=user, category="auth", action="login_failed", outcome="denied",
              detail={"email": body.email}, request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    start_session(db, user, request, response)
    audit(db, actor=user, category="auth", action="login", request=request)
    db.commit()
    return user_out(user)


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not get_settings().allow_registration:
        raise HTTPException(status_code=403, detail="Self-registration is disabled. Ask an administrator.")
    limit(request, "register", 5)
    problem = validate_password_strength(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status_code=409, detail="An account with that email exists.")
    role = db.scalar(select(Role).where(Role.code == "standard"))
    user = User(email=body.email.lower(), display_name=body.display_name, password_hash=hash_password(body.password),
                role_id=role.id)
    db.add(user)
    db.flush()
    db.refresh(user)
    start_session(db, user, request, response)
    audit(db, actor=user, category="auth", action="register", request=request)
    db.commit()
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sid = getattr(request.state, "session_id", None)
    if sid:
        sess = db.get(DbSession, sid)
        if sess:
            sess.revoked_at = utcnow()
    audit(db, actor=user, category="auth", action="logout", request=request)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User | None = Depends(current_user_optional)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user_out(user)


@router.get("/config")
def auth_config():
    return {"registration": get_settings().allow_registration}
