"""
main.py — Vybord User API (FastAPI)
Serves: auth, user management, subscription, quota check, admin panel.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import jinja2
from fastapi import FastAPI, Request, HTTPException, Form, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from database import (
    get_db, init_db, get_user_by_email, get_user_by_id,
    get_plan_by_id, get_default_plan, check_quota, increment_video_count,
)
from models import (
    UserRegister, UserLogin, VerifyEmailRequest, UserPublic, UserDetail,
    UpdateProfile, QuotaResponse, VideoRecord, VideoCompletePayload,
    SubscribeRequest, StripeCheckoutResponse, AdminUserList, AdminUserUpdate,
    GenerateCheckResponse, PlanResponse,
)
from auth import (
    hash_password, verify_password, create_access_token,
    create_verify_token, get_current_user, require_admin,
    set_cookie, clear_cookie, COOKIE_NAME,
)
from stripe_utils import (
    create_checkout_session, create_customer,
    verify_webhook_signature, handle_checkout_completed,
    handle_subscription_updated, handle_payment_failed,
    get_price_id_for_plan,
)

# ── App Setup ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

# Jinja2 directly — bypasses Starlette's TemplateResponse (which adds unhashable request to context)
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=True,
)


def _render(template_name: str, context: dict) -> HTMLResponse:
    """Render a template with context and return HTMLResponse."""
    ctx = dict(context)
    ctx["year"] = datetime.utcnow().year
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(ctx))

app = FastAPI(title="Vybord User API", version="1.0.50")

# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


# ── Auth Routes ──────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(body: UserRegister):
    with get_db() as conn:
        existing = get_user_by_email(conn, body.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        default_plan = get_default_plan(conn)
        if not default_plan:
            raise HTTPException(status_code=500, detail="No default plan configured")

        verify_token = create_verify_token(0)  # placeholder, update after insert

        password_hash = hash_password(body.password)
        verify_token = create_verify_token(0)  # will be updated

        cursor = conn.execute(
            """
            INSERT INTO users (email, password_hash, plan_id, email_verify_token)
            VALUES (?, ?, ?, ?)
            """,
            (body.email, password_hash, default_plan["id"], verify_token),
        )
        conn.commit()
        user_id = cursor.lastrowid

        # Update with real token
        real_token = create_verify_token(user_id)
        conn.execute(
            "UPDATE users SET email_verify_token = ? WHERE id = ?",
            (real_token, user_id),
        )
        conn.commit()

        # TODO: Send verify email here (SMTP). For now, log to server console.
        print(f"[user_api] Verification link: "
              f"https://app.vybord.com/verify-email?token={real_token}")

        token = create_access_token(user_id, body.email, False)
        response = JSONResponse({"message": "Registered. Check email to verify."})
        set_cookie(response, token)
        return response


@app.post("/api/auth/login")
def login(body: UserLogin):
    with get_db() as conn:
        user = get_user_by_email(conn, body.email)
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account suspended")

        token = create_access_token(user["id"], user["email"], bool(user["is_admin"]))

        # Update last_login
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), user["id"]),
        )
        conn.commit()

        response = JSONResponse({
            "message": "Logged in",
            "user": _user_detail(conn, user["id"]),
        })
        set_cookie(response, token)
        return response


@app.post("/api/auth/logout")
def logout():
    response = JSONResponse({"message": "Logged out"})
    clear_cookie(response)
    return response


@app.get("/verify-email")
def verify_email(token: str):
    """GET — user clicks email link."""
    import jwt
    from auth import JWT_SECRET, JWT_ALGORITHM

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return HTMLResponse("<h3>Invalid or expired link.</h3>", status_code=400)

    user_id = int(payload["sub"])
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
    if not user:
        return HTMLResponse("<h3>User not found.</h3>", status_code=404)

    with get_db() as conn:
        conn.execute(
            "UPDATE users SET email_verified = 1, email_verify_token = NULL WHERE id = ?",
            (user_id,),
        )
        conn.commit()

    return RedirectResponse(url="/dashboard?verified=ok")


# ── User / Profile ──────────────────────────────────────────────────────────

@app.get("/api/me")
def get_me(request: Request):
    with get_db() as conn:
        user = get_current_user(request, conn)
        return _user_detail(conn, user["id"])


@app.put("/api/me")
def update_me(body: UpdateProfile, request: Request):
    with get_db() as conn:
        user = get_current_user(request, conn)

        if body.email:
            existing = get_user_by_email(conn, body.email)
            if existing and existing["id"] != user["id"]:
                raise HTTPException(status_code=409, detail="Email taken")
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (body.email, user["id"]))

        if body.password:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(body.password), user["id"]),
            )

        conn.commit()
        return _user_detail(conn, user["id"])


# ── Plan & Quota ─────────────────────────────────────────────────────────────

@app.get("/api/my/plan")
def get_my_plan(request: Request):
    with get_db() as conn:
        user = get_current_user(request, conn)
        plan = get_plan_by_id(conn, user["plan_id"])
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        allowed, remaining, limit = check_quota(conn, user["id"])
        return {
            "plan": {
                "id": plan["id"],
                "name": plan["name"],
                "monthly_limit": plan["monthly_limit"],
                "price_monthly_cents": plan["price_monthly_cents"],
            },
            "quota": {
                "allowed": allowed,
                "remaining": remaining,
                "limit": limit,
                "videos_generated": user["videos_generated"],
            },
        }


@app.get("/api/plans")
def list_plans():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM plans WHERE is_active = 1").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/subscribe")
def subscribe(body: SubscribeRequest, request: Request):
    with get_db() as conn:
        user = get_current_user(request, conn)

        if not user["email_verified"]:
            raise HTTPException(status_code=403, detail="Verify your email first")

        plan = get_plan_by_id(conn, body.plan_id)
        if not plan or not plan["is_active"]:
            raise HTTPException(status_code=404, detail="Plan not found")

        if plan["price_monthly_cents"] == 0:
            # Free plan — no Stripe needed, just upgrade
            conn.execute(
                "UPDATE users SET plan_id = ? WHERE id = ?",
                (plan["id"], user["id"]),
            )
            conn.commit()
            return {"message": "Plan updated to Free", "plan": plan}

        price_id = get_price_id_for_plan(plan["name"], plan["price_monthly_cents"])
        if not price_id:
            raise HTTPException(
                status_code=400,
                detail=f"Stripe not configured for plan '{plan['name']}'. "
                       f"Set STRIPE_PRICE_IDS env var.",
            )

        customer_id = user.get("stripe_customer_id")
        if not customer_id:
            customer_id = create_customer(user["email"], user["id"])
            conn.execute(
                "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
                (customer_id, user["id"]),
            )
            conn.commit()

        checkout_url = create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            user_id=user["id"],
            user_email=user["email"],
        )
        return {"checkout_url": checkout_url}


# ── Video Quota Check (called by build_vps.py) ──────────────────────────────

@app.get("/api/internal/check-quota/{user_id}")
def internal_check_quota(user_id: int) -> GenerateCheckResponse:
    """
    Internal endpoint — called by build_vps.py before starting a job.
    Returns whether the user is allowed to generate and their remaining count.
    """
    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            return GenerateCheckResponse(allowed=False, remaining=0, limit=0, error="User not found")
        if not user["is_active"]:
            return GenerateCheckResponse(allowed=False, remaining=0, limit=0, error="Account suspended")
        if not user["email_verified"]:
            return GenerateCheckResponse(allowed=False, remaining=0, limit=0, error="Email not verified")

        allowed, remaining, limit = check_quota(conn, user_id)
        return GenerateCheckResponse(
            allowed=allowed,
            remaining=remaining,
            limit=limit,
            error=None if allowed else "Video limit reached",
        )


@app.post("/api/internal/video-complete")
def internal_video_complete(body: VideoCompletePayload):
    """
    Called by build_vps.py when a job completes.
    Increments video count and updates video record.
    """
    with get_db() as conn:
        # Find or create video record
        existing = conn.execute(
            "SELECT id FROM videos WHERE job_id = ?", (body.job_id,)
        ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO videos (user_id, job_id, status, completed_at) VALUES (?, ?, ?, ?)",
                (body.user_id, body.job_id, body.status, datetime.utcnow().isoformat()),
            )
        else:
            conn.execute(
                "UPDATE videos SET status = ?, completed_at = ? WHERE job_id = ?",
                (body.status, datetime.utcnow().isoformat(), body.job_id),
            )

        if body.status == "completed":
            increment_video_count(conn, body.user_id)

        conn.commit()
        return {"ok": True}


# ── User Video History ───────────────────────────────────────────────────────

@app.get("/api/my/videos")
def get_my_videos(request: Request, limit: int = 20, offset: int = 0):
    with get_db() as conn:
        user = get_current_user(request, conn)
        rows = conn.execute(
            "SELECT * FROM videos WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user["id"], limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Stripe Webhook ───────────────────────────────────────────────────────────

@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Raw body needed for Stripe signature verification."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    with get_db() as conn:
        # Idempotency guard
        event_id = event.get("id")
        if event_id:
            existing = conn.execute(
                "SELECT id FROM stripe_events WHERE id = ?", (event_id,)
            ).fetchone()
            if existing:
                return {"received": True, "skipped": "already processed"}

            conn.execute(
                "INSERT OR IGNORE INTO stripe_events (id, event_type) VALUES (?, ?)",
                (event_id, event.get("type")),
            )
            conn.commit()

        event_type = event.get("type", "")
        handlers = {
            "checkout.session.completed": handle_checkout_completed,
            "customer.subscription.updated": handle_subscription_updated,
            "customer.subscription.deleted": handle_subscription_updated,
            "invoice.payment_failed": handle_payment_failed,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                handler(conn, event)
            except Exception as e:
                print(f"[user_api] Webhook handler error ({event_type}): {e}")
                return JSONResponse({"error": str(e)}, status_code=500)

    return {"received": True}


# ── Admin Panel — HTML Routes ───────────────────────────────────────────────

def _admin_render(request: Request, template_name: str, context: dict):
    """Render admin template. Request object not passed to template to avoid unhashable context."""
    return _render(template_name, context)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return _admin_render(request, "admin/login.html", {})


@app.post("/admin/login")
def admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    with get_db() as conn:
        user = get_user_by_email(conn, email)
        if not user or not verify_password(password, user["password_hash"]):
            return HTMLResponse("<h3>Invalid credentials</h3>", status_code=401)
        if not user["is_admin"]:
            return HTMLResponse("<h3>Not an admin</h3>", status_code=403)

        token = create_access_token(user["id"], user["email"], True)
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
        set_cookie(response, token)
        return response


@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    clear_cookie(response)
    return response


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    with get_db() as conn:
        require_admin(request, conn)

        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        verified_users = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE email_verified = 1"
        ).fetchone()["c"]
        active_users = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE is_active = 1"
        ).fetchone()["c"]
        total_videos = conn.execute(
            "SELECT COUNT(*) as c FROM videos"
        ).fetchone()["c"]
        videos_this_month = conn.execute(
            "SELECT COUNT(*) as c FROM videos WHERE created_at >= date('now', 'start of month')"
        ).fetchone()["c"]
        total_revenue = conn.execute(
            "SELECT SUM(amount_cents) as s FROM payments WHERE status = 'succeeded'"
        ).fetchone()["s"] or 0
        pending_payments = conn.execute(
            "SELECT COUNT(*) as c FROM payments WHERE status = 'pending'"
        ).fetchone()["c"]

        # Recent signups
        recent_users = conn.execute(
            "SELECT id, email, plan_id, created_at, email_verified, is_active "
            "FROM users ORDER BY created_at DESC LIMIT 10"
        ).fetchall()

        # Recent videos
        recent_videos = conn.execute(
            "SELECT v.*, u.email FROM videos v JOIN users u ON v.user_id = u.id "
            "ORDER BY v.created_at DESC LIMIT 10"
        ).fetchall()

        return _admin_render(request, "admin/dashboard.html", {
            "total_users": total_users,
            "verified_users": verified_users,
            "active_users": active_users,
            "total_videos": total_videos,
            "videos_this_month": videos_this_month,
            "total_revenue_cents": total_revenue,
            "pending_payments": pending_payments,
            "recent_users": [dict(r) for r in recent_users],
            "recent_videos": [dict(r) for r in recent_videos],
        })


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    search: str = "",
    plan_filter: str = "",
    status_filter: str = "",
    page: int = 1,
):
    with get_db() as conn:
        require_admin(request, conn)

        per_page = 25
        offset = (page - 1) * per_page

        where = ["1=1"]
        params = []
        if search:
            where.append("(u.email LIKE ?)")
            params.append(f"%{search}%")
        if plan_filter:
            where.append("u.plan_id = ?")
            params.append(plan_filter)
        if status_filter == "active":
            where.append("u.is_active = 1")
        elif status_filter == "suspended":
            where.append("u.is_active = 0")
        elif status_filter == "unverified":
            where.append("u.email_verified = 0")

        where_sql = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) as c FROM users u WHERE {where_sql}", params
        ).fetchone()["c"]

        rows = conn.execute(
            f"""
            SELECT u.*, p.name as plan_name
            FROM users u JOIN plans p ON u.plan_id = p.id
            WHERE {where_sql}
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()

        plans = conn.execute("SELECT * FROM plans WHERE is_active = 1").fetchall()

        return _admin_render(request, "admin/users.html", {
            "users": [dict(r) for r in rows],
            "plans": [dict(r) for r in plans],
            "search": search,
            "plan_filter": plan_filter,
            "status_filter": status_filter,
            "page": page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        })


@app.get("/admin/users/<int:user_id>", response_class=HTMLResponse)
def admin_user_detail(request: Request, user_id: int):
    with get_db() as conn:
        require_admin(request, conn)

        user = get_user_by_id(conn, user_id)
        if not user:
            return HTMLResponse("User not found", status_code=404)
        plan = get_plan_by_id(conn, user["plan_id"])
        videos = conn.execute(
            "SELECT * FROM videos WHERE user_id = ? ORDER BY created_at DESC LIMIT 50"
        , (user_id,)).fetchall()
        payments = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC LIMIT 20"
        , (user_id,)).fetchall()
        plans = conn.execute("SELECT * FROM plans WHERE is_active = 1").fetchall()

        return _admin_render(request, "admin/user_detail.html", {
            "user": dict(user),
            "plan": dict(plan) if plan else None,
            "videos": [dict(v) for v in videos],
            "payments": [dict(p) for p in payments],
            "plans": [dict(p) for p in plans],
        })


@app.post("/admin/users/<int:user_id>/update")
def admin_update_user(request: Request, user_id: int, body: AdminUserUpdate):
    with get_db() as conn:
        require_admin(request, conn)

        if body.is_active is not None:
            conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (body.is_active, user_id))
        if body.plan_id is not None:
            conn.execute("UPDATE users SET plan_id = ? WHERE id = ?", (body.plan_id, user_id))
        conn.commit()
        return RedirectResponse(url=f"/admin/users/{user_id}", status_code=302)


@app.get("/admin/plans", response_class=HTMLResponse)
def admin_plans(request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        plans = conn.execute("SELECT * FROM plans ORDER BY price_monthly_cents ASC").fetchall()
        return _admin_render(request, "admin/plans.html", {"plans": [dict(p) for p in plans]})


@app.get("/admin/payments", response_class=HTMLResponse)
def admin_payments(request: Request, page: int = 1, status: str = ""):
    with get_db() as conn:
        require_admin(request, conn)

        per_page = 30
        offset = (page - 1) * per_page

        where = ["1=1"]
        params = []
        if status:
            where.append("p.status = ?")
            params.append(status)

        where_sql = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) as c FROM payments p WHERE {where_sql}", params
        ).fetchone()["c"]

        rows = conn.execute(
            f"""
            SELECT p.*, u.email
            FROM payments p JOIN users u ON p.user_id = u.id
            WHERE {where_sql}
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()

        return _admin_render(request, "admin/payments.html", {
            "payments": [dict(r) for r in rows],
            "page": page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
            "status_filter": status,
        })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _user_detail(conn, user_id: int) -> dict:
    user = get_user_by_id(conn, user_id)
    plan = get_plan_by_id(conn, user["plan_id"])
    allowed, remaining, limit = check_quota(conn, user_id)
    return {
        "id": user["id"],
        "email": user["email"],
        "plan_id": user["plan_id"],
        "plan_name": plan["name"] if plan else "Unknown",
        "videos_generated": user["videos_generated"],
        "monthly_limit": plan["monthly_limit"] if plan else 0,
        "is_admin": bool(user["is_admin"]),
        "email_verified": bool(user["email_verified"]),
        "stripe_customer_id": user.get("stripe_customer_id"),
        "stripe_subscription_id": user.get("stripe_subscription_id"),
        "is_active": bool(user["is_active"]),
        "created_at": user["created_at"],
        "last_login": user.get("last_login"),
        "quota": {
            "allowed": allowed,
            "remaining": remaining,
            "limit": limit,
        },
    }


# ── Entry Point ──────────────────────────────────────────────────────────────

def serve():
    init_db()
    port = int(os.getenv("USER_API_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    serve()
