"""
auth.py — JWT + password hashing.
"""

import os
import secrets
import hashlib
import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException, Request, Depends
from fastapi.responses import JSONResponse

# Load from environment — set in .env file
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days

BCRYPT_ROUNDS = 12  # deliberate slowness for security


# ── Passwords ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Salted bcrypt hash. Stored as: bcrypt(password + salt)."""
    salt = os.urandom(16)
    from bcrypt import hashpw, gensalt

    combined = (password + salt.hex()).encode()
    return salt.hex() + "$" + hashpw(combined, gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against its stored hash."""
    try:
        from bcrypt import hashpw, checkpw

        if "$" not in stored:
            # Legacy SHA256 fallback (old passwords)
            return hashlib.sha256(password.encode()).hexdigest() == stored

        salt_hex, b_hash = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        combined = (password + salt_hex).encode()
        return checkpw(combined, b_hash.encode())
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, email: str, is_admin: bool) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "is_admin": is_admin,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_sub": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def create_verify_token(user_id: int) -> str:
    """Short-lived token for email verification."""
    return jwt.encode(
        {"sub": str(user_id), "purpose": "verify", "exp": datetime.utcnow() + timedelta(hours=24)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def create_reset_token(user_id: int) -> str:
    """Short-lived token for password reset."""
    return jwt.encode(
        {"sub": str(user_id), "purpose": "reset", "exp": datetime.utcnow() + timedelta(hours=1)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


# ── Cookie helpers ─────────────────────────────────────────────────────────

COOKIE_NAME = "vyb_token"
COOKIE_OPTS = {
    "httponly": True,
    "secure": True,  # HTTPS only in production
    "samesite": "lax",
    "path": "/",
    "max_age": JWT_EXPIRY_HOURS * 3600,
    "domain": ".vybord.com",
}


def set_cookie(response: JSONResponse, token: str):
    response.set_cookie(key=COOKIE_NAME, value=token, **COOKIE_OPTS)


def clear_cookie(response: JSONResponse):
    response.set_cookie(
        key=COOKIE_NAME,
        value="",
        max_age=0,
        expires=0,
        **COOKIE_OPTS,
    )


def get_token_from_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


# ── Dependency injectors ───────────────────────────────────────────────────

def get_current_user(request: Request, conn):
    """
    Dependency — returns user dict or raises 401.
    Does NOT require email verification.
    """
    token = get_token_from_cookie(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    from database import get_user_by_id

    user = get_user_by_id(conn, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_verified_email(request: Request, conn):
    """Extra gate: user must have verified their email."""
    user = get_current_user(request, conn)
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Email not verified")
    return user


def require_admin(request: Request, conn):
    """Gate: user must have is_admin=True."""
    user = get_current_user(request, conn)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
