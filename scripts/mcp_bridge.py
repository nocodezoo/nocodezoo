#!/usr/bin/env python3
"""
OpenClaw MCP Unified Bridge
- Original home.* video pipeline tools
- Plus: VPS MCP tools (sysadmin, video, review, email) via subprocess stdio
Listens on port 8090.
"""
import os, sys, json, subprocess, asyncio, urllib.request, urllib.error, urllib.parse
import httpx
from fastmcp import FastMCP

VPS_API   = os.environ.get("VPS_API",   "http://127.0.0.1:8000")
USER_API  = os.environ.get("USER_API",  "http://127.0.0.1:8001")
REVIEW_API = os.environ.get("REVIEW_API", "http://127.0.0.1:7073")
TIMEOUT   = float(os.environ.get("TIMEOUT", "300"))

mcp = FastMCP("openclaw-vybord")
vps_client = httpx.AsyncClient(base_url=VPS_API, timeout=TIMEOUT)


# ════════════════════════════════════════════════════════════════════════════
# MCP SUBPROCESS BRIDGE — talk to VPS stdio MCP servers
# ════════════════════════════════════════════════════════════════════════════

def _mcp_call(script: str, tool: str, args: dict) -> dict:
    """Call a stdio MCP tool and return its result dict."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args}
    }
    try:
        proc = subprocess.run(
            ["python3", script],
            input=json.dumps(payload).encode(),
            capture_output=True, timeout=30
        )
        out = proc.stdout.strip()
        if not out:
            return {"error": f"No output from {tool}", "stderr": proc.stderr.decode()[-200:]}
        resp = json.loads(out)
        if "error" in resp:
            return resp["error"]
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "{}") if content else "{}"
        return json.loads(text)
    except subprocess.TimeoutExpired:
        return {"error": f"{tool} timed out after 30s"}
    except Exception as e:
        return {"error": str(e)}


def _mcp_list_tools(script: str) -> list:
    """List tools available from a stdio MCP server."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    try:
        proc = subprocess.run(
            ["python3", script], input=json.dumps(payload).encode(),
            capture_output=True, timeout=10
        )
        resp = json.loads(proc.stdout.strip())
        return resp.get("result", {}).get("tools", [])
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

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
        if not text: continue
        total = sum(len(w_) for w_ in text.split())
        if total <= 0: continue
        char_dur = (e - s) / total
        pos = 0
        for word in text.split():
            w_start = s + pos * char_dur
            w_end   = w_start + len(word) * char_dur
            words.append({"id": wid, "text": word, "start": round(w_start, 3), "end": round(w_end, 3)})
            wid  += 1
            pos  += len(word) + 1
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
        if data.get("status") in ("done", "failed"):
            return data
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    return {"status": "timeout", "job_id": job_id}


# ════════════════════════════════════════════════════════════════════════════
# VIDEO TOOLS (home.*)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def build_video(
    url: str = "", voice: str = "Sarah", max_images: int = 15,
    email: str = "", duration: int = 30, ratio: str = "16:9",
    effect: str = "random", template: str = "word-focus",
    font_size: int = 55, text_color: str = "#FF69B4", bg_color: str = "#000000",
    music: str | None = None, music_url: str | None = None,
    cta: str | None = None, script: str | None = None,
    transition: str = "smoothleft", images_per_slide: int = 1,
    images: str | list = "",
) -> dict:
    payload = {
        "url": url or "", "voice": voice, "max_images": max_images,
        "duration": duration, "ratio": ratio, "effect": effect,
        "template": template, "font_size": font_size,
        "text_color": text_color, "bg_color": bg_color,
        "music": music or "none", "music_url": music_url or "",
        "cta": cta or "", "script": script or "",
        "transition": transition, "images_per_slide": images_per_slide,
    }
    if email:   payload["email"]   = email
    if images:  payload["images"]  = json.loads(images) if isinstance(images, str) else images
    r = await vps_client.post("/generate", json=payload)
    r.raise_for_status()
    return r.json()


@mcp.tool
async def render_video(
    job_id: str, template: str = "explosive",
    font_size: int = 35, text_color: str = "#FF1493",
) -> dict:
    WORK = f"/opt/video_pipeline/work/{job_id}"
    VIDEO_RAW   = f"{WORK}/video_wna.mp4" if os.path.exists(f"{WORK}/video_wna.mp4") else f"{WORK}/video.mp4"
    VIDEO_CAPPED = f"{WORK}/video_capped.mp4"
    PYCAPS       = "/opt/venv/bin/pycaps"
    TRANSCRIPT   = f"{WORK}/voice_transcript.json"

    job = await wait_for_done(job_id)
    status = job.get("status", "")
    if status == "failed":   return {"status": "failed",  "job_id": job_id, "error": job.get("error")}
    if status == "timeout":  return {"status": "timeout",  "job_id": job_id}
    if status != "done":     return {"status": "error",    "job_id": job_id, "error": f"Unexpected: {status}"}
    if not os.path.exists(VIDEO_RAW):    return {"status": "error", "job_id": job_id, "error": "Video not found"}
    if not os.path.exists(TRANSCRIPT):    return {"status": "error", "job_id": job_id, "error": "Transcript not found"}

    whisper_to_pycaps(TRANSCRIPT, f"{WORK}/voice_pycaps.json")
    r = subprocess.run(
        [PYCAPS, "render", "--input", VIDEO_RAW, "--output", VIDEO_CAPPED,
         "--template", template, "--transcript", f"{WORK}/voice_pycaps.json",
         "--transcript-format", "pycaps_json",
         "--style", f"word.color={text_color}",
         "--style", f"word.fontSize={font_size}px",
         "--video-quality", "high"],
        capture_output=True, text=True, timeout=600
    )
    if r.returncode != 0:
        return {"status": "error", "job_id": job_id, "error": f"PyCaps failed: {r.stderr[-500:]}"}

    video_url = upload_catbox(VIDEO_CAPPED, job_id)
    return {"status": "done", "job_id": job_id, "video_url": video_url,
            "template": template, "font_size": font_size, "text_color": text_color}


@mcp.tool
async def check_job(job_id: str) -> dict:
    r = await vps_client.get(f"/status/{job_id}")
    r.raise_for_status()
    return r.json()


@mcp.tool
async def list_jobs() -> list:
    r = await vps_client.get("/jobs")
    r.raise_for_status()
    return r.json()


@mcp.tool
async def health() -> dict:
    try:
        r = await vps_client.get("/health", timeout=5)
        vps_status = r.json() if r.status_code == 200 else {"error": r.text}
    except Exception as e:
        vps_status = {"error": str(e)}
    try:
        req = urllib.request.Request(f"{USER_API}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            user_status = json.loads(resp.read())
    except Exception as e:
        user_status = {"error": str(e)}
    try:
        req2 = urllib.request.Request(f"{REVIEW_API}/api/health")
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            review_status = json.loads(resp2.read())
    except Exception as e:
        review_status = {"error": str(e)}
    return {"bridge": "ok", "vps_api": vps_status, "user_api": user_status,
            "review_api": review_status, "vps_url": VPS_API}


# ════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT TOOLS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def user_register(email: str, password: str) -> dict:
    body = json.dumps({"email": email, "password": password}).encode()
    req  = urllib.request.Request(f"{USER_API}/api/auth/register", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


@mcp.tool
async def user_login(email: str, password: str) -> dict:
    body = json.dumps({"email": email, "password": password}).encode()
    req  = urllib.request.Request(f"{USER_API}/api/auth/login", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


@mcp.tool
async def user_check_quota(user_id: int) -> dict:
    req = urllib.request.Request(f"{USER_API}/api/internal/check-quota/{user_id}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@mcp.tool
async def user_get_plan(email: str, password: str) -> dict:
    body  = json.dumps({"email": email, "password": password}).encode()
    req   = urllib.request.Request(f"{USER_API}/api/auth/login", data=body,
                                   headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15):
        pass
    cookies = {}
    # Re-open and capture cookies
    body = json.dumps({"email": email, "password": password}).encode()
    req2 = urllib.request.Request(f"{USER_API}/api/auth/login", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req2, timeout=15) as resp:
        for h, v in resp.headers.items():
            if h.lower() == "set-cookie":
                parts = v.split(";")
                if parts:
                    kv = parts[0].split("=", 1)
                    if len(kv) == 2:
                        cookies[kv[0].strip()] = kv[1].strip()
    if not cookies:
        return {"error": "No session cookie"}
    req3 = urllib.request.Request(f"{USER_API}/api/my/plan")
    req3.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
    with urllib.request.urlopen(req3, timeout=15) as resp:
        return json.loads(resp.read())


@mcp.tool
async def user_get_profile(email: str, password: str) -> dict:
    body = json.dumps({"email": email, "password": password}).encode()
    req  = urllib.request.Request(f"{USER_API}/api/auth/login", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15):
        pass
    cookies = {}
    body = json.dumps({"email": email, "password": password}).encode()
    req2 = urllib.request.Request(f"{USER_API}/api/auth/login", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req2, timeout=15) as resp:
        for h, v in resp.headers.items():
            if h.lower() == "set-cookie":
                parts = v.split(";")
                if parts:
                    kv = parts[0].split("=", 1)
                    if len(kv) == 2:
                        cookies[kv[0].strip()] = kv[1].strip()
    req3 = urllib.request.Request(f"{USER_API}/api/me")
    req3.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
    with urllib.request.urlopen(req3, timeout=15) as resp:
        return json.loads(resp.read())


# ════════════════════════════════════════════════════════════════════════════
# FREE LOCAL MCP SERVERS (no API key needed)
# ════════════════════════════════════════════════════════════════════════════

# NOTE: puppeteer removed — it requires Chromium download which hangs on small VPS
# filesystem: list/read/write/move/remove files on /opt/video_pipeline
# sequential-thinking: structured reasoning
# everything: search across indexed content
MCP_SERVERS = {
    "filesystem": {
        "cmd": ["mcp-server-filesystem", "/opt/video_pipeline"],
        "env": {},
    },
    "puppeteer": {
        "cmd": ["/usr/bin/mcp-server-puppeteer"],
        "env": {},
    },
    "sequential-thinking": {
        "cmd": ["mcp-server-sequential-thinking"],
        "env": {},
    },
    "everything": {
        "cmd": ["mcp-server-everything", "stdio"],
        "env": {},
    },
}

def _mcp_stdio_call(server_key: str, tool_name: str, arguments: dict) -> dict:
    """Call a local stdio MCP server tool."""
    srv = MCP_SERVERS.get(server_key)
    if not srv:
        return {"error": f"Unknown server: {server_key}"}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }

    try:
        env = dict(os.environ)
        env.update(srv.get("env", {}))
        proc = subprocess.run(
            srv["cmd"],
            input=json.dumps(payload).encode(),
            capture_output=True, timeout=60,
            env=env,
            bufsize=0
        )
        out = proc.stdout.strip()
        if not out:
            return {"error": f"No output from {server_key}/{tool_name}", "stderr": proc.stderr.decode()[-300:]}

        resp = json.loads(out)
        if "error" in resp:
            return resp["error"]

        result = resp.get("result", {})
        content = result.get("content", [{}])
        if isinstance(content, list) and content:
            text = content[0].get("text", "{}") if isinstance(content[0], dict) else str(content[0])
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"result": text, "_raw": content}
        return result
    except subprocess.TimeoutExpired:
        return {"error": f"{server_key}/{tool_name} timed out after 60s"}
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════════════════

# ===== PYTHON CDP BROWSER AUTOMATION (native Chrome DevTools Protocol)

async def _cdp_navigate(url: str, port: int = 9222) -> dict:
    import asyncio, subprocess, os, tempfile, shutil, json, urllib.request, websockets
    
    user_data_dir = tempfile.mkdtemp(prefix="cdp_")
    chrome = "/root/.cache/puppeteer/chrome/linux-131.0.6778.204/chrome-linux64/chrome"
    cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
           "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}",
           "--window-size=800,600"]
    env = dict(os.environ)
    env["DISPLAY"] = ":99"
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(30):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://localhost:{port}/json", timeout=1).read())
                if tabs:
                    ws_url = tabs[0]["webSocketDebuggerUrl"].replace("ws://localhost", "ws://127.0.0.1")
                    break
            except:
                pass
            await asyncio.sleep(0.5)
        if not ws_url:
            return {"error": "Chrome did not start"}
        
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
            deadline = asyncio.get_event_loop().time() + 30
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time()))
                    if msg.get("id") == 1:
                        if "error" in msg:
                            return {"error": msg["error"]}
                        break
                except:
                    break
        await asyncio.sleep(2)
        return {"success": True, "url": url}
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        shutil.rmtree(user_data_dir, ignore_errors=True)

async def _cdp_screenshot(url: str = "", full_page: bool = False, path: str = "/tmp/cdp_shot.png", port: int = 9222) -> dict:
    import asyncio, subprocess, os, tempfile, shutil, json, urllib.request, base64, websockets
    
    user_data_dir = tempfile.mkdtemp(prefix="cdp_")
    chrome = "/root/.cache/puppeteer/chrome/linux-131.0.6778.204/chrome-linux64/chrome"
    cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
           "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}",
           "--window-size=800,600"]
    env = dict(os.environ)
    env["DISPLAY"] = ":99"
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(30):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://localhost:{port}/json", timeout=1).read())
                if tabs:
                    ws_url = tabs[0]["webSocketDebuggerUrl"].replace("ws://localhost", "ws://127.0.0.1")
                    break
            except:
                pass
            await asyncio.sleep(0.5)
        if not ws_url:
            return {"error": "Chrome did not start"}
        
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            if url:
                await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
                deadline = asyncio.get_event_loop().time() + 30
                while True:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time()))
                        if msg.get("id") == 1:
                            if "error" in msg:
                                return {"error": msg["error"]}
                            break
                    except:
                        break
                await asyncio.sleep(2)
            
            await ws.send(json.dumps({"id": 2, "method": "Page.captureScreenshot",
                                      "params": {"format": "png", "captureBeyondViewport": full_page}}))
            deadline = asyncio.get_event_loop().time() + 15
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time()))
                    if msg.get("id") == 2:
                        if "error" in msg:
                            return {"error": msg.get("error")}
                        img_data = base64.b64decode(msg["result"]["data"])
                        with open(path, "wb") as f:
                            f.write(img_data)
                        return {"success": True, "path": path, "size_bytes": len(img_data), "url": url or "current"}
                except:
                    break
        return {"error": "No screenshot response"}
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        shutil.rmtree(user_data_dir, ignore_errors=True)

def _run_cdp(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                fut = pool.submit(asyncio.run, coro)
                return fut.result(timeout=60)
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

@mcp.tool
async def browser_navigate(url: str) -> dict:
    return _run_cdp(_cdp_navigate(url))

@mcp.tool
async def browser_screenshot(url: str = "", full_page: bool = False) -> dict:
    return _run_cdp(_cdp_screenshot(url=url, full_page=full_page))

@mcp.tool
async def browser_click(selector: str) -> dict:
    return {"error": "Use browser_evaluate with JS click"}

@mcp.tool
async def browser_fill(selector: str, value: str) -> dict:
    return {"error": "Use browser_evaluate with JS fill"}

@mcp.tool
async def browser_select(selector: str, value: str) -> dict:
    return {"error": "Use browser_evaluate with JS select"}

@mcp.tool
async def browser_hover(selector: str) -> dict:
    return {"error": "Use browser_evaluate with JS hover"}

@mcp.tool
async def browser_evaluate(script: str) -> dict:
    return {"error": "CDP evaluate not yet implemented"}


# FILESYSTEM MCP TOOLS (mcp-server-filesystem)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def fs_read_file(path: str) -> dict:
    """Read a file from the VPS filesystem."""
    return _mcp_stdio_call("filesystem", "read_file", {"path": path})

@mcp.tool
async def fs_write_file(path: str, content: str) -> dict:
    """Write content to a file on the VPS."""
    return _mcp_stdio_call("filesystem", "write_file", {"path": path, "content": content})

@mcp.tool
async def fs_list_directory(path: str) -> dict:
    """List files in a VPS directory."""
    return _mcp_stdio_call("filesystem", "list_directory", {"path": path})

@mcp.tool
async def fs_create_directory(path: str) -> dict:
    """Create a directory on the VPS."""
    return _mcp_stdio_call("filesystem", "create_directory", {"path": path})

@mcp.tool
async def fs_move_file(source: str, destination: str) -> dict:
    """Move/rename a file on the VPS."""
    return _mcp_stdio_call("filesystem", "move_file", {"source": source, "destination": destination})

@mcp.tool
async def fs_remove_file(path: str) -> dict:
    """Delete a file from the VPS."""
    return _mcp_stdio_call("filesystem", "remove_file", {"path": path})


# ════════════════════════════════════════════════════════════════════════════
# SEQUENTIAL THINKING MCP TOOL (mcp-server-sequential-thinking)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool
async def think(query: str, depth: int = 3) -> dict:
    """Structured reasoning tool. Breaks down complex problems step by step."""
    return _mcp_stdio_call("sequential-thinking", "sequentialthinking",
                           {"query": query, "depth": depth})


# ════════════════════════════════════════════════════════════════════════════
# EVERYTHING MCP TOOLS (mcp-server-everything — search + data)
# ════════════════════════════════════════════════════════════════════════════



@mcp.tool
async def vps_disk_usage() -> dict:
    """Get VPS disk usage for all mounted filesystems."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "disk_usage", {})


@mcp.tool
async def vps_ssl_check(domain: str, port: int = 443) -> dict:
    """Check SSL certificate for a domain. Returns days until expiry."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "ssl_check", {"domain": domain, "port": port})


@mcp.tool
async def vps_uptime_check(domain: str) -> dict:
    """Check if a host is reachable on port 443."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "uptime_check", {"domain": domain})


@mcp.tool
async def vps_service_status(service: str) -> dict:
    """Check status of a systemd service. e.g. nginx, vybord-user-api, vps-api, cloudflared."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "service_status", {"service": service})


@mcp.tool
async def vps_restart_service(service: str) -> dict:
    """Restart a systemd service. e.g. nginx, vybord-user-api, vps-api."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "restart_service", {"service": service})


@mcp.tool
async def vps_tail_log(path: str = "/var/log/nginx/access.log", lines: int = 30) -> dict:
    """Tail a log file on the VPS. e.g. path=/var/log/nginx/error.log"""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "tail_log", {"path": path, "lines": lines})


@mcp.tool
async def vps_nginx_reload() -> dict:
    """Reload nginx configuration."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "nginx_reload", {})


@mcp.tool
async def vps_nginx_test() -> dict:
    """Test nginx configuration syntax."""
    return _mcp_call("/usr/local/bin/mcp-sysadmin", "nginx_test", {})


@mcp.tool
async def vps_generate_video(
    address: str, script: str = "",
    price: str = "", beds: str = "", baths: str = "", sqft: str = "",
    voice: str = "Bella", music: str = "upbeat", duration: int = 45,
) -> dict:
    """Generate a review video via the VPS video pipeline."""
    return _mcp_call("/usr/local/bin/mcp-video-pipeline", "generate_video", {
        "address": address, "script": script, "price": price,
        "beds": beds, "baths": baths, "sqft": sqft,
        "voice": voice, "music": music, "duration": duration,
    })


@mcp.tool
async def vps_job_status(job_id: str) -> dict:
    """Get status of a review job."""
    return _mcp_call("/usr/local/bin/mcp-video-pipeline", "job_status", {"job_id": job_id})


@mcp.tool
async def vps_list_jobs() -> dict:
    """List recent review jobs."""
    return _mcp_call("/usr/local/bin/mcp-video-pipeline", "list_jobs", {})


@mcp.tool
async def vps_get_video(job_id: str) -> dict:
    """Get download link for a completed video."""
    return _mcp_call("/usr/local/bin/mcp-video-pipeline", "get_video", {"job_id": job_id})


@mcp.tool
async def vps_video_system_status() -> dict:
    """Get VPS system status via video pipeline MCP."""
    return _mcp_call("/usr/local/bin/mcp-video-pipeline", "system_status", {})


@mcp.tool
async def review_check_job(job_id: str) -> dict:
    """Get status of a review job via review-monitor."""
    return _mcp_call("/usr/local/bin/mcp-review-monitor", "check_job", {"job_id": job_id})


@mcp.tool
async def review_wait_for_completion(job_id: str, timeout: int = 300) -> dict:
    """Wait for a review job to complete."""
    return _mcp_call("/usr/local/bin/mcp-review-monitor", "wait_for_completion", {"job_id": job_id, "timeout": timeout})


@mcp.tool
async def review_list_recent_jobs() -> dict:
    """List recent review jobs via review-monitor."""
    return _mcp_call("/usr/local/bin/mcp-review-monitor", "list_recent_jobs", {})


@mcp.tool
async def email_send(to: str, subject: str, body: str) -> dict:
    """Send an email via msmtp."""
    return _mcp_call("/usr/local/bin/mcp-email", "send_email", {"to": to, "subject": subject, "body": body})


# ════════════════════════════════════════════════════════════════════════════
# ADMIN TOOLS (via User API)
# ════════════════════════════════════════════════════════════════════════════

class ApiSession:
    def __init__(self, base: str):
        self.base   = base.rstrip("/")
        self.cookies = {}
    def _cookie(self, resp):
        for h, v in resp.headers.items():
            if h.lower() == "set-cookie":
                p = v.split(";")
                if p:
                    kv = p[0].split("=", 1)
                    if len(kv) == 2:
                        self.cookies[kv[0].strip()] = kv[1].strip()
    def post_form(self, path: str, data: dict) -> dict:
        body = urllib.parse.urlencode(data).encode()
        req  = urllib.request.Request(f"{self.base}{path}", data=body,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                self._cookie(resp)
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
    def get_text(self, path: str) -> str:
        req = urllib.request.Request(f"{self.base}{path}")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        with urllib.request.urlopen(req, timeout=15) as resp:
            self._cookie(resp)
            return resp.read().decode()


def _admin_session():
    email    = os.environ.get("VYBORD_ADMIN_EMAIL", "make@grpid.com")
    password = os.environ.get("VYBORD_ADMIN_PASS", "")
    if not password:
        return None
    api = ApiSession(USER_API)
    result = api.post_form("/admin/login", {"email": email, "password": password})
    if not api.cookies.get("vyb_token"):
        return None
    return api


import re
def _parse_users(html: str) -> list:
    users = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows[1:]:
        cells = re.findall(r"<td>(.*?)</td>", row, re.DOTALL)
        if len(cells) >= 5:
            users.append({
                "email":            re.sub(r"<[^>]+>", "", cells[0]).strip(),
                "plan":             re.sub(r"<[^>]+>", "", cells[1]).strip(),
                "videos_generated": re.sub(r"<[^>]+>", "", cells[2]).strip(),
                "verified":         "yes" in re.sub(r"<[^>]+>", "", cells[3]).lower(),
                "status":           "active" if "green" in cells[4].lower() else "suspended",
            })
    return users


@mcp.tool
async def admin_stats() -> dict:
    api = _admin_session()
    if not api: return {"error": "Admin credentials not configured (set VYBORD_ADMIN_EMAIL/PASS env)"}
    html = api.get_text("/admin/dashboard")
    stats = {}
    for key, pat in [
        ("total_users",   r"Total Users.*?<div class=\"value\">([0-9,]+)"),
        ("total_videos",  r"Videos Generated.*?<div class=\"value\">([0-9,]+)"),
        ("revenue_cents", r"Revenue.*?\$([0-9,.]+)"),
        ("active_users",  r"active.*?<div class=\"value\">([0-9,]+)"),
    ]:
        m = re.search(pat, html.replace("\n", " "), re.DOTALL)
        stats[key] = m.group(1) if m else None
    return stats


@mcp.tool
async def admin_list_users(search: str = "", status: str = "", plan_filter: str = "", page: int = 1) -> dict:
    api = _admin_session()
    if not api: return {"error": "Admin credentials not configured"}
    params = f"?page={page}"
    if search:      params += f"&search={urllib.parse.quote(search)}"
    if status:      params += f"&status_filter={urllib.parse.quote(status)}"
    if plan_filter: params += f"&plan_filter={urllib.parse.quote(plan_filter)}"
    html = api.get_text(f"/admin/users{params}")
    return {"users": _parse_users(html), "page": page, "search": search, "status": status}


@mcp.tool
async def admin_update_user(user_id: int, is_active: bool | None = None, plan_id: int | None = None) -> dict:
    api = _admin_session()
    if not api: return {"error": "Admin credentials not configured"}
    post_data = {}
    if is_active is not None: post_data["is_active"] = 1 if is_active else 0
    if plan_id  is not None: post_data["plan_id"]    = plan_id
    if not post_data: return {"error": "Provide is_active or plan_id"}
    try:
        api.post_form(f"/admin/users/{user_id}/update", post_data)
        return {"status": "ok", "user_id": user_id, "updated": post_data}
    except Exception as e:
        return {"error": str(e)}




# ════════════════════════════════════════════════════════════════════════════
# SNAGGER — URL Source + Image Snagger Tools
# ════════════════════════════════════════════════════════════════════════════

def _snag_fetch(url: str, timeout: int = 15) -> dict:
    import urllib.request, urllib.parse
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or 'utf-8'
            try: text = raw.decode(enc)
            except: text = raw.decode('utf-8', errors='replace')
            return {"success": True, "url": url, "status": resp.status,
                    "content_type": resp.headers.get('Content-Type', ''), "source": text[:500000]}
    except Exception as e:
        return {"success": False, "url": url, "error": str(e)}

def _snag_extract_images(source: str, page_url: str) -> list:
    import re, urllib.parse
    images, seen = [], set()
    parsed = urllib.parse.urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for pattern in [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'background-image:\s*url\(["\']?([^"\')]+)["\']?\)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    ]:
        for match in re.finditer(pattern, source, re.IGNORECASE):
            img = match.group(1).strip()
            if img and img not in seen:
                seen.add(img)
                if img.startswith('//'): img = 'https:' + img
                elif img.startswith('/'): img = base + img
                elif not img.startswith('http'): img = urllib.parse.urljoin(page_url, img)
                if not img.startswith('data:') and 'chrome' not in img:
                    images.append(img)
    return images

def _snag_meta(source: str) -> dict:
    import re
    meta = {}
    for key, pat in [
        ('og:title', r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:description', r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:image', r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:url', r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']'),
        ('title', r'<title[^>]*>([^<]+)</title>'),
    ]:
        m = re.search(pat, source, re.IGNORECASE)
        if m: meta[key] = m.group(1).strip()
    return meta

@mcp.tool
async def snag_source(url: str, timeout: int = 15) -> dict:
    'Fetch a URL and return raw HTML source + basic status.'
    return _snag_fetch(url, timeout)

@mcp.tool
async def snag_images(url: str, timeout: int = 15, filter: str = "all") -> dict:
    'Extract all image URLs from a webpage. Filter: all, large (>1024px wide), realestate.'
    page = _snag_fetch(url, timeout)
    if not page.get("success"): return page
    images = _snag_extract_images(page["source"], url)
    if filter == "large":
        images = [u for u in images if any(q in u.lower() for q in ["1024","1920","2000","4k"])]
    elif filter == "realestate":
        images = [u for u in images if any(q in u.lower() for q in ["photo","img","pic","listing","property","1200","1600"])]
    return {"url": url, "count": len(images), "images": images}

@mcp.tool
async def snag_full(url: str, timeout: int = 15) -> dict:
    'Full snagged data: source + images + OpenGraph metadata in one call.'
    page = _snag_fetch(url, timeout)
    if not page.get("success"): return page
    images = _snag_extract_images(page["source"], url)
    return {
        "url": url, "status": page["status"], "content_type": page["content_type"],
        "source_length": len(page["source"]), "metadata": _snag_meta(page["source"]),
        "images_count": len(images), "images": images
    }

# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, uvicorn
    p = argparse.ArgumentParser(description="OpenClaw MCP Unified Bridge")
    p.add_argument("--port",      type=int, default=8090)
    p.add_argument("--vps-api",   default=VPS_API)
    p.add_argument("--user-api",  default=USER_API)
    p.add_argument("--review-api",default=REVIEW_API)
    args = p.parse_args()
    vps_client = httpx.AsyncClient(base_url=args.vps_api, timeout=TIMEOUT)
    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=args.port, log_level="info")
