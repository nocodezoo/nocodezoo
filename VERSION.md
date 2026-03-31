# VERSION.md — Vybord User Management System

## v1.0.0 — 2026-03-29

### Added
- Full user management system: registration, login, logout, email verification
- Subscription plans: Free (3/mo), Pro ($29/mo), Enterprise ($99/mo)
- Stripe Checkout integration (test mode) for paid subscriptions
- Stripe webhook handlers: checkout.session.completed, subscription.updated, invoice.payment_failed
- Video quota enforcement with monthly reset logic
- Admin panel: dashboard, user management, plan management, payment log
- `/api/internal/check-quota/{user_id}` — called by vps_api.py before starting jobs
- `/api/internal/video-complete` — called by vps_api.py after job completes
- Quota check client library: `quota_checker.py`
- SQLite database with: users, plans, videos, payments, stripe_events tables
- JWT in httpOnly cookies (secure, XSS-safe)
- bcrypt password hashing with salt

### Files Added
- `vybord-user-api/database.py` — SQLite + table init + query helpers
- `vybord-user-api/models.py` — Pydantic schemas
- `vybord-user-api/auth.py` — JWT, bcrypt, cookie helpers, dependency injectors
- `vybord-user-api/stripe_utils.py` — Stripe Checkout + webhook handlers
- `vybord-user-api/quota_checker.py` — Quota check + video-complete client
- `vybord-user-api/main.py` — FastAPI app (all routes)
- `vybord-user-api/templates/admin/*.html` — Admin panel templates
- `vybord-user-api/.env.example` — Environment variable template
- `vybord-user-api/DEPLOY.md` — Step-by-step deployment guide
- `vybord-user-api/VPS_API_PATCH.md` — Integration patch for vps_api.py
- `vybord-user-api/vybord-user-api.service` — systemd service file

### Modified
- `scripts/build_vps.py` — (unchanged; integration happens via vps_api.py patch)
- `DEPLOY.md` — documents nginx routing, systemd setup, Stripe CLI webhook forwarding

### Dependencies Added (VPS)
- fastapi, uvicorn[standard], pydantic, email-validator, bcrypt, PyJWT, stripe, python-multipart, jinja2, aiofiles
