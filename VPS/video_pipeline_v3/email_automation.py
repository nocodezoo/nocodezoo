"""
email_automation.py — Vybord Lead Nurture Email System
Sends templated HTML emails via SMTP (video@vybord.com)
and tracks lead state in a SQLite db.
"""

import smtplib, ssl
import sqlite3
import re
import hashlib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
SMTP_HOST = "smtp.hostinger.com"
SMTP_PORT = 465
SMTP_USER = "video@vybord.com"
SMTP_PASS = "MaxPlans4497T$"
FROM_NAME = "Vybord"
FROM_EMAIL = "video@vybord.com"

BASE_DIR = Path("/opt/video_pipeline_v3")
LEADS_DB = BASE_DIR / "leads.db"

# ── Database ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(str(LEADS_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT NOT NULL UNIQUE,
            name        TEXT,
            source      TEXT DEFAULT 'landing_page',
            subscribed  INTEGER DEFAULT 1,
            email_hash  TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            last_sent   TEXT,
            sequence    TEXT DEFAULT 'welcome'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id     INTEGER,
            subject     TEXT,
            template    TEXT,
            sent_at     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sequence_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id     INTEGER NOT NULL,
            template    TEXT NOT NULL,
            send_at     TEXT NOT NULL,
            sent        INTEGER DEFAULT 0,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    conn.commit()
    conn.close()

def _get_conn():
    conn = sqlite3.connect(str(LEADS_DB), timeout=5)
    return conn

# ── SMTP Send ─────────────────────────────────────────────────────────────────
def _smtp_send(to_email: str, subject: str, html_body: str, text_body: str = ""):
    ctx = ssl.create_default_context()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Reply-To"] = FROM_EMAIL
    msg.attach(MIMEText(text_body or html_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, [to_email], msg.as_string())

# ── Email Templates ────────────────────────────────────────────────────────────
BASE_URL = "https://vybord.com"

EMAIL_TEMPLATES = {
    "welcome": {
        "subject": "Welcome to Vybord — Let's make your first video",
        "delay_hours": 0,
    },
    "follow_up_1": {
        "subject": "Here's what your property video will look like",
        "delay_hours": 24,
    },
    "follow_up_2": {
        "subject": "Real agents, real results — see the difference video makes",
        "delay_hours": 72,
    },
    "conversion": {
        "subject": "Ready to stand out? Your 14-day trial is waiting.",
        "delay_hours": 120,
    },
}


def _wrap(body: str, preheader: str = "") -> str:
    tracking_pixel = f'<img src="{BASE_URL}/email/open/{{email_hash}}" width="1" height="1" style="display:none" alt=""/>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title></title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Inter',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:40px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr><td style="background:#0f0f11;border-radius:16px 16px 0 0;padding:32px 40px;text-align:center;">
          <p style="margin:0;font-size:1.4rem;font-weight:800;color:#fff;letter-spacing:-0.5px;">
            <span style="color:#B0E0E6;">Vybord</span>
          </p>
          <p style="margin:6px 0 0;font-size:0.8rem;color:#778899;letter-spacing:1px;text-transform:uppercase;">by Vybord</p>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:#ffffff;padding:40px 40px 32px;">
          {body}
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8f8f8;border-radius:0 0 16px 16px;padding:24px 40px;text-align:center;">
          <p style="margin:0 0 8px;font-size:0.8rem;color:#999999;">
            Vybord · AI-powered property video automation
          </p>
          <p style="margin:0;font-size:0.75rem;color:#bbbbbb;">
            You're receiving this because you signed up at vybord.com · 
            <a href="{BASE_URL}/unsubscribe?email={{email}}" style="color:#999999;">Unsubscribe</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _generate_email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


# ── Template Renderers ────────────────────────────────────────────────────────
def render_welcome(email: str) -> tuple[str, str]:
    h = _generate_email_hash(email)
    body = f"""
          <p style="margin:0 0 24px;font-size:1.6rem;font-weight:700;color:#0f0f11;line-height:1.3;">
            You're in — let's make something great.
          </p>
          <p style="margin:0 0 20px;font-size:1rem;color:#444444;line-height:1.7;">
            Thanks for joining Vybord. We create polished, branded property videos for real estate professionals — with AI voiceover, captions, and music — all from a listing URL.
          </p>
          <p style="margin:0 0 28px;font-size:1rem;color:#444444;line-height:1.7;">
            Here's what happens next:<br/>
            <strong>1.</strong> Reply to this email with any listing URL (Zillow, Realtor.com, Redfin — any of them)<br/>
            <strong>2.</strong> We'll have a video back to you within 24 hours<br/>
            <strong>3.</strong> Share it, post it, send it to clients — watch the response
          </p>
          <p style="margin:0 0 32px;font-size:0.95rem;color:#666666;line-height:1.7;">
            No software to install. No editing skills needed. Just send a link — we handle the rest.
          </p>
          <p style="margin:0 0 32px;" align="center">
            <a href="{BASE_URL}/register.html" style="display:inline-block;background:#778899;color:#ffffff;font-weight:700;font-size:1rem;padding:14px 32px;border-radius:10px;text-decoration:none;">
              Set Up Your Free Account →
            </a>
          </p>
          <p style="margin:0;font-size:0.85rem;color:#999999;line-height:1.6;">
            P.S. If you already have a listing in mind, just forward the URL here and we'll get started.
          </p>
        """
    subject = EMAIL_TEMPLATES["welcome"]["subject"]
    html = _wrap(body, "You're in — let's make your first video").format(email_hash=h, email=email)
    text = f"""Welcome to Vybord!

Thanks for joining. We create polished property videos for real estate professionals — with AI voiceover, captions, and music.

Here's what happens next:
1. Reply to this email with any listing URL (Zillow, Realtor.com, Redfin)
2. We'll have a video back to you within 24 hours
3. Share it, post it, send it to clients

No software needed. Just send a link — we handle the rest.

Set up your free account: {BASE_URL}/register.html

P.S. If you already have a listing in mind, just forward the URL here and we'll get started."""
    return subject, html, text


def render_follow_up_1(email: str) -> tuple[str, str, str]:
    h = _generate_email_hash(email)
    body = """
          <p style="margin:0 0 24px;font-size:1.5rem;font-weight:700;color:#0f0f11;line-height:1.3;">
            Property video = more views, more showings, more offers.
          </p>
          <p style="margin:0 0 20px;font-size:1rem;color:#444444;line-height:1.7;">
            Real estate agents who use video get up to 403% more inquiries than those with photos only. A polished video walkthrough does the selling for you before the showing even starts.
          </p>
          <p style="margin:0 0 20px;font-size:1rem;color:#444444;line-height:1.7;">
            With Vybord, you get:
          </p>
          <p style="margin:0 0 8px;font-size:0.95rem;color:#444444;line-height:1.7;padding-left:20px;">
            ✓ HD video with smooth camera motion<br/>
            ✓ AI voiceover reading the property details<br/>
            ✓ Auto-generated captions (mute-friendly by default)<br/>
            ✓ Your agent branding and MLS info embedded<br/>
            ✓ Delivered within 24 hours of your request
          </p>
          <p style="margin:20px 0 28px;" align="center">
            <a href="{BASE_URL}/register.html" style="display:inline-block;background:#778899;color:#ffffff;font-weight:700;font-size:1rem;padding:14px 32px;border-radius:10px;text-decoration:none;">
              Create Your First Free Video →
            </a>
          </p>
        """
    subject = EMAIL_TEMPLATES["follow_up_1"]["subject"]
    html = _wrap(body).format(email_hash=h, email=email)
    text = """Property video = more views, more showings, more offers.

Real estate agents who use video get up to 403% more inquiries than those with photos only.

With Vybord, you get:
- HD video with smooth camera motion
- AI voiceover reading the property details
- Auto-generated captions
- Your agent branding and MLS info
- Delivered within 24 hours

Create your first free video: {}/register.html""".format(BASE_URL)
    return subject, html, text


def render_follow_up_2(email: str) -> tuple[str, str, str]:
    h = _generate_email_hash(email)
    body = """
          <p style="margin:0 0 24px;font-size:1.5rem;font-weight:700;color:#0f0f11;line-height:1.3;">
            See what a Vybord video looks like.
          </p>
          <p style="margin:0 0 20px;font-size:1rem;color:#444444;line-height:1.7;">
            We put together a sample property video so you can see exactly what your listing would look like. Two minutes — watch the whole thing.
          </p>
          <p style="margin:0 0 28px;" align="center">
            <a href="{BASE_URL}/#demo" style="display:inline-block;background:#778899;color:#ffffff;font-weight:700;font-size:1rem;padding:14px 32px;border-radius:10px;text-decoration:none;">
              Watch the Demo Video →
            </a>
          </p>
          <p style="margin:0 0 20px;font-size:0.95rem;color:#666666;line-height:1.6;">
            Reply with your listing URL anytime — we're standing by to turn it into a video within 24 hours.
          </p>
        """
    subject = EMAIL_TEMPLATES["follow_up_2"]["subject"]
    html = _wrap(body).format(email_hash=h, email=email)
    text = """See what a Vybord video looks like.

We put together a sample property video so you can see exactly what your listing would look like.

Watch the demo: {}/#demo

Reply with your listing URL anytime — we're standing by to turn it into a video within 24 hours.""".format(BASE_URL)
    return subject, html, text


def render_conversion(email: str) -> tuple[str, str, str]:
    h = _generate_email_hash(email)
    body = """
          <p style="margin:0 0 24px;font-size:1.5rem;font-weight:700;color:#0f0f11;line-height:1.3;">
            Your 14-day trial is waiting — no credit card required.
          </p>
          <p style="margin:0 0 20px;font-size:1rem;color:#444444;line-height:1.7;">
            You've seen what we do. Now let's put it to work on your real listing. Pick your plan, send us a URL, and have a professional video back before your next open house.
          </p>
          <p style="margin:0 0 8px;font-size:0.95rem;color:#444444;line-height:1.7;">
            <strong>Starter:</strong> $25/month — up to 10 videos<br/>
            <strong>Pro:</strong> $45/month — up to 20 videos + priority delivery
          </p>
          <p style="margin:20px 0 32px;" align="center">
            <a href="{BASE_URL}/register.html" style="display:inline-block;background:#0f0f11;color:#B0E0E6;font-weight:700;font-size:1rem;padding:14px 32px;border-radius:10px;text-decoration:none;">
              Claim Your Free Trial →
            </a>
          </p>
          <p style="margin:0;font-size:0.85rem;color:#999999;line-height:1.6;">
            Questions? Just reply to this email — a real person reads every message.
          </p>
        """
    subject = EMAIL_TEMPLATES["conversion"]["subject"]
    html = _wrap(body).format(email_hash=h, email=email)
    text = """Your 14-day trial is waiting — no credit card required.

You've seen what we do. Now let's put it to work on your real listing.

Starter: $25/month — up to 10 videos
Pro: $45/month — up to 20 videos + priority delivery

Claim your free trial: {}/register.html

Questions? Just reply to this email — a real person reads every message.""".format(BASE_URL)
    return subject, html, text


TEMPLATE_RENDERERS = {
    "welcome":     render_welcome,
    "follow_up_1": render_follow_up_1,
    "follow_up_2": render_follow_up_2,
    "conversion":  render_conversion,
}


# ── Public API ────────────────────────────────────────────────────────────────

def capture_lead(email: str, name: str = "", source: str = "landing_page") -> dict:
    """Save a new lead and immediately send the welcome email."""
    init_db()
    email = email.strip().lower()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return {"ok": False, "error": "invalid_email"}

    conn = _get_conn()
    cur = conn.execute("SELECT id, subscribed FROM leads WHERE email=?", (email,))
    row = cur.fetchone()

    email_hash = _generate_email_hash(email)
    now = datetime.utcnow().isoformat()

    if row:
        lead_id, subscribed = row
        if subscribed:
            conn.close()
            return {"ok": True, "status": "already_subscribed", "lead_id": lead_id}
        # Re-activate
        conn.execute("UPDATE leads SET subscribed=1, source=?, created_at=? WHERE id=?",
                     (source, now, lead_id))
        conn.commit()
    else:
        cur = conn.execute(
            "INSERT INTO leads (email, name, source, email_hash, subscribed) VALUES (?,?,?,?,1)",
            (email, name or "", source, email_hash)
        )
        lead_id = cur.lastrowid
        conn.commit()
    conn.close()

    # Queue welcome email immediately
    _send_sequence_email(lead_id, email, "welcome")
    _schedule_sequence(lead_id, email)

    return {"ok": True, "status": "captured", "lead_id": lead_id}


def _send_sequence_email(lead_id: int, email: str, template: str):
    try:
        renderer = TEMPLATE_RENDERERS.get(template)
        if not renderer:
            return
        subject, html, text = renderer(email)

        _smtp_send(email, subject, html, text)

        conn = _get_conn()
        conn.execute(
            "INSERT INTO email_log (lead_id, subject, template) VALUES (?,?,?)",
            (lead_id, subject, template)
        )
        conn.execute(
            "UPDATE leads SET last_sent=? WHERE id=?",
            (datetime.utcnow().isoformat(), lead_id)
        )
        conn.commit()
        conn.close()
        print(f"[email_automation] Sent {template} to {email}")
    except Exception as e:
        print(f"[email_automation] ERROR sending {template} to {email}: {e}")


def _schedule_sequence(lead_id: int, email: str):
    """Add follow-up emails to the queue with delays."""
    init_db()
    conn = _get_conn()
    now = datetime.utcnow()
    for name, info in EMAIL_TEMPLATES.items():
        if name == "welcome":
            continue
        send_at = now + timedelta(hours=info["delay_hours"])
        conn.execute(
            "INSERT OR IGNORE INTO sequence_queue (lead_id, template, send_at) VALUES (?,?,?)",
            (lead_id, name, send_at.isoformat())
        )
    conn.commit()
    conn.close()


def process_queue():
    """Call this from a cron job. Sends any due emails."""
    init_db()
    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    rows = conn.execute(
        "SELECT sq.id, sq.lead_id, l.email, sq.template FROM sequence_queue sq "
        "JOIN leads l ON l.id = sq.lead_id "
        "WHERE sq.sent=0 AND sq.send_at <= ?",
        (now,)
    ).fetchall()
    conn.close()

    for row in rows:
        qid, lead_id, email, template = row
        _send_sequence_email(lead_id, email, template)
        conn2 = _get_conn()
        conn2.execute("UPDATE sequence_queue SET sent=1 WHERE id=?", (qid,))
        conn2.commit()
        conn2.close()


def get_leads() -> list:
    """Return all leads with their email log."""
    init_db()
    conn = _get_conn()
    leads = conn.execute("""
        SELECT l.id, l.email, l.name, l.source, l.created_at, l.last_sent, l.subscribed,
               GROUP_CONCAT(el.subject, ' | ') as email_history
        FROM leads l
        LEFT JOIN email_log el ON el.lead_id = l.id
        GROUP BY l.id
        ORDER BY l.created_at DESC
    """).fetchall()
    conn.close()
    return leads


def unsubscribe(email: str) -> bool:
    conn = _get_conn()
    conn.execute("UPDATE leads SET subscribed=0 WHERE email=?", (email.lower(),))
    committed = conn.rowcount > 0
    conn.commit()
    conn.close()
    return committed


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python email_automation.py capture <email> [name] [source]")
        print("       python email_automation.py queue")
        print("       python email_automation.py leads")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "capture":
        email = sys.argv[2] if len(sys.argv) > 2 else input("Email: ")
        name  = sys.argv[3] if len(sys.argv) > 3 else ""
        source = sys.argv[4] if len(sys.argv) > 4 else "manual"
        result = capture_lead(email, name, source)
        print(result)
    elif cmd == "queue":
        process_queue()
        print("Queue processed.")
    elif cmd == "leads":
        for row in get_leads():
            print(row)
