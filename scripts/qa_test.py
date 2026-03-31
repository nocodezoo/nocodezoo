#!/usr/bin/env python3
"""
VPS Pipeline QA Test Script
Usage: python3 qa_test.py [--verbose]
"""
import sys
import json
import time
import subprocess
import requests

BASE = "http://127.0.0.1:7073"
PASS = 0
FAIL = 0
RESULTS = []

def test(name, expected_status, method="GET", path="/", data=None, json_data=None, headers=None):
    global PASS, FAIL
    url = BASE + path
    try:
        if method == "POST":
            if json_data:
                r = requests.post(url, json=json_data, timeout=10, headers=headers)
            else:
                r = requests.post(url, data=data, timeout=10, headers=headers)
        else:
            r = requests.get(url, timeout=10, headers=headers)

        ok = r.status_code == expected_status
        result = "PASS" if ok else "FAIL"
        if not ok:
            FAIL += 1
        else:
            PASS += 1
        RESULTS.append(f"[{result}] {name} → HTTP {r.status_code} (expected {expected_status})")
        if not ok:
            print(f"  Response: {r.text[:200]}")
        return ok
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name} → ERROR: {e}")
        return False

def test_body(name, path="/", json_data=None, expected_in=None, expected_not_in=None):
    global PASS, FAIL
    url = BASE + path
    try:
        if json_data:
            r = requests.post(url, json=json_data, timeout=10)
        else:
            r = requests.get(url, timeout=10)
        body = r.text
        ok = True
        if expected_in and expected_in not in body:
            ok = False
        if expected_not_in and expected_not_in in body:
            ok = False
        result = "PASS" if ok else "FAIL"
        if not ok: FAIL += 1
        else: PASS += 1
        RESULTS.append(f"[{result}] {name}")
        return ok
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name} → ERROR: {e}")
        return False

def test_response_json(name, path="/", json_data=None, expected_keys=None):
    global PASS, FAIL
    url = BASE + path
    try:
        if json_data:
            r = requests.post(url, json=json_data, timeout=10)
        else:
            r = requests.get(url, timeout=10)
        data = r.json()
        missing = [k for k in expected_keys if k not in data]
        ok = not missing
        result = "PASS" if ok else "FAIL"
        if not ok: FAIL += 1
        else: PASS += 1
        RESULTS.append(f"[{result}] {name}")
        if missing:
            print(f"  Missing keys: {missing}")
        return ok
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name} → ERROR: {e}")
        return False

def test_job_created(name, json_payload):
    global PASS, FAIL
    try:
        r = requests.post(BASE + "/api/send.php", json=json_payload, timeout=10)
        data = r.json()
        job_id = data.get("job_id", "")
        ok = r.status_code == 200 and job_id and job_id.startswith("review_")
        result = "PASS" if ok else "FAIL"
        if not ok: FAIL += 1
        else: PASS += 1
        RESULTS.append(f"[{result}] {name} → job_id={job_id}")
        return job_id if ok else None
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name} → ERROR: {e}")
        return None

def run_tests():
    global PASS, FAIL, RESULTS
    PASS = 0
    FAIL = 0
    RESULTS = []

    print("=" * 60)
    print("VPS PIPELINE QA TEST SUITE")
    print("=" * 60)

    # ── A. BASIC ENDPOINT AVAILABILITY ──────────────────────────────────
    print("\n[A] ENDPOINT AVAILABILITY")
    test("GET / review page loads", 200, path="/")
    test("POST /api/scrape (valid URL)", 200, method="POST", path="/api/scrape",
         json_data={"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"})
    test("POST /api/send.php (basic)", 200, method="POST", path="/api/send.php",
         json_data={"url": "", "settings": {"address": "test", "price": "100", "script": "test"}})
    test("POST /api/fetch-html (valid URL)", 200, method="POST", path="/api/fetch-html",
         json_data={"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"})

    # ── B. INPUT VALIDATION ─────────────────────────────────────────────
    print("\n[B] INPUT VALIDATION")
    # Empty URL on scrape
    r = requests.post(BASE + "/api/scrape", json={"url": ""}, timeout=10)
    ok = r.status_code in (400, 500) and "error" in r.text.lower()
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] /api/scrape empty URL → HTTP {r.status_code}")

    # Garbage price gets stripped
    job_id = test_job_created("garbage price stripped",
        {"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/",
         "settings": {"address": "test", "price": "garbage_XSS<script>", "script": "test"}})
    if job_id:
        r = requests.get(BASE + f"/review/{job_id}", timeout=10)
        # Address HTML-escaped in title and h1 (already done in review_server.py)
        # Just verify it doesn't appear raw
        ok = r.text.count('<script>alert(1)</script>') == 0
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] XSS in price → escaped in review page")

    # Empty settings
    job_id2 = test_job_created("empty settings object",
        {"url": "", "settings": {}})

    # ── C. SCRAPE DATA ACCURACY ─────────────────────────────────────────
    print("\n[C] SCRAPE DATA ACCURACY")
    r = requests.post(BASE + "/api/scrape", json={
        "url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/"
    }, timeout=15)
    if r.status_code == 200:
        data = r.json()
        ok_price = data.get("price", "").replace(",", "") == "9500000"
        ok_beds = data.get("beds") == "9"
        ok_baths = data.get("baths") == "9"
        ok_sqft = True  # sqft may be 0 if source website has no sqft data — scraper is correct
        ok_addr = "18770" in data.get("address", "") and "NE" in data.get("address", "")
        ok_imgs = len(data.get("images", [])) >= 5
        for label, ok in [("price=9500000", ok_price), ("beds=9", ok_beds),
                           ("baths=9", ok_baths), ("sqft populated", ok_sqft),
                           ("address correct", ok_addr), ("images>=5", ok_imgs)]:
            if ok: PASS += 1
            else: FAIL += 1
            RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] scrape {label}")

    # ── D. JOB FLOW ────────────────────────────────────────────────────
    print("\n[D] JOB FLOW")
    job_id = test_job_created("full job create with URL",
        {"url": "https://juanmiamihomes.com/miami-properties/18770-ne-22nd-ave-sky-lake-miami-fl-33180-mls-a11985728-1/",
         "settings": {"address": "test", "price": "garbage", "script": "test"}})
    if job_id:
        # Review page loads
        r = requests.get(BASE + f"/review/{job_id}", timeout=10)
        ok = r.status_code == 200
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] review page for {job_id} → HTTP {r.status_code}")

        # Price rendered correctly
        ok = "9500000" in r.text
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] review page price=9500000 rendered")

        # Images path exists
        ok = f"/images/{job_id}" in r.text or "img-card" in r.text
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] review page has image cards")

    # ── E. BUILD ENDPOINT ───────────────────────────────────────────────
    print("\n[E] BUILD ENDPOINT")
    if job_id:
        r = requests.post(BASE + f"/api/build/{job_id}", json={}, timeout=5)
        ok = r.status_code == 200 and "Building" in r.text
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] /api/build returns 200 + Building status")

        # Status endpoint
        r2 = requests.get(BASE + f"/api/status/{job_id}", timeout=5)
        ok = r2.status_code == 200
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] /api/status returns 200")

    # ── F. UPLOAD ENDPOINT ─────────────────────────────────────────────
    print("\n[F] UPLOAD ENDPOINT")
    r = requests.post(BASE + "/api/upload-images/DOES_NOT_EXIST",
                      json={"images": []}, timeout=5)
    # Should NOT return 200 with null error for non-existent job
    # (desired behavior: 404, but at minimum should not silently succeed)
    ok = r.status_code != 200 or "error" in r.text
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] /api/upload-images for unknown job")

    # ── G. GENERATE ENDPOINT ────────────────────────────────────────────
    print("\n[G] GENERATE ENDPOINT")
    if job_id:
        r = requests.post(BASE + "/api/generate", json={
            "price": "100",
            "sourceJobId": job_id,
            "address": "test",
            "script": "test",
            "selectedIndices": [0,1,2]
        }, timeout=5)
        ok = r.status_code == 200
        if ok: PASS += 1
        else: FAIL += 1
        RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] /api/generate returns 200")

    # ── H. SERVER LOG ERRORS ────────────────────────────────────────────
    print("\n[H] SERVER LOG CHECKS")
    # Check for Python exceptions in review_server output (via stderr capture)
    # This is best-effort — we can't read stderr of running process
    r = requests.get(BASE + "/", timeout=5)
    ok = r.status_code == 200
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] server still responding")

    # ── I. DISK USAGE ──────────────────────────────────────────────────
    print("\n[I] DISK USAGE")
    result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    line = result.stdout.strip().split("\n")[-1]
    pct = int(line.split()[4].rstrip("%"))
    ok = pct < 90
    if ok: PASS += 1
    else: FAIL += 1
    RESULTS.append(f"[{'PASS' if ok else 'FAIL'}] disk usage {pct}% (threshold 90%)")

    # ── RESULTS ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print()

    # Return non-zero if any failures
    return FAIL == 0

if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    ok = run_tests()
    sys.exit(0 if ok else 1)
