#!/usr/bin/env python3
"""
VPS Pipeline QA Test Script
Usage: 
  python3 qa_test.py              # unauthenticated checks only
  python3 qa_test.py --auth       # full flow with auth (needs test credentials)

Tests:
  - Public endpoints return expected status
  - Protected endpoints return 401 when unauthenticated
  - Authenticated requests work end-to-end
  - Input validation and sanitization
  - Job pipeline end-to-end
"""
import sys
import json
import time
import subprocess
import requests
import re

BASE = "http://127.0.0.1:7073"
AUTH_COOKIE = None
PASS = 0
FAIL = 0
RESULTS = []

def test(name, expected_status, method="GET", path="/", json_data=None, headers=None, cookie=None):
    global PASS, FAIL
    url = BASE + path
    h = dict(headers) if headers else {}
    if cookie:
        h['Cookie'] = cookie
    try:
        if method == "POST":
            r = requests.post(url, json=json_data, timeout=10, headers=h)
        else:
            r = requests.get(url, timeout=10, headers=h)
        ok = r.status_code == expected_status if isinstance(expected_status, int) else r.status_code in expected_status
        result = "PASS" if ok else "FAIL"
        if not ok: FAIL += 1
        else: PASS += 1
        RESULTS.append(f"[{result}] {name} → HTTP {r.status_code} (expected {expected_status})")
        if not ok:
            print(f"  Response: {r.text[:200]}")
        return ok
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name} → ERROR: {e}")
        return False

def get_test_user_cookie():
    """Register a test user, login, and return the auth cookie."""
    global AUTH_COOKIE
    ts = str(int(time.time()))
    email = f"qa_{ts}@test.com"
    password = "TestPass123!"
    try:
        # Register
        r = requests.post("http://127.0.0.1:8001/api/auth/register",
                         json={"email": email, "password": password, "name": "QA Test"},
                         timeout=10)
        if r.status_code not in (200, 201):
            print(f"  Register failed: {r.status_code} {r.text[:100]}")
            return None
        # Login
        r = requests.post("http://127.0.0.1:8001/api/auth/login",
                         json={"email": email, "password": password},
                         timeout=10,
                         allow_redirects=False)
        if r.status_code == 200:
            AUTH_COOKIE = r.cookies.get("vyb_token")
            return AUTH_COOKIE
        print(f"  Login failed: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"  Auth setup error: {e}")
    return None

def run_tests():
    global PASS, FAIL, RESULTS, AUTH_COOKIE
    PASS = 0
    FAIL = 0
    RESULTS = []
    use_auth = "--auth" in sys.argv

    print("=" * 60)
    print("VPS PIPELINE QA TEST SUITE")
    print(f"Mode: {'AUTHENTICATED (full)' if use_auth else 'ANONYMOUS (public + auth-checks)'}")
    print("=" * 60)

    # ── 0. AUTH SETUP ─────────────────────────────────────────────────
    if use_auth:
        print("\n[0] AUTH SETUP")
        cookie = get_test_user_cookie()
        if cookie:
            PASS += 1
            RESULTS.append(f"[PASS] Auth setup → cookie obtained")
            print(f"  Logged in as {email}")
        else:
            FAIL += 1
            RESULTS.append(f"[FAIL] Auth setup → could not obtain cookie")
            print("  WARNING: continuing without auth — some tests will 401")
    else:
        RESULTS.append("[--auth not set, skipping authenticated tests]")

    # ── A. PUBLIC ENDPOINTS (no auth required) ─────────────────────────
    print("\n[A] PUBLIC ENDPOINTS (no auth)")
    test("GET / review page loads", 200)
    test("POST /api/scrape valid URL", 200, method="POST", path="/api/scrape",
         json_data={"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"})
    test("POST /api/fetch-html valid URL", 200, method="POST", path="/api/fetch-html",
         json_data={"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"})

    # ── B. AUTH PROTECTION (unauthenticated → 401) ────────────────────
    print("\n[B] AUTH PROTECTION (no cookie → 401)")
    protected = [
        ("POST", "/api/send.php", {"settings": {"address": "test", "price": "100", "script": "test"}}),
        ("POST", "/api/generate", {"price": "100", "address": "test", "script": "test", "selectedIndices": [0]}),
        ("POST", "/api/build/review_test", {}),
        ("POST", "/api/upload-images/review_test", {"images": []}),
    ]
    for method, path, data in protected:
        test(f"{method} {path} unauthenticated → 401", 401, method=method, path=path, json_data=data)

    # ── C. INPUT VALIDATION ───────────────────────────────────────────
    print("\n[C] INPUT VALIDATION")
    test("/api/scrape empty URL → 400 or 500", [400, 500], method="POST", path="/api/scrape",
         json_data={"url": ""})

    # ── D. SCRAPE DATA ACCURACY ──────────────────────────────────────
    print("\n[D] SCRAPE DATA ACCURACY")
    r = requests.post(BASE + "/api/scrape", json={
        "url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"
    }, timeout=15)
    if r.status_code == 200:
        data = r.json()
        checks = [
            ("price=9500000", data.get("price", "").replace(",", "") == "9500000"),
            ("beds=9", data.get("beds") == "9"),
            ("baths=9", data.get("baths") == "9"),
            ("address contains 18770", "18770" in data.get("address", "")),
            ("images>=5", len(data.get("images", [])) >= 5),
        ]
        for label, ok in checks:
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] scrape {label}")

    # ── E. AUTHENTICATED JOB FLOW (with cookie) ───────────────────────
    if use_auth and AUTH_COOKIE:
        print("\n[E] AUTHENTICATED JOB FLOW")
        cookie = f"vyb_token={AUTH_COOKIE}"
        job_id = None

        # E1: Create job (with URL → scrape fallback)
        r = requests.post(BASE + "/api/send.php",
                         json={
                             "url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/",
                             "settings": {
                                 "address": "test",
                                 "price": "garbage_XSS<script>",
                                 "script": "test script",
                                 "voice": "Bella",
                                 "beds": "9",
                             }
                         },
                         headers={"Cookie": cookie},
                         timeout=10)
        ok = r.status_code == 200
        if ok:
            try:
                data = r.json()
                job_id = data.get("job_id", "")
                ok = bool(job_id and job_id.startswith("review_"))
            except:
                ok = False
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E1: create job (auth) → {job_id or 'FAILED'}")

        # E2: Review page loads
        if job_id:
            r2 = requests.get(BASE + f"/review/{job_id}", timeout=10)
            ok = r2.status_code == 200
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E2: review page loads → HTTP {r2.status_code}")

            # E3: Address is escaped (no raw <script>)
            ok = "<script>alert" not in r2.text and "&lt;script&gt;" in r2.text
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E3: address escaped in review page")

            # E4: Price is clean (garbage stripped → scrape used)
            ok = "9500000" in r2.text
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E4: price=9500000 in review page")

            # E5: Trigger build
            r3 = requests.post(BASE + f"/api/build/{job_id}",
                              json={},
                              headers={"Cookie": cookie},
                              timeout=5)
            ok = r3.status_code == 200 and "Building" in r3.text
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E5: /api/build → 200 + Building")

            # E6: Build idempotency (second call returns current status, not error)
            r4 = requests.post(BASE + f"/api/build/{job_id}",
                               json={},
                               headers={"Cookie": cookie},
                               timeout=5)
            ok = r4.status_code == 200 and "Building" in r4.text
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E6: /api/build idempotent → 200 + status")

            # E7: Status endpoint
            r5 = requests.get(BASE + f"/api/status/{job_id}", timeout=5)
            ok = r5.status_code == 200
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] E7: /api/status → 200")
    else:
        RESULTS.append("[SKIP] E: authenticated job flow (no --auth flag)")

    # ── F. SERVER LOG ERRORS ─────────────────────────────────────────
    print("\n[F] SERVER LOG CHECKS")
    r = requests.get(BASE + "/", timeout=5)
    ok = r.status_code == 200
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] server still responding")

    # ── G. DISK USAGE ────────────────────────────────────────────────
    print("\n[G] DISK USAGE")
    result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    line = result.stdout.strip().split("\n")[-1]
    pct = int(line.split()[4].rstrip("%"))
    ok = pct < 90
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] disk usage {pct}% (threshold 90%)")

    # ── RESULTS ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print()
    return FAIL == 0

if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
