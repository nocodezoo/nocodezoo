# Vybord Issue & Resolution Tracker

**GitHub Issues:** https://github.com/nocodezoo/vybord-issues/issues
**Local repo:** `/opt/video_pipeline_v3/`

---

## Quick Index

| # | Priority | Title | Status |
|---|----------|-------|--------|
| 1 | P0 | Image download fails on most listing sites (403/empty files) | FIXED |
| 2 | P1 | pycaps CLI crashes when video has no audio stream | WORKAROUND |
| 3 | P1 | build_vps.py hardcodes Bella voice instead of reading from job config | OPEN |
| 4 | P2 | VPS disk space management — venv cache and browser caches | FIXED |

---

## Issue #1 — [P0] Image download fails on most listing sites

**Symptom:** Job ID returns instantly. Review page shows no images. Slides fail.

**Root Cause:** `urllib.request.urlretrieve(url)` with no User-Agent, no timeout. Most listing sites block bare requests.

**Affected:** `review_server.py` line ~2360 (generate API) and line ~3257 (scrape API)

**Fix Applied 2026-04-23:**
```python
import urllib.request
req = urllib.request.Request(img_url, headers={
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
})
with urllib.request.urlopen(req, timeout=15) as resp:
    content_type = resp.headers.get('Content-Type', 'image/jpeg')
    ext = 'webp' if 'webp' in content_type else 'jpg'
    actual_fname = fname.replace('.jpg', f'.{ext}')
    (img_dir / actual_fname).write_bytes(resp.read())
```

**Prevention:** When adding ANY new URL-to-file download in the pipeline, always include browser User-Agent header.

---

## Issue #2 — [P1] pycaps CLI crashes when video has no audio stream

**Symptom:** pycaps silently fails — no captions burned, no error, output identical to input.

**Root Cause:** `asyncio.run()` wrapping Playwright sync API + string-concat bug in pycaps error path.

**Workaround:** Use `burn_captions.py` pattern — call `pipeline.run()` directly without `asyncio.run()`.

**Prevention:** Ensure all videos have an AAC audio track before running pycaps.

---

## Issue #3 — [P1] build_vps.py hardcodes Bella voice

**Symptom:** Generated videos always use Bella voice regardless of UI selection.

**Root Cause:** `build_vps.py` does not read `voice` from `pipeline_config.json`.

**Status:** OPEN — not yet patched.

---

## Issue #4 — [P2] VPS disk space management

**Symptom:** "Disk full" errors, builds failing.

**Root Cause:** uv cache (~11GB), browser caches (~3GB), old job dirs in /tmp.

**Fix Commands:**
```bash
uv cache clean
rm -rf ~/.cache/camoufox ~/.cache/puppeteer ~/.cache/playwright ~/.cache/ms-playwright
```

**Prevention:** Cron job to clean /tmp/rs_uploads older than 7 days.

---

*Last updated: 2026-04-23*
