#!/usr/bin/env python3
"""Simple lookup server for property data. Port 7074."""
import http.server, socketserver, json, re, html, urllib.request

PORT = 17074

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[lookup] {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "https://app.vybord.com")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path != "/api/lookup":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        try:
            payload = json.loads(body)
        except:
            payload = {}
        target_url = payload.get("url", "")
        if not target_url:
            self.send_response(400)
            self.send_header("Access-Control-Allow-Origin", "https://app.vybord.com")
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "url required"}).encode())
            return
        try:
            req = urllib.request.Request(target_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                try:
                    html_str = raw.decode("utf-8")
                except UnicodeDecodeError:
                    html_str = raw.decode("latin-1")

            def strip_tags(s):
                s = re.sub("<[^>]+>", "", s)
                return html.unescape(s).strip()

            def meta(pat):
                m = re.search(pat, html_str, re.I)
                return strip_tags(m.group(1)) if m else ""

            address = (
                meta(r'<meta property="og:title" content="([^"]+)">') or
                meta(r'<meta property="og:title" content="([^"]+)">') or
                meta(r'<h1 class="[^"]*address[^"]*"[^>]*>([^<]+)</h1>') or
                meta(r'<address[^>]*>([^<]+)</address>') or
                meta(r'<title>([^<]+)</title>')
            )

            price_m = re.search(r'\$[\d,]+', html_str)
            price = price_m.group(0).replace("$", "") if price_m else ""
            beds_m = re.search(r'(\d+)\s*(bed(?:room)?s?|bd)\b', html_str, re.I)
            baths_m = re.search(r'(\d+(?:\.\d+)?)\s*(bath(?:room)?s?|ba)\b', html_str, re.I)
            sqft_m = re.search(r'([\d,]+)\s*(sq\s*ft|square\s*feet)\b', html_str, re.I)
            beds = beds_m.group(1) if beds_m else ""
            baths = baths_m.group(1) if baths_m else ""
            sqft = sqft_m.group(1) if sqft_m else ""
            script = address
            if price: script += " " + price
            if beds: script += " " + beds + " bed"
            if baths: script += " " + baths + " bath"
            if sqft: script += " " + sqft + " sq ft"

            print(f"[lookup] OK {target_url[:50]} -> {address[:40]}")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "https://app.vybord.com")
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"address": address, "price": price, "beds": beds, "baths": baths, "sqft": sqft, "script": script}).encode())
        except Exception as e:
            print(f"[lookup] ERROR {target_url[:50]}: {e}")
            # Return 200 with error in JSON body — prevents nginx from surfacing 502/4xx as HTML error page
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "https://app.vybord.com")
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_msg = str(e)
            # Make user-friendly messages for common fetch failures
            if "404" in err_msg or "Not Found" in err_msg:
                err_msg = "Listing not found (404). Check the URL or try a different listing site."
            elif "500" in err_msg or "Internal Server Error" in err_msg:
                err_msg = "Listing site returned a server error. Try again or use a different URL."
            elif "timed out" in err_msg.lower():
                err_msg = "Lookup timed out. The site may be blocking requests — try the 'Scan / Paste Images' method instead."
            elif "Connection" in err_msg or "refused" in err_msg.lower():
                err_msg = "Could not reach the listing URL. Verify the link is correct and publicly accessible."
            self.wfile.write(json.dumps({"error": err_msg}).encode())

socketserver.TCPServer.allow_reuse_address = True
print(f"Lookup server starting on port {PORT}")
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    httpd.serve_forever()
