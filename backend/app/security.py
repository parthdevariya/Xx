from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_hasher = PasswordHasher()
SESSION_COOKIE = "x_session"
CSRF_COOKIE = "x_csrf"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> str | None:
    if len(password) < 12:
        return "Password must be at least 12 characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Password must mix upper- and lower-case letters and include a digit."
    return None


def create_session_token(user_id: str, session_id: str) -> tuple[str, datetime]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.session_hours)
    token = jwt.encode({"sub": user_id, "sid": session_id, "exp": exp, "typ": "session"}, s.secret_key,
                       algorithm="HS256")
    return token, exp


def create_ws_ticket(user_id: str, execution_id: str) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    return jwt.encode({"sub": user_id, "eid": execution_id, "exp": exp, "typ": "ws"}, s.secret_key,
                      algorithm="HS256")


def decode_token(token: str, typ: str) -> dict | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == typ else None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Credential encryption
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        if s.is_production:
            raise RuntimeError("X_ENCRYPTION_KEY is not configured")
        # Development only: derive a stable key from the secret so local data stays readable.
        key = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("stored credential cannot be decrypted with the current X_ENCRYPTION_KEY") from exc


def secret_hint(plain: str) -> str:
    if len(plain) <= 8:
        return "•" * len(plain)
    return f"{plain[:3]}…{plain[-4:]}"
