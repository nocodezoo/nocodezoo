# VERSION.md — Vybord User Management System

## v1.0.54 — 2026-04-02

### Fixed
- `scrape_listing()` (Python): juanmiamihomes.com page HTML contains images from a DIFFERENT listing (A11942169) in its JSON-LD structured data, while the actual visible gallery images are A11914388 (correct listing)
  - Added listing ID filter: extracts `A119\d+` from URL, only keeps images whose URL contains that listing ID
  - Filter applied in Python `scrape_listing()` AND in JS `parseAndShowImages()` in create.html
  - Before: 26 images returned + polluted A11942169 images mixed in
  - After: 26 images, all A11914388 (correct listing)
- `create.html` JS: same listing ID filter added to background-image extraction block

### Files Modified
- `/opt/video_pipeline/review_server.py` — added `url_listing_id` extraction + filter in `scrape_listing()` juanmiamihomes block
- `/var/www/html/create.html` — added `urlListingId` extraction + filter in `parseAndShowImages()`

### LEARNINGS
- juanmiamihomes.com has MULTIPLE listing images embedded in its HTML: correct images in `style="background-image: url(...)"` (A11914388) and wrong images in JSON-LD (A11942169)
- Always extract listing ID from URL and use it as a filter when site has inconsistent listing data across different HTML sections

## v1.0.53 — 2026-04-02

### Fixed
- VPS reboot caused `review_server.py` to revert to minimal 711-line version (missing all API handlers including `/api/scrape`, `/api/fetch-html`, `/api/send.php`, etc.)
  - Restored full 1580-line version from git commit `96f4918`
  - Re-applied `background-image` regex fix: `r'url\("?([^)]+)"?\)'` (was reverted to buggy `r'url\("?([^\)"]+)"?\)'`)

### Files Modified
- `/opt/video_pipeline/review_server.py` — restored from git, regex fixed at line 505

### LEARNINGS
- VPS reboot restored `review_server.py` from an older source — the full version with all changes existed only on disk (not committed to git)
- Always commit changes to git before rebooting; or better: use a deployment script that copies the file to a known location as part of startup

## v1.0.52 — 2026-04-02

### Fixed
- `create.html` `parseAndShowImages()`: missing `background-image` CSS extraction — images on sites like juanmiamihomes.com that use inline `style="background-image: url(...)"` were invisible to the client-side parser
  - Added new extraction block: regex matches inline styles containing `background-image: url(...)`, extracts the URL, validates extension and filters logos/icons

### Files Modified
- `var/www/html/create.html` — added `background-image` CSS URL extraction block in `parseAndShowImages()` before `cdnMatches` block

### LEARNINGS
- `scrape_listing()` (Python) and `parseAndShowImages()` (JS) were out of sync — fix to one didn't reach the other
- Lesson: when site has two rendering paths (server-side Python vs client-side JS), both need the same extraction logic

## v1.0.51 — 2026-04-02

### Fixed
- `review_server.py` `scrape_listing()`: background-image regex was excluding `"` chars from capture group, returning 0 images for sites like juanmiamihomes.com that use unquoted CSS `url(...)` syntax
  - Old: `r'url\("?([^\)"]+)"?\)'` — stops at first `"` inside the URL
  - New: `r'url\("?([^)]+)"?\)'` — captures everything up to `)` regardless of quotes

### Files Modified
- `review_server.py` — line ~496: fixed regex in `scrape_listing()` juanmiamihomes.com image extraction block

### LEARNINGS
- CSS `background-image: url(https://...)` never has quotes inside the url(), so the character class `[^\)"]` was wrong — it excluded the `"` that terminates the URL, making the capture stop prematurely
- Always test regex against actual HTML source, not assumptions about format

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
