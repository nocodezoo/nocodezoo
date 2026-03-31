"""
database.py — SQLite database setup and table initialization.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

DATABASE_PATH = Path("/opt/video_pipeline/user_api.db")
ENSURE_TABLES_SQL = """
-- Plans table
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    monthly_limit INTEGER NOT NULL,        -- -1 = unlimited
    price_monthly_cents INTEGER NOT NULL, -- 0 = free
    stripe_price_id TEXT,                 -- set after Stripe product created
    is_active BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    plan_id INTEGER NOT NULL DEFAULT 1,
    videos_generated INTEGER NOT NULL DEFAULT 0,
    videos_reset_at TEXT,                 -- month marker for quota reset
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    is_active BOOLEAN DEFAULT 1,
    is_admin BOOLEAN DEFAULT 0,
    email_verified BOOLEAN DEFAULT 0,
    email_verify_token TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(id)
);

-- Videos table (audit log)
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    job_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/processing/completed/failed
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Payments table (audit log)
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stripe_payment_intent_id TEXT UNIQUE,
    stripe_subscription_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT DEFAULT 'usd',
    status TEXT NOT NULL,  -- succeeded/failed/refunded/pending
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Stripe events log (idempotency guard)
CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,  -- Stripe event ID
    event_type TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""


@contextmanager
def get_db():
    """Yield a DB connection with row factory. Use with `with get_db() as conn:`."""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def init_db():
    """Create all tables and seed default plans."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.executescript(ENSURE_TABLES_SQL)
    conn.commit()

    # Seed default plans if not exist
    default_plans = [
        ("Free", 3, 0, None),
        ("Pro", 50, 2900, None),
        ("Enterprise", -1, 9900, None),
    ]
    for name, limit, price, stripe_price_id in default_plans:
        conn.execute(
            """
            INSERT OR IGNORE INTO plans (name, monthly_limit, price_monthly_cents, stripe_price_id)
            VALUES (?, ?, ?, ?)
            """,
            (name, limit, price, stripe_price_id),
        )
    conn.commit()
    conn.close()
    print(f"[user_api] Database initialized at {DATABASE_PATH}")


def get_user_by_email(conn, email: str):
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn, user_id: int):
    row = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def get_plan_by_id(conn, plan_id: int):
    row = conn.execute(
        "SELECT * FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return dict(row) if row else None


def get_default_plan(conn):
    row = conn.execute(
        "SELECT * FROM plans WHERE name = 'Free' AND is_active = 1"
    ).fetchone()
    return dict(row) if row else None


def check_quota(conn, user_id: int) -> tuple[bool, int, int]:
    """
    Returns (allowed, remaining, limit).
    -1 limit means unlimited.
    Uses row-level locking for concurrent safety.
    """
    row = conn.execute(
        "SELECT u.id, u.videos_generated, u.videos_reset_at, p.monthly_limit "
        "FROM users u JOIN plans p ON u.plan_id = p.id "
        "WHERE u.id = ? AND u.is_active = 1",
        (user_id,),
    ).fetchone()

    if not row:
        return False, 0, 0

    videos_generated = row["videos_generated"]
    monthly_limit = row["monthly_limit"]
    videos_reset_at = row["videos_reset_at"]

    # Reset monthly counter if new month
    now = datetime.utcnow()
    current_month = now.strftime("%Y-%m")
    if videos_reset_at is None or videos_reset_at < current_month:
        conn.execute(
            "UPDATE users SET videos_generated = 0, videos_reset_at = ? WHERE id = ?",
            (current_month, user_id),
        )
        conn.commit()
        return True, monthly_limit, monthly_limit

    if monthly_limit == -1:
        return True, -1, -1  # unlimited

    remaining = max(0, monthly_limit - videos_generated)
    return remaining > 0, remaining, monthly_limit


def increment_video_count(conn, user_id: int):
    """Atomically increment video count. Returns new count."""
    conn.execute(
        "UPDATE users SET videos_generated = videos_generated + 1 WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT videos_generated FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row["videos_generated"] if row else None
