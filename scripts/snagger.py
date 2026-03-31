#!/usr/bin/env python3
"""
snagger — URL Source + Image Snagger MCP Server
Fetches page source, extracts image URLs, returns structured data.
"""
import re, json, sys, urllib.request, urllib.parse

def fetch_url(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or 'utf-8'
            try:
                text = raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                text = raw.decode('utf-8', errors='replace')
            return {"success": True, "url": url, "status": resp.status,
                    "content_type": resp.headers.get('Content-Type', ''), "source": text[:500000]}
    except Exception as e:
        return {"success": False, "url": url, "error": str(e)}

def extract_images(source, page_url):
    images = []
    seen = set()
    parsed = urllib.parse.urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'background-image:\s*url\(["\']?([^"\')]+)["\']?\)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'https?://[^"\'<>\s]+\.(?:jpg|jpeg|png|gif|webp|svg|bmp)(?:\?[^"\'<>\s]*)?',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.IGNORECASE):
            img_url = match.group(1).strip()
            if img_url and img_url not in seen:
                seen.add(img_url)
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                elif img_url.startswith('/'):
                    img_url = base + img_url
                elif not img_url.startswith('http'):
                    img_url = urllib.parse.urljoin(page_url, img_url)
                if img_url.startswith('data:') or 'chrome' in img_url:
                    continue
                images.append(img_url)
    return images

def extract_metadata(source):
    meta = {}
    for key, pattern in [
        ('og:title', r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:description', r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:image', r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'),
        ('og:url', r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']'),
        ('title', r'<title[^>]*>([^<]+)</title>'),
    ]:
        m = re.search(pattern, source, re.IGNORECASE)
        if m:
            meta[key] = m.group(1).strip()
    return meta

def handle(req):
    method = req.get("method")
    msg_id = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "snagger", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [
            {"name": "snag_source", "description": "Fetch URL and return raw HTML source",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "timeout": {"type": "integer", "default": 15}}, "required": ["url"]}},
            {"name": "snag_images", "description": "Extract all image URLs from a webpage",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "timeout": {"type": "integer", "default": 15}, "filter": {"type": "string", "enum": ["all", "large", "realestate"], "default": "all"}}, "required": ["url"]}},
            {"name": "snag_full", "description": "Full: source + images + metadata",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "timeout": {"type": "integer", "default": 15}}, "required": ["url"]}},
        ]}}
    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})
        url = args.get("url")
        if not url:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": "Missing url"}}
        timeout = int(args.get("timeout", 15))
        if tool_name == "snag_source":
            result = fetch_url(url, timeout)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
        elif tool_name == "snag_images":
            page = fetch_url(url, timeout)
            if not page.get("success"):
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps(page)}]}}
            images = extract_images(page["source"], url)
            filter_type = args.get("filter", "all")
            if filter_type == "large":
                images = [u for u in images if any(q in u.lower() for q in ["1024", "1920", "2000", "4k"])]
            elif filter_type == "realestate":
                images = [u for u in images if any(q in u.lower() for q in ["photo", "img", "pic", "listing", "property", "1200", "1600"])]
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps({"url": url, "count": len(images), "images": images})}]}}
        elif tool_name == "snag_full":
            page = fetch_url(url, timeout)
            if not page.get("success"):
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps(page)}]}}
            images = extract_images(page["source"], url)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps({
                "url": url, "status": page["status"], "content_type": page["content_type"],
                "source_length": len(page["source"]), "metadata": extract_metadata(page["source"]),
                "images_count": len(images), "images": images
            })}]}}
        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

buffer = ""
while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break
        buffer += line
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = handle(req)
                print(json.dumps(resp), flush=True)
            except json.JSONDecodeError:
                continue
    except EOFError:
        break
    except Exception as e:
        print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}), flush=True)
