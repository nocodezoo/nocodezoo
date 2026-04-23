# Vybord User API — Deployment Guide

## Overview

New architecture:
```
Browser → send.php (Hostinger) → VPS port 8001 (user_api)
                                        ↓
                              Quota check → Stripe → DB
                                        ↓
                              Forward to port 8000 (vps_api)
```

---

## Step 1 — Upload Files to VPS

From your local machine, copy the `vybord-user-api/` directory to the VPS:

```bash
# Create tarball locally
cd ~/.openclaw/workspace
tar -czvf vybord-user-api.tar.gz vybord-user-api/

# Upload to VPS
scp vybord-user-api.tar.gz root@95.111.236.104:/tmp/

# SSH into VPS
ssh root@95.111.236.104

# Extract and move to install location
cd /opt/video_pipeline
tar -xzvf /tmp/vybord-user-api.tar.gz
mv vybord-user-api/* .
rm -rf vybord-user-api
```

---

## Step 2 — Install Python Dependencies on VPS

```bash
# SSH into VPS
ssh root@95.111.236.104

# Install dependencies
pip install fastapi uvicorn[standard] pydantic email-validator bcrypt PyJWT stripe python-multipart jinja2 aiofiles

# Verify
python3 -c "import fastapi, uvicorn, pydantic, bcrypt, jwt, stripe; print('All OK')"
```

---

## Step 3 — Configure Environment

```bash
# On VPS
cd /opt/video_pipeline

# Create .env file
cp .env.example .env
nano .env   # fill in JWT_SECRET, Stripe keys, SMTP

# Generate JWT secret
python3 -c "import secrets; print(secrets.token_hex(32))"
# Copy output into JWT_SECRET in .env
```

---

## Step 4 — Create Ryan's Admin Account

```bash
# On VPS — run once to create the DB and an admin user
python3 -c "
import sys; sys.path.insert(0, '/opt/video_pipeline')
from database import init_db, get_db
from auth import hash_password, create_access_token

init_db()

# Create admin user (email + password you choose)
with get_db() as conn:
    conn.execute('''
        INSERT OR REPLACE INTO users (email, password_hash, plan_id, is_admin, is_active, email_verified)
        VALUES (?, ?, 1, 1, 1, 1)
    ''', ('YOUR_ADMIN_EMAIL@DOMAIN.COM', 'HASHED_PASSWORD_PLACEHOLDER'))
    conn.commit()
"
```

Then update the password hash with the real one:
```python
# Calculate hash
python3 -c "from auth import hash_password; print(hash_password('YOUR_REAL_PASSWORD'))"
# Copy the hash output and UPDATE the user in the DB
```

---

## Step 5 — Update nginx

Add to the nginx config on VPS (`/etc/nginx/sites-available/default` or vybord config):

```nginx
# User API routes
location /api/auth {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
}

location /api/me {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
}

location /api/subscribe {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
}

location /api/webhooks {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
}

location /api/internal {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
}

location /api/plans {
    proxy_pass http://127.0.0.1:8001;
}

location /admin {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host \$host;
}
```

Then:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Step 6 — Update vps_api.py (Video Pipeline)

Modify `/opt/video_pipeline/scripts/vps_api.py` to add quota enforcement:

**At the top of the file, add:**
```python
import sys
sys.path.insert(0, '/opt/video_pipeline')
from quota_checker import check_quota, notify_video_complete
```

**Before starting a job (in the job submission handler), add:**
```python
# Check user quota
user_id = ...  # extract from job request (add user_id to GenReq)
try:
    quota = check_quota(user_id)
    if not quota.get("allowed"):
        return {"error": "quota_exceeded", "remaining": quota.get("remaining"), "limit": quota.get("limit")}
except Exception as e:
    print(f"[vps_api] Quota check failed: {e}")  # fail open
```

**After job completes (in the job completion callback), add:**
```python
notify_video_complete(job_id=job_id, user_id=user_id, status="completed")
# or status="failed" if the build failed
```

---

## Step 7 — Update send.php (Hostinger)

Update `/public_html/api/send.php` to:
1. Accept/require user authentication (JWT from cookie)
2. Look up the user's plan/quota before submitting
3. Return 402 if quota exceeded

Or alternatively: point to the new user API which proxies to vps_api.

---

## Step 8 — Start the User API

```bash
cd /opt/video_pipeline
python3 main.py &
# Or use systemd (see Step 9)
```

Test:
```bash
curl http://127.0.0.1:8001/health
# Should return: {"status": "ok", "ts": "..."}
```

---

## Step 9 — Systemd Service (so it survives reboot)

Create `/etc/systemd/system/vybord-user-api.service`:

```ini
[Unit]
Description=Vybord User API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/video_pipeline
EnvironmentFile=/opt/video_pipeline/.env
ExecStart=/usr/bin/python3 /opt/video_pipeline/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable vybord-user-api
sudo systemctl start vybord-user-api
sudo systemctl status vybord-user-api
```

---

## Step 10 — Stripe Webhook Setup (Test Mode)

1. Install Stripe CLI: `brew install stripe/stripe-cli/stripe` (mac) or `curl https://starship.stripe.app/install | sh` (Linux)
2. Login: `stripe login`
3. Forward webhooks to your local VPS:
   ```bash
   stripe listen --forward-to 95.111.236.104:8001/api/webhooks/stripe
   ```
4. Copy the webhook signing secret (`whsec_...`) output by the command into your `.env` as `STRIPE_WEBHOOK_SECRET`
5. Update `.env` and restart the service:
   ```bash
   sudo systemctl restart vybord-user-api
   ```

---

## Admin URL

After deployment:
- **Admin panel:** `https://app.vybord.com/admin/login`
- **Health check:** `https://app.vybord.com/health`
- **User dashboard:** `https://app.vybord.com/dashboard` (after login)

---

## Stripe Price Setup (Required for Paid Plans)

For paid plans to work, you must create products + prices in Stripe Dashboard:

1. Go to https://dashboard.stripe.com/products
2. Create 3 products: "Free", "Pro" ($29/mo), "Enterprise" ($99/mo)
3. Copy each Price ID (looks like `price_xxx`)
4. Update `.env`:
   ```
   STRIPE_PRICE_IDS='{"Free": "price_xxx", "Pro": "price_yyy", "Enterprise": "price_zzz"}'
   ```
5. Restart: `sudo systemctl restart vybord-user-api`
