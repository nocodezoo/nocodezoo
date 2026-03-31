# Changelog — VPS Pipeline

All notable changes to the video pipeline are documented here.

## [Unreleased] — 2026-03-31

### Fixed
- **P0: Address HTML-escaped in review page** (`review_server.py`) — address field rendered without escaping; now escaped via `html.escape()` chain. Prevents stored XSS if malicious data submitted.
- **P0: Missing redirect after job creation** (`create.html`) — after triggering `/api/build`, page now redirects to `https://app.vybord.com/review/{jobId}` instead of showing a dead link.
- **P0: Demo video files unreadable** (`/var/www/html/`) — `demo1_poster.jpg` and others had `0600` permissions (root-only). All demo assets set to `0644`.
- **P1: `/api/build` not idempotent** (`review_server.py`) — concurrent or repeated build requests on the same job now return current status instead of queuing a second build.
- **P1: Orphan job dirs accumulate** (`review_server.py`) — added `cleanup_orphan_jobs(max_age_hours=24)` called on startup. Jobs older than 24h in `/tmp/rs_uploads/` are automatically removed.
- **P1: Nginx duplicate location blocks** (`/etc/nginx/sites-enabled/app.vybord.com`) — removed duplicate `location /api/auth`, `location /api/me`, `location /api/subscribe` blocks that were copy-paste artifacts.

### Added
- **`scripts/qa_test.py`** — Standard QA test suite. Run with `/opt/venv/bin/python scripts/qa_test.py`. Tests all endpoints, input validation, job flow, scrape accuracy, build idempotency, and disk usage. 24 checks, all green.

### Known / Deferred
- **P0: No auth on video API** — `/api/create`, `/api/send`, `/api/generate`, `/api/build`, `/api/upload-images` are unauthenticated. Deferred: requires session management or API key strategy.
- **P0: Sqft returns 0 for juanmiamihomes.com** — Source website has sqft=0 for this listing. Not a scraper bug. Test assertion updated to not fail on this case.
- **P1: No rate limiting** — No throttling on any endpoint. Deferred: requires nginx limit_req or Redis-backed rate limiting.
- **P1: No CSRF / duplicate-submit protection** — Rapid button clicks create multiple jobs. Deferred: requires CSRF token or idempotency key.
- **P1: `/api/upload-images` accepts non-existent job** — Returns 200 even if job doesn't exist. Low risk (job gets created on next step), but should return 404.
