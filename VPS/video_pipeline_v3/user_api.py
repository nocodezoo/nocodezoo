#!/usr/bin/env python3
"""
user_api.py — Vybord User API (FastAPI) V3.1
Replaces main.py + SQLite with Supabase as the backend.

Key changes:
- Auth: Supabase Auth (REST API) for password verification
- Data: Supabase PostgreSQL via PostgREST API
- JWT: issued locally (same format as old auth.py) for compatibility
- Endpoints: identical to main.py — drop-in replacement
"""

import os, sys, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from functools import wraps

import httpx
import jwt
import bcrypt
import jinja2
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

sys.path.insert(0, str(Path(__file__).parent))

# ── Config ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "http://95.111.236.104:54341")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")           # anon key (public)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "postgresql://postgres:postgres@95.111.236.104:54342/postgres")
JWT_SECRET = os.getenv("JWT_SECRET", "e7afe89a80db2dc4ff2d1f23b01d2662e19d36dfde83a497e4be9ea63178934e")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7
BASE_DIR = Path(__file__).parent

# ── Session Persistence (SQLite) ────────────────────────────────────────────
_SESSIONS_DB = BASE_DIR / "sessions.db"

def _init_sessions_db():
    """Create sessions table if not exists."""
    conn = sqlite3.connect(str(_SESSIONS_DB), timeout=5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id   TEXT PRIMARY KEY,
            email     TEXT,
            token     TEXT,
            created_at TEXT,
            last_seen TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            token     TEXT PRIMARY KEY,
            revoked_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def _upsert_session(user_id: str, email: str, token: str):
    """Insert or update an active session."""
    conn = sqlite3.connect(str(_SESSIONS_DB), timeout=5)
    conn.execute("""
        INSERT INTO active_sessions (user_id, email, token, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            email=excluded.email, token=excluded.token, last_seen=excluded.last_seen
    """, (user_id, email, token, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def _revoke_session(user_id: str, token: str):
    """Remove active session and add token to revocation list."""
    conn = sqlite3.connect(str(_SESSIONS_DB), timeout=5)
    conn.execute("DELETE FROM active_sessions WHERE user_id=?", (user_id,))
    conn.execute("INSERT OR IGNORE INTO revoked_tokens (token, revoked_at) VALUES (?, ?)",
                (token, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def _is_token_revoked(token: str) -> bool:
    """Check if token is in the revocation list."""
    conn = sqlite3.connect(str(_SESSIONS_DB), timeout=5)
    cur = conn.execute("SELECT 1 FROM revoked_tokens WHERE token=?", (token,))
    revoked = cur.fetchone() is not None
    conn.close()
    return revoked

# ── Supabase REST helpers ───────────────────────────────────────────────────
def _sb_headers(user_token: str = ""):
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    elif SUPABASE_SERVICE_KEY:
        headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_KEY}"
    return headers

async def _sb_get(table: str, query: str = "", user_token: str = "") -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        url = f"{SUPABASE_URL}/rest/v1/{table}" + (f"?{query}" if query else "")
        resp = await client.get(url, headers=_sb_headers(user_token))
        if resp.status_code == 200:
            return resp.json()
        return None

async def _sb_post(table: str, data: dict, user_token: str = "") -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            json=data,
            headers=_sb_headers(user_token)
        )
        return {"status": resp.status_code, "data": resp.json() if resp.status_code not in (201, 204) else None}

async def _sb_update(table: str, data: dict, query: str, user_token: str = "") -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/{table}?{query}",
            json=data,
            headers=_sb_headers(user_token)
        )
        return {"status": resp.status_code}

# ── Supabase Auth ──────────────────────────────────────────────────────────
async def sb_auth_login(email: str, password: str) -> dict:
    """Verify email+password against Supabase Auth. Returns user info or raises."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            json={"email": email, "password": password},
            headers={**_sb_headers(), "Content-Type": "application/json"}
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        data = resp.json()
        return data  # contains access_token, user, etc.

async def sb_auth_register(email: str, password: str) -> dict:
    """Register new user in Supabase Auth."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/signup",
            json={"email": email, "password": password},
            headers={**_sb_headers(), "Content-Type": "application/json"}
        )
        if resp.status_code not in (200, 201):
            err = resp.json()
            raise HTTPException(status_code=400, detail=err.get("msg", err.get("message", "Signup failed")))
        return resp.json()

# ── JWT Helpers (same format as old auth.py) ─────────────────────────────
def _create_token(user_id: str, email: str, is_admin: bool = False) -> str:
    payload = {
        "sub": user_id, "email": email, "is_admin": is_admin,
        "iat": datetime.utcnow(), "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_sub": False})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

COOKIE_NAME = "vyb_token"

def _get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _decode_token(token)

def _get_token_from_header(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token

# ── App ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_sessions_db()
    print(f"[user_api] Sessions DB ready: {_SESSIONS_DB}")
    # Check Supabase connectivity on startup
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            r = await client.get(f"{SUPABASE_URL}/rest/v1/", headers=_sb_headers())
            print(f"[user_api] Supabase connected: {r.status_code}")
        except Exception as e:
            print(f"[user_api] WARN: Supabase unreachable: {e}")
    yield

app = FastAPI(title="Vybord User API V3.1", version="3.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.vybord.com", "http://app.vybord.com"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=True,
)

def _render(template_name: str, context: dict) -> HTMLResponse:
    ctx = dict(context); ctx["year"] = datetime.utcnow().year
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(ctx))

# ── Health ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.1.0", "backend": "supabase"}

# ── Auth ──────────────────────────────────────────────────────────────────
@app.post("/api/auth/register")
async def register(body: dict):
    email = body.get("email"); password = body.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    try:
        result = await sb_auth_register(email, password)
        user = result.get("user", {})
        user_id = user.get("id", "")

        # Create profile directly in Supabase DB
        await _sb_post("profiles", {
            "id": user_id,
            "email": email,
        }, SUPABASE_SERVICE_KEY)

        token = _create_token(user_id, email)
        return {
            "access_token": token, "user": {"id": user_id, "email": email}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
async def login(body: dict, request: Request):
    email = body.get("email"); password = body.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password required")

    try:
        result = await sb_auth_login(email, password)
        user = result.get("user", {})
        user_id = user.get("id", "")
        session = result.get("session", {})

        # Get profile for admin flag
        profile = await _sb_get("profiles", f"id=eq.{user_id}&select=is_admin", SUPABASE_SERVICE_KEY)
        is_admin = False
        if isinstance(profile, list) and len(profile) > 0:
            is_admin = profile[0].get("is_admin", False)

        token = _create_token(user_id, email, is_admin)

        # Ensure profile exists (create if not — handles users created before trigger was active)
        existing = await _sb_get("profiles", f"id=eq.{user_id}&select=id", SUPABASE_SERVICE_KEY)
        if not existing:
            await _sb_post("profiles", {"id": user_id, "email": email}, SUPABASE_SERVICE_KEY)

        # Update last_login
        await _sb_update("profiles", {"last_login": datetime.utcnow().isoformat()}, f"id=eq.{user_id}", SUPABASE_SERVICE_KEY)

        resp = JSONResponse({"access_token": token, "user": {"id": user_id, "email": email, "is_admin": is_admin}})
        resp.set_cookie(key=COOKIE_NAME, value=token, httponly=True, secure=True, samesite="lax", path="/", max_age=86400*7)
        _upsert_session(user_id, email, token)
        return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = _decode_token(token)
        _revoke_session(payload.get("sub", ""), token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp

@app.get("/verify-email")
async def verify_email(token: str = ""):
    # Supabase handles email verification — this is a stub
    return _render("message.html", {
        "title": "Email Verified",
        "message": "Your email has been verified. You can now generate videos."
    })

# ── User ───────────────────────────────────────────────────────────────────
@app.get("/api/me")
async def get_me(request: Request):
    token = _get_token_from_header(request)
    payload = _decode_token(token)
    user_id = payload["sub"]
    email = payload.get("email", "")

    print(f"[DEBUG /api/me] user_id={user_id}, email={email}", flush=True)

    profile = await _sb_get("profiles", f"id=eq.{user_id}&select=*", SUPABASE_SERVICE_KEY)
    print(f"[DEBUG /api/me] profile query result: {profile}", flush=True)
    if isinstance(profile, list) and len(profile) > 0:
        p = profile[0]
        plan = await _sb_get("plans", f"id=eq.{p.get('plan_id','')}&select=*", SUPABASE_SERVICE_KEY)
        plan_name = plan[0].get("name", "Free") if isinstance(plan, list) and plan else "Free"
        monthly_limit = plan[0].get("monthly_limit", 5) if isinstance(plan, list) and plan else 5

        return {
            "id": user_id, "email": email,
            "plan_id": p.get("plan_id"), "plan_name": plan_name,
            "videos_generated": p.get("videos_made", 0),
            "monthly_limit": monthly_limit,
            "is_admin": p.get("is_admin", False),
            "email_verified": True,  # Supabase handles this
            "created_at": p.get("created_at", ""),
        }
    raise HTTPException(status_code=404, detail="Profile not found")

@app.put("/api/me")
async def update_me(body: dict, request: Request):
    token = _get_token_from_header(request)
    payload = _decode_token(token)
    user_id = payload["sub"]

    updates = {}
    if "email" in body:
        updates["email"] = body["email"]
    if "password" in body:
        # Update Supabase Auth password
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.update_user(
                user_id,
                {"password": body["password"]},
                headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "Content-Type": "application/json"}
            )
    if updates:
        await _sb_update("profiles", updates, f"id=eq.{user_id}", SUPABASE_SERVICE_KEY)
    return {"ok": True}

# ── Plan & Quota ───────────────────────────────────────────────────────────
@app.get("/api/my/plan")
async def get_my_plan(request: Request):
    token = _get_token_from_header(request)
    payload = _decode_token(token)
    user_id = payload["sub"]

    profile = await _sb_get("profiles", f"id=eq.{user_id}&select=plan_id,videos_made,is_admin", SUPABASE_SERVICE_KEY)
    if not (isinstance(profile, list) and len(profile) > 0):
        raise HTTPException(status_code=404, detail="Profile not found")
    p = profile[0]
    plan_id = p.get("plan_id")

    plan = await _sb_get("plans", f"id=eq.{plan_id}&select=*", SUPABASE_SERVICE_KEY)
    if not (isinstance(plan, list) and len(plan) > 0):
        raise HTTPException(status_code=404, detail="Plan not found")
    pl = plan[0]

    monthly_limit = pl.get("monthly_limit", 5)
    videos_made = p.get("videos_made", 0)
    remaining = -1 if monthly_limit == -1 else max(0, monthly_limit - videos_made)

    return {
        "plan": {
            "id": pl.get("id"), "name": pl.get("name"),
            "monthly_limit": monthly_limit,
            "price_monthly_cents": pl.get("price_cents", 0),
        },
        "quota": {
            "allowed": remaining == -1 or remaining > 0,
            "remaining": remaining, "limit": monthly_limit,
            "videos_generated": videos_made,
        },
    }

@app.get("/api/plans")
async def list_plans():
    plans = await _sb_get("plans", "is_active=eq.true&select=*", SUPABASE_SERVICE_KEY)
    if plans is None:
        return []
    return plans

# ── Internal (called by vps_api pipeline) ──────────────────────────────────
@app.get("/api/internal/check-quota/{uid}")
async def internal_check_quota(uid: str):
    """Called by build_vps.py — returns quota status for user."""
    profile = await _sb_get("profiles", f"id=eq.{uid}&select=plan_id,videos_made,is_active,email", SUPABASE_SERVICE_KEY)
    if not (isinstance(profile, list) and len(profile) > 0):
        return {"allowed": False, "remaining": 0, "limit": 0, "error": "User not found"}
    p = profile[0]
    if not p.get("is_active", True):
        return {"allowed": False, "remaining": 0, "limit": 0, "error": "Account suspended"}

    plan = await _sb_get("plans", f"id=eq.{p.get('plan_id','')}&select=monthly_limit", SUPABASE_SERVICE_KEY)
    monthly_limit = plan[0].get("monthly_limit", 5) if isinstance(plan, list) and plan else 5
    videos_made = p.get("videos_made", 0)
    remaining = -1 if monthly_limit == -1 else max(0, monthly_limit - videos_made)

    return {
        "allowed": remaining == -1 or remaining > 0,
        "remaining": remaining, "limit": monthly_limit,
        "videos_generated": videos_made,
    }

@app.post("/api/internal/video-complete")
async def internal_video_complete(body: dict):
    """Called by build_vps.py — record video and increment count."""
    job_id = body.get("job_id"); user_id = body.get("user_id"); status = body.get("status", "completed")
    if not job_id or not user_id:
        raise HTTPException(status_code=400, detail="job_id and user_id required")

    # Insert/update video record
    await _sb_post("videos", {
        "user_id": user_id, "job_id": job_id,
        "status": status,
        "completed_at": datetime.utcnow().isoformat() if status == "completed" else None,
    }, SUPABASE_SERVICE_KEY)

    # Increment videos_made
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/increment_videos_made",
            json={"uid": user_id},
            headers={**_sb_headers(), "Content-Type": "application/json"}
        )

    return {"ok": True}

@app.get("/api/my/videos")
async def my_videos(request: Request):
    token = _get_token_from_header(request)
    payload = _decode_token(token)
    user_id = payload["sub"]
    videos = await _sb_get("videos", f"user_id=eq.{user_id}&order=created_at.desc&limit=50", SUPABASE_SERVICE_KEY)
    return videos if isinstance(videos, list) else []

# ── Admin ──────────────────────────────────────────────────────────────────
@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stub — Stripe webhooks go directly to Supabase Edge Function."""
    return {"ok": True, "note": "Stripe webhooks handled by Supabase Edge Function"}

# ── Entry Point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("USER_API_PORT", "18001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
