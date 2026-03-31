#!/usr/bin/env python3
"""
OpenClaw MCP Bridge — extended with user management, admin, and system tools.
Listens on port 8090. Forwards video calls to VPS API (8000) and auth calls to User API (8001).
"""
import os, json, subprocess, asyncio, urllib.request, urllib.error, urllib.parse
import httpx
from fastmcp import FastMCP

VPS_API = os.environ.get("VPS_API", "http://127.0.0.1:8000")
USER_API = os.environ.get("USER_API", "http://127.0.0.1:8001")
TIMEOUT = float(os.environ.get("TIMEOUT", "300"))

mcp = FastMCP("openclaw-vybord")
vps_client = httpx.AsyncClient(base_url=VPS_API, timeout=TIMEOUT)
user_client = httpx.AsyncClient(base_url=USER_API, timeout=30)


# ── helpers ──────────────────────────────────────────────────────────────────

def upload_catbox(filepath: str, job_id: str) -> str:
    with open(filepath, "rb") as f:
        req = urllib.request.Request(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (f"video_{job_id[:8]}.mp4", f, "video/mp4")},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode().strip()


def whisper_to_pycaps(transcript_path: str, out_path: str) -> dict:
    w = json.load(open(transcript_path))
    words, wid = [], 0
    for seg in w.get("segments", []):
        s, e, text = seg["start"], seg["end"], seg["text"]
        if not text:
            continue
        total = sum(len(w_) for w_ in text.split())
        if total <= 0:
            continue
        char_dur = (e - s) / total
        pos = 0
        for word in text.split():
            w_start = s + pos * char_dur
            w_end = w_start + len(word) * char_dur
            words.append({"id": wid, "text": word, "start": round(w_start, 3), "end": round(w_end, 3)})
            wid += 1
            pos += len(word) + 1
    segments = []
    for seg in w.get("segments", []):
        seg_words = [x for x in words if seg["start"] - 0.05 <= x["start"] and x["end"] <= seg["end"] + 0.05]
        if seg_words:
            segments.append({"start": round(seg["start"], 3), "end": round(seg["end"], 3), "words": seg_words})
    data = {"segments": segments}
    with open(out_path, "w") as f:
        json.dump(data, f)
    return data


async def wait_for_done(job_id: str, poll_interval: int = 10, max_wait: int = 600) -> dict:
    waited = 0
    while waited < max_wait:
        r = await vps_client.get(f"/status/{job_id}")
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        if status in ("done", "failed"):
            return data
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    return {"status": "timeout", "job_id": job_id, "error": f"Timed out after {max_wait}s"}


def _user_get(path: str, cookies: dict | None = None) -> dict:
    """GET to user API with optional cookie jar."""
    req = urllib.request.Request(f"{USER_API}{path}")
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _user_post(path: str, data: dict, cookies: dict | None = None) -> dict:
    """POST to user API."""
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{USER_API}{path}", data=body,
                                  headers={"Content-Type": "application/json"})
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _user_post_form(path: str, data: dict, cookies: dict | None = None) -> tuple[dict, dict]:
    """POST form data to user API. Returns (response_json, set_cookies)."""
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{USER_API}{path}", data=encoded,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
        # Extract Set-Cookie headers
        set_cookies = {}
        for h, v in resp.headers.items():
            if h.lower() == "set-cookie":
                parts = v.split(";")
                if parts:
                    kv = parts[0].split("=", 1)
                    if len(kv) == 2:
                        set_cookies[kv[0].strip()] = kv[1].strip()
        return result, set_cookies


# ════════════════════════════════════════════════════════════════════════════
# VIDEO TOOLS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def build_video(
    url: str = "",
    voice: str = "Sarah",
    max_images: int = 15,
    email: str = "",
    duration: int = 30,
    ratio: str = "16:9",
    effect: str = "random",
    template: str = "word-focus",
    font_size: int = 55,
    text_color: str = "#FF69B4",
    bg_color: str = "#000000",
    music: str | None = None,
    music_url: str | None = None,
    cta: str | None = None,
    script: str | None = None,
    transition: str = "smoothleft",
    images_per_slide: int = 1,
    images: str | list = "",
) -> dict:
    """Submit a video build job. Use render_video to complete with PyCaps."""
    payload = {
        "url": url or "", "voice": voice, "max_images": max_images,
        "duration": duration, "ratio": ratio, "effect": effect,
        "template": template, "font_size": font_size,
        "text_color": text_color, "bg_color": bg_color,
        "music": music or "none", "music_url": music_url or "",
        "cta": cta or "", "script": script or "",
        "transition": transition, "images_per_slide": images_per_slide,
    }
    if email:
        payload["email"] = email
    if images:
        payload["images"] = json.loads(images) if isinstance(images, str) else images
    r = await vps_client.post("/generate", json=payload)
    r.raise_for_status()
    return r.json()


@mcp.tool
async def render_video(
    job_id: str,
    template: str = "explosive",
    font_size: int = 35,
    text_color: str = "#FF1493",
) -> dict:
    """Wait for a build job to finish, run PyCaps, upload, and return the final URL."""
    WORK = f"/opt/video_pipeline/work/{job_id}"
    VIDEO_RAW = f"{WORK}/video_wna.mp4" if os.path.exists(f"{WORK}/video_wna.mp4") else f"{WORK}/video.mp4"
    VIDEO_CAPPED = f"{WORK}/video_capped.mp4"
    PYCAPS_BIN = "/opt/venv/bin/pycaps"
    TRANSCRIPT = f"{WORK}/voice_transcript.json"

    job = await wait_for_done(job_id)
    status = job.get("status", "")
    if status == "failed":
        return {"status": "failed", "job_id": job_id, "error": job.get("error", "Build failed")}
    if status == "timeout":
        return job
    if status != "done":
        return {"status": "error", "job_id": job_id, "error": f"Unexpected: {status}"}
    if not os.path.exists(VIDEO_RAW):
        return {"status": "error", "job_id": job_id, "error": f"Video not found: {VIDEO_RAW}"}
    if not os.path.exists(TRANSCRIPT):
        return {"status": "error", "job_id": job_id, "error": f"Transcript not found: {TRANSCRIPT}"}

    whisper_to_pycaps(TRANSCRIPT, f"{WORK}/voice_pycaps.json")
    cmd = [
        PYCAPS_BIN, "render", "--input", VIDEO_RAW, "--output", VIDEO_CAPPED,
        "--template", template, "--transcript", f"{WORK}/voice_pycaps.json",
        "--transcript-format", "pycaps_json",
        "--style", f"word.color={text_color}",
        "--style", f"word.fontSize={font_size}px",
        "--video-quality", "high",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"status": "error", "job_id": job_id, "error": f"PyCaps failed: {r.stderr[-500:]}"}

    video_url = upload_catbox(VIDEO_CAPPED, job_id)
    return {"status": "done", "job_id": job_id, "video_url": video_url,
            "template": template, "font_size": font_size, "text_color": text_color}


@mcp.tool
async def check_job(job_id: str) -> dict:
    """Get status and result for a job."""
    r = await vps_client.get(f"/status/{job_id}")
    r.raise_for_status()
    return r.json()


@mcp.tool
async def list_jobs() -> list:
    """List all jobs and their status."""
    r = await vps_client.get("/jobs")
    r.raise_for_status()
    return r.json()


@mcp.tool
async def health() -> dict:
    """Check bridge, VPS API, and User API health."""
    try:
        r = await vps_client.get("/health", timeout=5)
        vps_status = r.json() if r.status_code == 200 else {"error": r.text}
    except Exception as e:
        vps_status = {"error": str(e)}
    try:
        r2 = httpx.get(f"{USER_API}/health", timeout=5)
        user_status = r2.json() if r2.status_code == 200 else {"error": r2.text}
    except Exception as e:
        user_status = {"error": str(e)}
    return {"bridge": "ok", "vps_api": vps_status, "user_api": user_status,
            "vps_url": VPS_API, "user_api_url": USER_API}


# ════════════════════════════════════════════════════════════════════════════
# USER AUTH TOOLS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def user_register(email: str, password: str) -> dict:
    """Register a new user account. Returns success message."""
    payload = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/api/auth/register", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


@mcp.tool
async def user_login(email: str, password: str) -> dict:
    """Login a user. Returns user profile. Cookie is stored in the response."""
    data = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/api/auth/login", json=data, timeout=30)
    r.raise_for_status()
    resp = r.json()
    # Extract cookie from response
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()
    resp["_cookies"] = cookies
    return resp


@mcp.tool
async def user_check_quota(email: str = "", user_id: int = 0) -> dict:
    """Check a user's video quota. Requires email login or user_id."""
    if user_id > 0:
        r = httpx.get(f"{USER_API}/api/internal/check-quota/{user_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    if email:
        # Login to get cookie, then check plan
        r = httpx.post(f"{USER_API}/api/auth/login", json={"email": email, "password": "dummy"}, timeout=15)
        # Even failed login returns cookie — check quota via internal endpoint
        # Actually can't get quota without a valid session. Use user_id instead.
        return {"error": "Provide user_id instead of email, or login first"}
    return {"error": "Provide email or user_id"}


@mcp.tool
async def user_get_plan(email: str, password: str) -> dict:
    """Login and return the user's current plan and quota status."""
    data = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/api/auth/login", json=data, timeout=30)
    r.raise_for_status()
    resp = r.json()
    # Extract session cookie
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()
    if not cookies:
        return {"error": "No session cookie returned"}
    # Get plan with session cookie
    req = urllib.request.Request(f"{USER_API}/api/my/plan")
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


@mcp.tool
async def user_get_profile(email: str, password: str) -> dict:
    """Login and return the user's full profile."""
    data = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/api/auth/login", json=data, timeout=30)
    r.raise_for_status()
    return r.json()


@mcp.tool
async def user_list_videos(email: str, password: str, limit: int = 20) -> list:
    """Login and return the user's video history."""
    data = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/api/auth/login", json=data, timeout=30)
    r.raise_for_status()
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()
    req = urllib.request.Request(f"{USER_API}/api/my/videos?limit={limit}")
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ════════════════════════════════════════════════════════════════════════════
# ADMIN TOOLS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def admin_login(email: str, password: str) -> dict:
    """Login as admin. Returns session cookie for subsequent admin calls."""
    data = {"email": email, "password": password}
    r = httpx.post(f"{USER_API}/admin/login", data=data, timeout=30)
    r.raise_for_status()
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()
    resp = r.text
    return {"status": "ok" if "dashboard" in resp or r.status_code in (200, 302) else "failed",
            "_cookies": cookies, "redirect": r.headers.get("location", "")}


@mcp.tool
async def admin_list_users(search: str = "", status: str = "", plan_filter: str = "", page: int = 1) -> dict:
    """
    List all users in the admin panel.
    status: active | suspended | unverified | '' (all)
    plan_filter: plan id or '' (all)
    search: email search string
    """
    admin_email = os.environ.get("VYBORD_ADMIN_EMAIL", "make@grpid.com")
    admin_pass = os.environ.get("VYBORD_ADMIN_PASS", "")
    if not admin_pass:
        return {"error": "Set VYBORD_ADMIN_EMAIL and VYBORD_ADMIN_PASS env vars on the VPS"}

    # Login as admin
    login_data = {"email": admin_email, "password": admin_pass}
    r = httpx.post(f"{USER_API}/admin/login", data=login_data, timeout=30, follow_redirects=True)
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()

    # Fetch users page
    params = f"?page={page}"
    if search: params += f"&search={urllib.parse.quote(search)}"
    if status: params += f"&status_filter={urllib.parse.quote(status)}"
    if plan_filter: params += f"&plan_filter={urllib.parse.quote(plan_filter)}"

    req = urllib.request.Request(f"{USER_API}/admin/users{params}")
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode()
        # Extract user rows from HTML (simple parser)
        users = _parse_users_from_html(html)
        return {"users": users, "page": page, "search": search, "status": status}

@mcp.tool
async def admin_get_user(user_id: int) -> dict:
    """Get detailed info for a specific user."""
    admin_email = os.environ.get("VYBORD_ADMIN_EMAIL", "make@grpid.com")
    admin_pass = os.environ.get("VYBORD_ADMIN_PASS", "")
    if not admin_pass:
        return {"error": "Set VYBORD_ADMIN_EMAIL and VYBORD_ADMIN_PASS env vars"}

    login_data = {"email": admin_email, "password": admin_pass}
    r = httpx.post(f"{USER_API}/admin/login", data=login_data, timeout=30, follow_redirects=True)
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()
    req = urllib.request.Request(f"{USER_API}/admin/users/{user_id}")
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode()
            return {"html_length": len(html), "user_id": user_id, "note": "Parse HTML for full details"}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}


@mcp.tool
async def admin_update_user(user_id: int, is_active: bool | None = None, plan_id: int | None = None) -> dict:
    """Suspend/activate a user or change their plan. Provide is_active or plan_id."""
    admin_email = os.environ.get("VYBORD_ADMIN_EMAIL", "make@grpid.com")
    admin_pass = os.environ.get("VYBORD_ADMIN_PASS", "")
    if not admin_pass:
        return {"error": "Set VYBORD_ADMIN_EMAIL and VYBORD_ADMIN_PASS env vars"}

    login_data = {"email": admin_email, "password": admin_pass}
    r = httpx.post(f"{USER_API}/admin/login", data=login_data, timeout=30, follow_redirects=True)
    cookies = {}
    for h, v in r.headers.items():
        if h.lower() == "set-cookie":
            parts = v.split(";")
            if parts:
                kv = parts[0].split("=", 1)
                if len(kv) == 2:
                    cookies[kv[0].strip()] = kv[1].strip()

    # POST to the update endpoint
    post_data = {}
    if is_active is not None: post_data["is_active"] = 1 if is_active else 0
    if plan_id is not None: post_data["plan_id"] = plan_id
    if not post_data:
        return {"error": "Provide is_active or plan_id"}

    encoded = urllib.parse.urlencode(post_data).encode()
    req = urllib.request.Request(f"{USER_API}/admin/users/{user_id}/update", data=encoded,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req.add_header("Cookie", cookie_str)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"status": "ok", "user_id": user_id, "updated": post_data}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}


def _parse_users_from_html(html: str) -> list:
    """Extract user rows from admin users HTML table."""
    users = []
    import re
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows[1:]:  # skip header
        cells = re.findall(r"<td>(.*?)</td>", row, re.DOTALL)
        if len(cells) >= 5:
            email = re.sub(r"<[^>]+>", "", cells[0]).strip()
            plan = re.sub(r"<[^>]+>", "", cells[1]).strip()
            videos = re.sub(r"<[^>]+>", "", cells[2]).strip()
            verified = "yes" in re.sub(r"<[^>]+>", "", cells[3]).lower()
            status = "active" if "green" in cells[4].lower() else "suspended"
            users.append({"email": email, "plan": plan, "videos": videos,
                          "verified": verified, "status": status})
    return users


# ════════════════════════════════════════════════════════════════════════════
# SYSTEM TOOLS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def system_stats() -> dict:
    """Get VPS disk, memory, and active service status."""
    # Disk
    disk = subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout.strip().split("\n")
    # Memory
    mem = subprocess.run(["free", "-h"], capture_output=True, text=True).stdout.strip().split("\n")
    # Services
    services = {}
    for svc in ["vybord-user-api", "vps-api", "cloudflared"]:
        r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
        services[svc] = r.stdout.strip()
    return {"disk": disk[-1] if disk else "", "memory": mem[-1] if mem else "", "services": services}


@mcp.tool
async def system_logs(service: str = "vybord-user-api", lines: int = 20) -> dict:
    """Get recent logs for a systemd service."""
    r = subprocess.run(
        ["journalctl", "-u", service, "--no-pager", "-n", str(lines)],
        capture_output=True, text=True
    )
    return {"service": service, "logs": r.stdout[-3000:]}


@mcp.tool
async def disk_usage() -> dict:
    """Get disk usage for key directories."""
    dirs = ["/opt/video_pipeline", "/tmp", "/var/www"]
    result = {}
    for d in dirs:
        r = subprocess.run(["du", "-sh", d], capture_output=True, text=True)
        result[d] = r.stdout.strip().split("\t")[0] if r.returncode == 0 else "N/A"
    return result


@mcp.tool
async def list_jobs_detailed() -> dict:
    """List all jobs with more detail than list_jobs."""
    r = await vps_client.get("/jobs")
    r.raise_for_status()
    jobs = r.json()
    detailed = []
    for job in jobs[:20]:  # limit to 20
        try:
            rid = await vps_client.get(f"/status/{job.get('job_id', job.get('id',''))}")
            if rid.status_code == 200:
                detailed.append(rid.json())
            else:
                detailed.append(job)
        except Exception:
            detailed.append(job)
    return {"jobs": detailed, "count": len(jobs)}


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, uvicorn
    parser = argparse.ArgumentParser(description="OpenClaw MCP Bridge — Extended")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--vps-api", default=VPS_API)
    parser.add_argument("--user-api", default=USER_API)
    args = parser.parse_args()
    vps_client = httpx.AsyncClient(base_url=args.vps_api, timeout=TIMEOUT)
    user_client = httpx.AsyncClient(base_url=args.user_api, timeout=30)
    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=args.port, log_level="info")
