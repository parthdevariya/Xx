from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..models import Session as DbSession
from ..security import hash_password, validate_password_strength
from ..services.audit import audit
from .auth import user_out

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field("", max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: str


class UserUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=12, max_length=256)


def _row(u: User) -> dict:
    return {**user_out(u), "is_active": u.is_active, "created_at": u.created_at,
            "last_login_at": u.last_login_at}


def _check_role_change(actor: User, role: Role) -> None:
    if role.rank >= actor.role.rank and actor.role.code != "super_admin":
        raise HTTPException(status_code=403, detail="You cannot assign a role equal to or above your own.")


@router.get("")
def list_users(db: Session = Depends(get_db), _: User = Depends(require("users.read"))):
    return [_row(u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: User = Depends(require("users.read"))):
    return [{"code": r.code, "name": r.name, "rank": r.rank, "permissions": sorted(p.code for p in r.permissions)}
            for r in db.scalars(select(Role).order_by(Role.rank.desc()))]


@router.post("")
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require("users.write"))):
    role = db.scalar(select(Role).where(Role.code == body.role))
    if role is None:
        raise HTTPException(status_code=422, detail="Unknown role.")
    _check_role_change(actor, role)
    problem = validate_password_strength(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status_code=409, detail="An account with that email exists.")
    u = User(email=body.email.lower(), display_name=body.display_name, password_hash=hash_password(body.password),
             role_id=role.id)
    db.add(u)
    db.flush()
    db.refresh(u)
    audit(db, actor=actor, category="admin", action="user_created", target_type="user", target_id=u.id,
          detail={"email": u.email, "role": role.code}, request=request)
    db.commit()
    return _row(u)


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require("users.write"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.role.rank >= actor.role.rank and actor.role.code != "super_admin" and u.id != actor.id:
        raise HTTPException(status_code=403, detail="You cannot modify a user at or above your role.")
    changes = {}
    if body.role is not None:
        role = db.scalar(select(Role).where(Role.code == body.role))
        if role is None:
            raise HTTPException(status_code=422, detail="Unknown role.")
        if u.id == actor.id:
            raise HTTPException(status_code=403, detail="You cannot change your own role.")
        _check_role_change(actor, role)
        u.role_id, changes["role"] = role.id, role.code
    if body.display_name is not None:
        u.display_name = changes["display_name"] = body.display_name
    if body.is_active is not None:
        if u.id == actor.id and not body.is_active:
            raise HTTPException(status_code=403, detail="You cannot deactivate yourself.")
        u.is_active = changes["is_active"] = body.is_active
        if not body.is_active:
            for s in db.scalars(select(DbSession).where(DbSession.user_id == u.id, DbSession.revoked_at.is_(None))):
                from ..models import utcnow
                s.revoked_at = utcnow()
    if body.password is not None:
        problem = validate_password_strength(body.password)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        u.password_hash = hash_password(body.password)
        changes["password"] = "changed"
    audit(db, actor=actor, category="admin", action="user_updated", target_type="user", target_id=u.id,
          detail=changes, request=request)
    db.commit()
    db.refresh(u)
    return _row(u)
