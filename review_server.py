#!/usr/bin/env python3
"""Review Web Server — VPS version with full pipeline. Port 7073."""
import http.server, socketserver, json, os, subprocess, shutil, re, uuid
import asyncio, threading
from urllib.parse import urlparse
from pathlib import Path
import json

PORT = 7073
CURRENT_JOB_ID = [None]  # thread-safe mutable container
WORK_DIR = Path('/opt/video_pipeline/work')
LISTING_DIR_BASE = WORK_DIR / 'review_images'

def get_job_listing_dir(job_id):
    # Try both with and without 'review_' prefix
    for jid in [job_id, job_id.replace("review_", "")]:
        for path in [
            Path(f"/opt/video_pipeline/work/{jid}/images"),
            Path(f"/tmp/rs_uploads/{jid}/images"),
        ]:
            if path.exists():
                return path
    return LISTING_DIR_BASE
    # Last fallback: global listing dir
    return LISTING_DIR_BASE

def get_job_config(job_id):
    # Try both with and without 'review_' prefix — different code paths create jobs differently
    for jid in [job_id, job_id.replace("review_", "")]:
        for cfg_path in [
            Path(f"/opt/video_pipeline/work/{jid}/review_config.json"),
            Path(f"/tmp/rs_uploads/{jid}/pipeline_config.json"),
        ]:
            if cfg_path.exists():
                try:
                    return json.loads(cfg_path.read_text())
                except:
                    pass
    # Fallback: global config
    cfg_path = WORK_DIR / 'review_config.json'
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return None


CONFIG_FILE = WORK_DIR / 'review_config.json'
WWW_DIR = Path('/opt/video_pipeline/review_www')
VENV = '/opt/venv/bin/python'
ELEVENLABS_API_KEY = 'sk_8fc024b5406b1e3ac437db283f36bb69a40a13b5e72c6041'

VOICE_MAP = {
    'Bella':    ('en-US-JennyNeural',  'hpp4J3VqNfWAUOO0d1Us'),
    'Sarah':    ('en-US-AriaNeural',   'EXAVITQu4vr4xnSDxMaL'),
    'Roger':    ('en-US-RogerNeural',  'CwhRBWXzGAHq8TQ4Fs17'),
    'George':   ('en-US-AndrewNeural', 'JBFqnCBsd6RMkjVDRZzb'),
    'Jessica':  ('en-US-AvaNeural',    'cgSgspJ2msm6clMCkdW9'),
    'Charlie':  ('en-US-BrianNeural',  'IKne3meq5aSn9XLyUdCD'),
    'Laura':    ('en-US-EmmaNeural',   'FGY2WhTYpPnrIDTdsKH5'),
    'Liam':     ('en-US-GuyNeural',    'TX3LPaxmHKxFdv7VOQHJ'),
}

def read_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return None

def log(msg):
    print(f'[{msg}]', flush=True)

def format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def run(cmd, cwd=None, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if r.returncode != 0:
        log(f'RUN ERR: {r.stderr[-300:]}')
    return r

def render_page(cfg, listing_dir=None, job_id=None):
    ld = listing_dir if listing_dir else LISTING_DIR_BASE
    img_files = sorted([f for f in os.listdir(ld) if f.lower().endswith(('.jpg','.jpeg'))])
    sel = cfg.get('selectedIndices', list(range(min(15, len(img_files)))))
    sel_set = set(sel)

    cards = []
    for i, fname in enumerate(img_files):
        is_sel = i in sel_set
        order = sel.index(i) + 1 if is_sel else 0
        tag = (cfg.get('images') or [{}])[i].get('tag', '') if i < len(cfg.get('images') or []) else ''
        notes = (cfg.get('images') or [{}])[i].get('notes', '') if i < len(cfg.get('images') or []) else ''
        badge = f'<span class="badge {tag.lower()}">{tag}</span>' if tag else '<span></span>'
        right = f'<span class="sel-badge">{order}</span>' if is_sel else f'<span class="img-num">{i+1}</span>'
        cards.append({'index': i, 'fname': fname, 'is_selected': is_sel,
                      'badge': badge, 'right': right, 'notes': notes})

    pool_cards = [{'fname': img_files[si], 'i': si+1} for i, si in enumerate(sel) if si < len(img_files)]
    pool_parts = []
    for p in pool_cards:
        pool_parts.append(
            "<div class='mini-card'><img src='/images/" + (job_id or '') + "/" + p['fname'] + "' alt='S" + str(p['i'])
            + "' onerror=\"this.style.display='none'\" /><span class='mini-num'>" + str(p['i']) + "</span></div>"
        )
    pool_html = ''.join(pool_parts)

    cap = cfg.get('captionStyle', {})
    voices = [
        ('Bella', 'Professional, Bright, Warm'),
        ('Sarah', 'Mature, Reassuring, Confident'),
        ('Roger', 'Laid-Back, Casual'),
        ('George', 'Warm, Storyteller'),
        ('Jessica', 'Playful, Bright, Warm'),
        ('Charlie', 'Deep, Confident, Energetic'),
        ('Laura', 'Enthusiast, Quirky'),
        ('Liam', 'Energetic, Social Media Creator'),
    ]
    voice_opts = '\n'.join(
        f'<option value="{v}"{" selected" if cfg.get("voice","Bella")==v else ""}>{v} — {d}</option>'
        for v, d in voices
    )
    glow_opts = '\n'.join(
        f'<option value="{g}"{" selected" if cap.get("glowIntensity","explosive")==g else ""}>{g.capitalize()}</option>'
        for g in ['subtle', 'medium', 'explosive']
    )
    music_opts = '\n'.join(
        f'<option value="{m}">{m.replace("_", " ").replace(".mp3", "").title()}</option>'
        for m in ['none', 'upbeat', 'positive', 'cinematic', 'chill', 'panning_track']
    )
    script_html = (cfg.get('script') or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    addr = (cfg.get('address') or 'Listing').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    listing_type = (cfg.get('listingType') or 'Real Estate').replace('&', '&amp;')
    price = cfg.get('price') or '—'
    beds = cfg.get('beds') or '—'
    baths = cfg.get('baths') or '—'
    sqft = cfg.get('sqft') or '—'
    sel_len = len(sel)
    font_size = cap.get('fontSize', 55)
    color_val = cap.get('highlightColor', '#FFFF00')
    sel_json = json.dumps(sel)
    files_json = json.dumps(img_files)

    img_cards_html = ''
    for c in cards:
        img_cards_html += (
            "<div class='img-card" + (" selected" if c["is_selected"] else "") + "' data-index='" + str(c["index"])
            + "' onclick=\"toggle(" + str(c["index"]) + ")\" draggable='true'"
            " ondragstart='dragStart(event)' ondragover='dragOver(event)' ondrop='drop(event)' ondragend='dragEnd(event)'>"
            "<img src='/images/" + (job_id or '') + "/" + c["fname"] + "' alt='Img" + str(c["index"]+1)
            + "' onerror=\"this.style.display='none'\" />"
            "<div class='img-meta'>" + c["badge"] + c["right"] + "</div>"
            "<div class='img-notes'>" + c["notes"] + "</div>"
            "</div>"
        )

    html = (
"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video Review — """ + addr + """</title>
<link rel="stylesheet" href="/app.css">
</head>
<body>
<div class="container">
    <div style="position:fixed;top:8px;right:12px;background:#f59e0b;color:#000;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;z-index:9999;">X7</div>
    <h1>""" + addr + """</h1>
    <div class="subtitle">""" + listing_type + """ &middot; """ + str(len(img_files)) + """ images &middot; Click to select</div>

    <div class="section">
        <div class="section-title">Property Details</div>
        <div class="prop-info">
            <div class="prop-stat"><div class="val">""" + price + """</div><div class="lbl">Price</div></div>
            <div class="prop-stat"><div class="val">""" + beds + """</div><div class="lbl">Beds</div></div>
            <div class="prop-stat"><div class="val">""" + baths + """</div><div class="lbl">Baths</div></div>
            <div class="prop-stat"><div class="val">""" + sqft + """</div><div class="lbl">Sq Ft</div></div>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Image Pool &mdash; """ + str(len(img_files)) + """ images &middot; Click to select (max 15)</div>
        <div class="sel-hint"><span id="sel-count">""" + str(sel_len) + """</span> selected &middot; First 15 in order used for video</div>
        <div class="img-grid" id="img-grid">
""" + img_cards_html + """
        </div>
    </div>

    <div class="section">
        <div class="pool-header">
            <span>Selected for Video &mdash; <span id="pool-count">""" + str(sel_len) + """</span> images</span>
            <button class="clear-btn" onclick="clearSel()">Clear All</button>
        </div>
        <div id="pool-grid">
""" + pool_html + """
        </div>
    </div>

    <div class="section">
        <div class="section-title">Narration Script</div>
        <textarea id="script">""" + script_html + """</textarea>
        <div class="char-count"><span id="char-count">""" + str(len(script_html)) + """</span> chars</div>
    </div>

    <div class="section">
        <div class="section-title">Caption Style</div>
        <div class="sgrid">
            <div class="field"><label>Font Size (px)</label>
                <input type="number" id="fontSize" value=""" + str(font_size) + """ min="24" max="80" /></div>
            <div class="field"><label>Highlight Color</label>
                <input type="color" id="highlightColor" value=""" + color_val + """ /></div>
            <div class="field"><label>Glow Intensity</label>
                <select id="glowIntensity">""" + glow_opts + """</select></div>
        </div>
        <div id="caption-preview">
            <span class="word-being">Pool</span><span class="done-word"> views </span><span class="done-word">and </span><span class="done-word">sunset</span>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Voice</div>
        <select id="voice">""" + voice_opts + """</select>
    </div>

    <div class="section">
        <div class="section-title">Background Music</div>
        <select id="music">""" + music_opts + """</select>
    </div>

    <div class="section">
        <div class="section-title">Branding</div>
        <div class="field">
            <label>Logo (transparent PNG)</label>
            <input type="file" id="logo" accept="image/png" />
        </div>
        <div class="sgrid">
            <div class="field">
                <label>Logo Position</label>
                <select id="logoPosition">
                    <option value="top-left">Top Left</option>
                    <option value="top-right">Top Right</option>
                    <option value="bottom-left" selected>Bottom Left</option>
                    <option value="bottom-right">Bottom Right</option>
                </select>
            </div>
            <div class="field">
                <label>Logo Size (%)</label>
                <input type="number" id="logoSize" value="15" min="5" max="30" />
            </div>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Start Caption</div>
        <div class="sgrid">
            <div class="field">
                <label>Start Text</label>
                <input type="text" id="startCaption" placeholder="e.g. Villa Serene" />
            </div>
            <div class="field">
                <label>Duration (s)</label>
                <input type="number" id="startDuration" value="3" min="2" max="8" step="0.5" />
            </div>
        </div>
    </div>

    <div class="section">
        <div class="section-title">End Caption</div>
        <div class="sgrid">
            <div class="field">
                <label>End Text</label>
                <input type="text" id="endCaption" placeholder="e.g. Call (305) 555-1234" />
            </div>
            <div class="field">
                <label>Duration (s)</label>
                <input type="number" id="endDuration" value="4" min="2" max="10" step="0.5" />
            </div>
        </div>
    </div>

    <div class="btn-row">
        <button class="btn btn-primary" id="gen-btn" onclick="generate()">Generate Video</button>
    </div>
    <div id="status"></div>
</div>
<script>
var TOTAL = """ + str(len(img_files)) + """;
var MAX = 15;
var sel = new Set(""" + sel_json + """);
var imgFiles = """ + files_json + """;
var jobId = """ + json.dumps(job_id) + """;
var propPrice = """ + json.dumps(price if price and price != "—" else "") + """;
var propBeds = """ + json.dumps(beds if beds and beds != "—" else "") + """;
var propBaths = """ + json.dumps(baths if baths and baths != "—" else "") + """;
var propSqft = """ + json.dumps(sqft if sqft and sqft != "—" else "") + """;

function render() {
    document.querySelectorAll('.img-card').forEach(function(card) {
        var i = parseInt(card.dataset.index);
        var isSel = sel.has(i);
        card.classList.toggle('selected', isSel);
        var meta = card.querySelector('.img-meta');
        if (isSel) {
            meta.innerHTML = '<span class="sel-badge">' + (Array.from(sel).indexOf(i)+1) + '</span>';
        } else {
            meta.innerHTML = '<span></span><span class="img-num">' + (i+1) + '</span>';
        }
    });
    document.getElementById('pool-grid').innerHTML = Array.from(sel).map(function(si, di) {
        return "<div class='mini-card'><img src='/images/" + (jobId || '') + "/" + imgFiles[si] + "' /><span class='mini-num'>" + (di+1) + "</span></div>";
    }).join('');
    document.getElementById('sel-count').textContent = sel.size;
    document.getElementById('pool-count').textContent = sel.size;
}

function toggle(i) {
    if (sel.has(i)) sel.delete(i);
    else { if (sel.size >= MAX) return; sel.add(i); }
    render();
}

function clearSel() { sel = new Set(); render(); }

var dragSrc = null;
function dragStart(e) { dragSrc = parseInt(e.target.closest('.img-card').dataset.index); }
function dragOver(e) { e.preventDefault(); }
function drop(e) {
    e.preventDefault();
    var target = parseInt(e.target.closest('.img-card').dataset.index);
    if (sel.has(dragSrc) && sel.has(target) && dragSrc !== target) {
        var arr = Array.from(sel);
        var dp = arr.indexOf(dragSrc), tp = arr.indexOf(target);
        arr.splice(dp, 1); arr.splice(tp, 0, dragSrc);
        sel = new Set(arr); render();
    }
    dragSrc = null;
}
function dragEnd() { dragSrc = null; }

document.getElementById('script').addEventListener('input', function(e) {
    document.getElementById('char-count').textContent = e.target.value.length;
});

function generate() {
    var btn = document.getElementById('gen-btn');
    var status = document.getElementById('status');
    if (sel.size === 0) { status.className = 'error'; status.textContent = 'Select at least 1 image.'; return; }
    btn.disabled = true;
    status.className = 'running';
    status.textContent = 'Building video (~45s)...';

    // Handle logo file upload
    var logoBase64 = '';
    var logoFile = document.getElementById('logo').files[0];
    if (logoFile) {
        var reader = new FileReader();
        reader.onload = function(e) { submitPayload(e.target.result); };
        reader.readAsDataURL(logoFile);
    } else {
        submitPayload('');
    }

    function submitPayload(logoData) {
        var payload = {
            address: document.querySelector('h1').textContent.trim(),
            script: document.getElementById('script').value,
            sourceJobId: location.pathname.split('/review/')[1] || '',
            price: (document.querySelector('.prop-stat > .val') || {textContent: ''}).textContent,
            beds: (document.querySelectorAll('.prop-stat > .val')[1] || {textContent: ''}).textContent,
            baths: (document.querySelectorAll('.prop-stat > .val')[2] || {textContent: ''}).textContent,
            sqft: (document.querySelectorAll('.prop-stat > .val')[3] || {textContent: ''}).textContent,
            selectedIndices: Array.from(sel),
            captionStyle: {
                fontSize: parseInt((document.getElementById('fontSize') || {value:'55'}).value),
                highlightColor: (document.getElementById('highlightColor') || {value:'#FFFF00'}).value,
                glowIntensity: (document.getElementById('glowIntensity') || {value:'explosive'}).value
            },
            voice: (document.getElementById('voice') || {value:'Bella'}).value,
            music: (document.getElementById('music') || {value:'upbeat'}).value,
            logo: logoData,
            logoPosition: (document.getElementById('logoPosition') || {value:'bottom-right'}).value,
            logoSize: parseInt((document.getElementById('logoSize') || {value:'15'}).value),
            startCaption: (document.getElementById('startCaption') || {value:''}).value,
            startDuration: parseFloat((document.getElementById('startDuration') || {value:'3'}).value) || 3,
            endCaption: (document.getElementById('endCaption') || {value:''}).value,
            endDuration: parseFloat((document.getElementById('endDuration') || {value:'4'}).value) || 4,
        };
        fetch('/api/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); }).then(function(r) {
            if (r.success) {
                var jobId = r.job_id;
                status.textContent = 'Starting build...';
                var pollInterval = setInterval(function() {
                    fetch('/api/status/' + jobId).then(function(res) { return res.json(); }).then(function(s) {
                        status.textContent = s.status || 'Building...';
                        if (s.done) {
                            clearInterval(pollInterval);
                            btn.disabled = false;
                            status.className = 'done';
                            var videoSection = document.getElementById('video-section');
                            if (!videoSection) {
                                var container = document.querySelector('.container');
                                var videoDiv = document.createElement('div');
                                videoDiv.id = 'video-section';
                                videoDiv.className = 'section';
                                videoDiv.innerHTML = '<div class="section-title">Your Video</div><video id="preview-video" controls autoplay style="width:100%;max-width:640px;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.4);"><source src="/videos/' + jobId + '/video_final.mp4" type="video/mp4">Your browser does not support video.</video>';
                                container.appendChild(videoDiv);
                            } else {
                                var vid = document.getElementById('preview-video');
                                vid.src = '/videos/' + jobId + '/video_final.mp4';
                            }
                        }
                    }).catch(function(e) { /* Keep polling on network glitch */ });
                }, 3000);
            } else {
                status.className = 'error';
                status.textContent = 'Error: ' + (r.error||'unknown');
                btn.disabled = false;
            }
        }).catch(function(e) {
            status.className = 'error';
            status.textContent = 'Error: ' + e.message;
            btn.disabled = false;
        });
    }
}

render();
</script>
</body>
</html>""")
    return html


def scrape_listing(url):
    """Standalone listing scraper — safe to call directly or from within request handlers."""
    import re as _re
    from bs4 import BeautifulSoup
    import requests as _requests

    result = {'address': '', 'price': '', 'beds': '', 'baths': '', 'sqft': '', 'images': [], 'success': False}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        resp = _requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        if 'juanmiamihomes.com' in url:
            addr_parts = []
            for tag in soup.find_all('p'):
                t = tag.get_text(strip=True)
                if t and ('NE ' in t or 'NW ' in t or 'SE ' in t or 'SW ' in t or 'St' in t or 'Ave' in t or 'Blvd' in t):
                    addr_parts.append(t); break
            if not addr_parts:
                addr_parts = [s.get_text(strip=True) for s in soup.find_all('p')
                              if s.get('class') and 'address' in ' '.join(s.get('class', []))]
            all_p = soup.find_all('p')
            for p_el in all_p:
                t = p_el.get_text(strip=True)
                if t in ('Miami Shores, FL 33138', 'Miami Shores, FL'):
                    addr_parts.append(', ' + t); break
                if 'Miami Shores' in t:
                    addr_parts.append(', ' + t); break
            result['address'] = ' '.join(addr_parts)

            feat = soup.select_one('.te-heading-property-details-features, .btn-group')
            beds = baths = sqft = ''
            if feat:
                labels = feat.select('.text-secondary')
                vals = feat.select('.head')
                for label, val in zip(labels, vals):
                    lbl = label.get_text(strip=True).lower()
                    v = val.get_text(strip=True)
                    if 'price' in lbl:
                        result['price'] = v.replace('$', '')
                    elif 'bed' in lbl and 'half' not in lbl:
                        beds = v
                    elif 'bath' in lbl and 'half' not in lbl:
                        baths = v
                    elif 'ft' in lbl or 'sq' in lbl:
                        sqft = v.replace(',', '').replace(' ft²', '').replace(' ft', '').split()[0]
            result['beds'] = beds
            result['baths'] = baths
            result['sqft'] = sqft

            images = []
            for el in soup.find_all(style=True):
                style = el.get('style', '')
                if 'background-image' in style and 'url(' in style:
                    m = _re.search(r'url\("?([^\)"]+)"?\)', style)
                    if m:
                        src = m.group(1)
                        if ('loopt-idx' in src or 'A119' in src) and 'logo' not in src.lower():
                            images.append(src)
            result['images'] = list(dict.fromkeys(images))[:70]
        else:
            def text(sel, default=''):
                e = soup.select_one(sel)
                return e.get_text(strip=True) if e else default
            result['address'] = (text('[data-testid="address"], .address, .listing-address')
                                or text('h1', '') or soup.title.string or '')
            result['price'] = (text('[data-testid="price"], .price') or text('.amount', ''))
            result['beds'] = text('[data-testid="beds"], .beds', '')
            result['baths'] = text('[data-testid="baths"], .baths', '')
            result['sqft'] = text('[data-testid="sqft"], .sqft', '')
            result['images'] = [img.get('src') or img.get('data-src')
                                for img in soup.select('img[src*="photo"], img[class*="gallery"]')
                                if img.get('src') and 'logo' not in img.get('src', '').lower()][:15]

        result['success'] = True
    except Exception as e:
        log(f'scrape_listing error for {url}: {e}')
    return result


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[{self.address_string()}] {fmt%args}', flush=True)


    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "https://vybord.com")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


    def do_HEAD(self):
        # Delegate to do_GET logic for headers only
        p = urlparse(self.path).path
        self.send_response(200)
        if p.startswith('/images/'):
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'max-age=3600')
        elif p in ('/app.css', '/style.css'):
            self.send_header('Content-Type', 'text/css')
        else:
            self.send_header('Content-Type', 'text/html')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path

        if p.startswith('/images/'):
            # Format: /images/{job_id}/{fname} — extract job_id from path
            parts = p[8:].split('/', 1)  # strip '/images/' (8 chars) then split job_id/filename
            job_id_from_path = parts[0] if len(parts) > 1 else None
            fname = parts[1] if len(parts) > 1 else parts[0]
            job_id = job_id_from_path or CURRENT_JOB_ID[0]
            if job_id:
                work_path = Path(f"/opt/video_pipeline/work/{job_id}/images/{fname}")
                if work_path.exists():
                    fpath = str(work_path)
                else:
                    fpath = str(Path(f"/tmp/rs_uploads/{job_id}/images/{fname}"))
            else:
                fpath = str(LISTING_DIR_BASE / fname)
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Cache-Control', 'max-age=3600')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        if p in ('/app.css', '/style.css'):
            fpath = str(WWW_DIR / 'style.css')
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/css')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        # Status check endpoint
        if p.startswith('/api/status/'):
            raw_id = p.split('/api/status/')[1].split('/')[0]
            # Normalize: add review_ prefix if missing (matches generate endpoint)
            job_id = raw_id if raw_id.startswith('review_') else 'review_' + raw_id
            work = Path(f"/tmp/rs_uploads/{job_id}")
            status_file = work / 'status.json'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
            self.end_headers()
            if status_file.exists():
                self.wfile.write(status_file.read_text().encode())
            else:
                self.wfile.write(json.dumps({'status': 'Starting...', 'done': False, 'job_id': job_id}).encode())
            return

        # Video serve endpoint
        if p.startswith('/videos/'):
            parts = p[8:].split('/', 1)  # strip '/videos/' then job_id/file
            if len(parts) < 2:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing job_id or filename'}).encode())
                return
            vid_job_id, fname = parts
            # Normalize: add review_ prefix if missing
            vid_job_id = vid_job_id if vid_job_id.startswith('review_') else 'review_' + vid_job_id
            work = Path(f"/tmp/rs_uploads/{vid_job_id}")
            candidates = [
                work / fname,
                work / 'video_final.mp4',
                work / 'video_wna.mp4',
            ]
            fpath = None
            for c in candidates:
                if c.exists() and c.is_file():
                    fpath = str(c)
                    break
            if fpath:
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', os.path.getsize(fpath))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Video not ready'}).encode())
            return

        cfg = None
        listing_dir = None
        job_id = None
        CURRENT_JOB_ID[0] = None  # reset
        if p.startswith("/review/"):
            job_id = p.split("/review/")[1].split("/")[0]
            log(f"REVIEW JOB: job_id={job_id}")
            if job_id:
                CURRENT_JOB_ID[0] = job_id
                listing_dir = get_job_listing_dir(job_id)
                cfg = get_job_config(job_id)
                log(f"JOB CFG: {type(cfg)} found={cfg is not None}")
                # Fallback: if cfg missing property details, try source job's config
                if cfg and (not cfg.get('price') or not cfg.get('beds')):
                    src = cfg.get('sourceJobId') or cfg.get('source_job_id')
                    if src:
                        src_cfg = get_job_config(src)
                        if src_cfg:
                            for k in ('price', 'beds', 'baths', 'sqft', 'listingType', 'prop_details'):
                                if not cfg.get(k) and src_cfg.get(k):
                                    cfg[k] = src_cfg[k]
        if not cfg:
            cfg = read_config()
        if not cfg:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'No review config. Run image analysis first.')
            return

        if p in ('/', '/review', '/index.html') or p.startswith('/review/'):
            try:
                html = render_page(cfg, listing_dir, job_id)
            except Exception as e:
                log(f"RENDER ERROR: {e}")
                import traceback; traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Render error: {e}".encode())
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())
            return


        elif p.startswith("/api/build/"):
            job_id = p.split("/api/build/")[1]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing job_id"}).encode())
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length > 0 else "{}"
            try:
                payload = json.loads(body)
            except:
                payload = {}

            work = Path(f"/tmp/rs_uploads/{job_id}")
            log(f"/api/build called for {job_id}")

            # Trigger build
            try:
                music_name = payload.get("music", "none")
                music_path = {
                    "upbeat": "/opt/video_pipeline/music/upbeat.mp3",
                    "positive": "/opt/video_pipeline/music/positive.mp3",
                    "cinematic": "/opt/video_pipeline/music/cinematic.mp3",
                    "chill": "/opt/video_pipeline/music/chill.mp3",
                    "panning_track": "/opt/video_pipeline/music/panning_track.mp3",
                }.get(music_name, "none")
                cmd = [
                    "/opt/venv/bin/python",
                    "/opt/video_pipeline/scripts/build_vps.py",
                    "--work", f"/tmp/rs_uploads/{job_id}", "--listing", f"/tmp/rs_uploads/{job_id}/images",
                    "--duration", str(payload.get("duration", 30)),
                    "--ratio", payload.get("ratio", "9:16"),
                    "--music", music_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd="/opt/video_pipeline")
                log(f"Build for {job_id}: exit={result.returncode} stdout={result.stdout[:200]}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "job_id": job_id, "exit": result.returncode}).encode())
            except Exception as e:
                log(f"Build error {job_id}: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return


        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        if p == '/api/fetch-html':
            # Handle CORS preflight
            if self.command == 'OPTIONS':
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                return
            # Proxy: fetch URL server-side and return HTML (bypasses CORS)
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode()
            try:
                payload = json.loads(body)
            except:
                payload = {}
            target_url = payload.get('url', '')
            if not target_url:
                self.send_response(400)
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'url required'}).encode())
                return
            try:
                import urllib.request
                req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                    try:
                        html = raw.decode('utf-8')
                    except UnicodeDecodeError:
                        html = raw.decode('latin-1')
                    # Strip inline styles, scripts, and nonce attrs to reduce size
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    for tag in soup(['style', 'script', 'noscript']):
                        tag.decompose()
                    # Remove et-divi-customizer inline style blocks (huge CSS)
                    for elem in soup.find_all('style', id=True):
                        if 'et-divi' in str(elem.get('id', '')):
                            elem.decompose()
                    # Also remove any style attrs
                    for elem in soup.find_all(attrs={'data-type': 'etDCS'}):
                        elem.decompose()
                    html = str(soup)
                    self.send_response(200)
                    self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                self.send_response(502)
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return
        elif p == '/api/generate':
            # Handle CORS preflight
            if self.command == 'OPTIONS':
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode()
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {}
            addr = payload.get('address', 'Listing')
            sel_indices = payload.get('selectedIndices', list(range(15)))
            voice = payload.get('voice', 'Bella')
            script = payload.get('script', '')
            cap = payload.get('captionStyle', {})
            # Validate price — reject garbled CSS selector strings
            raw_price = payload.get('price', '')
            import re
            if raw_price:
                price_clean = re.sub(r'[^\d,]', '', raw_price)
                price = price_clean if price_clean and price_clean != '0' else ''
            else:
                price = ''
            # Branding fields
            logo_b64 = payload.get('logo', '')
            logo_position = payload.get('logoPosition', 'bottom-right')
            logo_size = int(payload.get('logoSize', 15))
            start_caption = payload.get('startCaption', '')
            start_duration = float(payload.get('startDuration', 3))
            end_caption = payload.get('endCaption', '')
            end_duration = float(payload.get('endDuration', 4))
            ratio = payload.get('ratio', '9:16')

            log(f'Generate request: {addr} | {len(sel_indices)} images | voice={voice}')

            # Use existing sourceJobId if provided, otherwise create new
            source_job_id = payload.get('sourceJobId', '')
            if source_job_id:
                # Normalize: add review_ prefix if missing
                job_id = source_job_id if source_job_id.startswith('review_') else 'review_' + source_job_id
                # Clean up old status/video if regenerating
                work = Path(f"/tmp/rs_uploads/{job_id}")
                status_file = work / 'status.json'
                if status_file.exists():
                    os.remove(status_file)
            else:
                job_id = 'review_' + str(uuid.uuid4())[:8]
                work = Path(f"/tmp/rs_uploads/{job_id}")
            img_dir = work / 'images'
            os.makedirs(img_dir, exist_ok=True)

            # Save logo if base64 provided
            logo_path = ''
            if logo_b64:
                try:
                    import base64
                    logo_data = base64.b64decode(logo_b64.split(',')[1] if ',' in logo_b64 else logo_b64)
                    logo_path = str(work / 'logo.png')
                    with open(logo_path, 'wb') as f:
                        f.write(logo_data)
                    log(f'Logo saved: {len(logo_data)} bytes')
                except Exception as e:
                    log(f'Logo save error: {e}')
                    logo_path = ''

            # Copy images from source job OR from global listing dir using selected indices
            import shutil
            if source_job_id:
                src_images = Path(f"/tmp/rs_uploads/{job_id}/images")
                if src_images.exists() and src_images != img_dir:
                    for fname in sorted(src_images.iterdir()):
                        if fname.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                            shutil.copy2(fname, img_dir / fname.name)
                    log(f"Copied {len(list(img_dir.iterdir()))} images from source job {source_job_id}")
            if not list(img_dir.iterdir()):
                # Fallback: copy selected images from global listing dir using indices
                all_imgs = sorted([f for f in LISTING_DIR_BASE.iterdir()
                                   if f.suffix.lower() in ('.jpg', '.jpeg')])
                for idx in sel_indices:
                    if idx < len(all_imgs):
                        shutil.copy2(all_imgs[idx], img_dir / all_imgs[idx].name)
                log(f"Copied {len(list(img_dir.iterdir()))} images from global listing (indices={sel_indices})")

            edge_voice, elevenlabs_id = VOICE_MAP.get(voice, ('en-US-JennyNeural', 'hpp4J3VqNfWAUOO0d1Us'))
            voice_m4a = work / 'voice.m4a'

            def write_status(status_msg, done=False, video_path=''):
                try:
                    with open(work / 'status.json', 'w') as f:
                        json.dump({'status': status_msg, 'done': done, 'video': video_path, 'job_id': job_id}, f)
                except:
                    pass

            def do_build():
                nonlocal script
                caption_style = payload.get('captionStyle', {})
                """All blocking work in one async thread — returns immediately to HTTP."""
                try:
                    price = payload.get('price', '')
                    beds = payload.get('beds', '')
                    baths = payload.get('baths', '')
                    sqft = payload.get('sqft', '')
                    duration = int(payload.get('duration', 30) or 30)
                    # --- Script generation (only if script is empty) ---
                    if not script:
                        voice_desc = {
                            'Sarah': 'Sarah - mature, reassuring',
                            'Bella': 'Bella - professional, warm',
                            'Roger': 'Roger - casual, laid-back',
                            'George': 'George - warm storyteller',
                            'Jessica': 'Jessica - playful, bright',
                            'Charlie': 'Charlie - confident, energetic',
                            'Liam': 'Liam - energetic social media creator',
                        }.get(voice, voice)
                        script_prompt = (
                            'Write a ' + str(duration // 2) + '-sentence energetic real estate narration for a '
                            + beds + '-bed, ' + baths + '-bath'
                            + (' property, ' + sqft + ' sq ft' if sqft else '')
                            + ('. Listed at ' + price if price else '')
                            + '. Property: ' + addr + '. '
                            + 'Voice: ' + voice_desc + '. '
                            + 'Do not say the address. Start with the hook immediately. Only output the narration.'
                        )
                        log('Generating script via OpenClaw AI...')
                        try:
                            import tempfile, subprocess as subproc
                            outf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                            errf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                            outf.close(); errf.close()
                            p = subproc.Popen(
                                ['openclaw', 'agent',
                                 '--session-id', 'gen_script_' + job_id,
                                 '--message', script_prompt,
                                 '--timeout', '60'],
                                stdout=open(outf.name, 'w'),
                                stderr=open(errf.name, 'w'),
                                stdin=subprocess.DEVNULL)
                            ret = p.wait(timeout=120)
                            with open(outf.name) as f:
                                raw = f.read()
                            os.unlink(outf.name); os.unlink(errf.name)
                            lines = raw.strip().splitlines()
                            skip_prefs = ('[plugins]', 'Gateway', 'Error:', 'Usage:', 'Session')
                            clean = [l.strip() for l in lines
                                     if l.strip() and not any(l.strip().startswith(x) for x in skip_prefs)]
                            script = ' '.join(clean).strip()
                            log('Script: ' + (script[:100] if script else 'EMPTY'))
                        except Exception as e:
                            log('Script gen error: ' + str(e))
                            script = ('Welcome to ' + addr + '. This ' + beds + ' bed ' + baths
                                      + ' bath home offers ' + sqft + ' sq ft' + (' listed at ' + price + '.' if price else '.'))

                    # --- Voice generation (edge_tts with gTTS fallback) ---
                    write_status('Generating voice...')
                    try:
                        import edge_tts
                        asyncio.run(edge_tts.Communicate(script, edge_voice).save(str(voice_m4a)))
                        log(f'Voice generated: {voice_m4a.stat().st_size} bytes')
                        # If edge_tts produced a empty/0-byte file, fall back to gTTS
                        if voice_m4a.stat().st_size == 0:
                            raise ValueError("edge_tts produced empty file")
                    except Exception as e:
                        log(f'Voice TTS error ({e}), falling back to gTTS...')
                        try:
                            import gtts
                            tmp_mp3 = str(voice_m4a).replace('.m4a', '.mp3')
                            gtts.gTTS(script, lang='en').save(tmp_mp3)
                            # Convert MP3 to M4A (AAC) using ffmpeg
                            run(['ffmpeg', '-y', '-i', tmp_mp3,
                                 '-c:a', 'aac', '-b:a', '192k',
                                 str(voice_m4a)], timeout=30, cwd='/opt/video_pipeline')
                            os.unlink(tmp_mp3)
                            log(f'gTTS voice generated: {voice_m4a.stat().st_size} bytes')
                        except Exception as e2:
                            log(f'gTTS fallback also failed: {e2}')

                    # --- Whisper transcript ---
                    try:
                        r = run([VENV, '-m', 'whisper', str(voice_m4a), '--model', 'small', '--language', 'English',
                                '--output_dir', str(work)],
                               cwd='/opt/video_pipeline')
                        log(f'Whisper done: {r.stdout[-200:]}')
                        wj = work / 'voice.json'
                        if wj.exists():
                            with open(wj) as f:
                                wdata = json.load(f)
                            srt_path = work / 'voice.srt'
                            with open(srt_path, 'w') as f:
                                for seg in wdata.get('segments', []):
                                    start = seg['start']
                                    end = seg['end']
                                    text = seg['text'].strip()
                                    f.write(f"{seg['id']+1}\n")
                                    f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                                    f.write(f"{text}\n\n")
                            pc_path = work / 'voice_transcript.json'
                            with open(pc_path, 'w') as f:
                                json.dump({'segments': [{
                                    'structure_tags': [],
                                    'max_layout': {'width': 1920, 'height': 1080, 'left': 0, 'top': 0},
                                    'time': {'start': seg['start'], 'end': seg['end']},
                                    'words': [{'word': w.strip(), 'start': seg['start'], 'end': seg['end']} for w in text.split()],
                                    'text': text
                                } for seg in wdata.get('segments', [])]}, f)
                    except Exception as e:
                        log(f'Whisper error: {e}')

                    # --- Pipeline config ---
                    n = min(15, len(sel_indices))
                    cfg_out = {
                        'address': addr, 'script': script, 'voice': voice,
                        'imageCount': n,
                        'selectedIndices': list(sel_indices),
                        'captionStyle': caption_style,
                        'sourceJobId': source_job_id or '',
                        'price': payload.get('price', ''),
                        'beds': payload.get('beds', ''),
                        'baths': payload.get('baths', ''),
                        'sqft': payload.get('sqft', ''),
                        'logoPath': logo_path,
                        'logoPosition': logo_position,
                        'logoSize': logo_size,
                        'startCaption': start_caption,
                        'startDuration': start_duration,
                        'endCaption': end_caption,
                        'endDuration': end_duration,
                        'ratio': ratio,
                    }
                    with open(work / 'pipeline_config.json', 'w') as f:
                        json.dump(cfg_out, f, indent=2)
                    log(f'Pipeline config written for {job_id}')
                    write_status('Voice ready, building slides...')

                    # --- Generate intro card ---
                    intro_mp4 = ''
                    if start_caption:
                        try:
                            intro_png = str(work / 'intro_card.png')
                            intro_anim = str(work / 'intro_card.mp4')
                            ratio_val = ratio
                            run(['python3', '/opt/video_pipeline/scripts/branding.py',
                                 '--mode', 'intro',
                                 '--text', start_caption,
                                 '--subtext', addr,
                                 '--output', intro_png,
                                 '--ratio', ratio_val,
                                 '--duration', str(start_duration)],
                                timeout=30, cwd='/opt/video_pipeline')
                            intro_mp4 = intro_anim
                            log(f'Intro card generated: {intro_mp4}')
                        except Exception as e:
                            log(f'Intro generation error: {e}')

                    # --- Generate outro card ---
                    outro_mp4 = ''
                    if end_caption:
                        try:
                            outro_png = str(work / 'outro_card.png')
                            outro_anim = str(work / 'outro_card.mp4')
                            ratio_val = ratio
                            run(['python3', '/opt/video_pipeline/scripts/branding.py',
                                 '--mode', 'outro',
                                 '--text', end_caption,
                                 '--subtext', '',
                                 '--output', outro_png,
                                 '--ratio', ratio_val,
                                 '--duration', str(end_duration)],
                                timeout=30, cwd='/opt/video_pipeline')
                            outro_mp4 = outro_anim
                            log(f'Outro card generated: {outro_mp4}')
                        except Exception as e:
                            log(f'Outro generation error: {e}')

                    # --- Slides + captions ---
                    write_status('Building slides...')
                    cfg = json.loads((work / 'pipeline_config.json').read_text())
                    cap = cfg.get('captionStyle', {})
                    fs = cap.get('fontSize', 55)
                    hc = cap.get('highlightColor', '#FFFF00')
                    result = run([VENV, '/opt/video_pipeline/scripts/build_vps.py',
                                  '--work', str(work),
                                  '--listing', str(img_dir),
                                  '--duration', str(duration)],
                                 timeout=300, cwd='/opt/video_pipeline')
                    log(f'Slides built: exit={result.returncode}')

                    # --- Concatenate intro + slides + outro ---
                    video_with_intro_outro = str(work / 'video_with_intro_outro.mp4')
                    intro_anim = str(work / 'intro_card_anim.mp4')
                    outro_anim = str(work / 'outro_card_anim.mp4')
                    main_slides = str(work / 'video_noaudio.mp4')
                    clip_files = []
                    if os.path.exists(intro_anim):
                        clip_files.append(intro_anim)
                        log(f'ADDED intro: {intro_anim}')
                    if os.path.exists(main_slides):
                        clip_files.append(main_slides)
                    if os.path.exists(outro_anim):
                        clip_files.append(outro_anim)
                        log(f'ADDED outro: {outro_anim}')
                    log(f'CONCAT: {len(clip_files)} clips: {clip_files}')
                    if len(clip_files) > 1:
                        # Write concat list
                        concat_list = str(work / 'concat_list.txt')
                        with open(concat_list, 'w') as f:
                            for cf in clip_files:
                                f.write(f"file '{cf}'\n")
                        concat_cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                                      '-i', concat_list,
                                      '-c', 'copy', video_with_intro_outro]
                        r_cat = run(concat_cmd, timeout=120)
                        log(f'Intro/outro concat: exit={r_cat.returncode}')
                    elif clip_files:
                        video_with_intro_outro = clip_files[0]
                    else:
                        video_with_intro_outro = main_slides

                    # --- Remux with audio (replace video stream) ---
                    wna_with_intro = str(work / 'video_wna2.mp4')
                    if video_with_intro_outro != str(work / 'video_wna.mp4'):
                        # Get target duration from video_with_intro_outro
                        dur_r = subprocess.run(
                            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                             '-of', 'csv=p=0', video_with_intro_outro],
                            capture_output=True, text=True)
                        target_dur = float(dur_r.stdout.strip() or 0)
                        mux_cmd = ['ffmpeg', '-y', '-i', video_with_intro_outro,
                                   '-i', str(work / 'video_wna.mp4'),
                                   '-map', '0:v:0', '-map', '1:a',
                                   '-c:v', 'copy',
                                   '-af', f'apad=whole_dur={target_dur}',
                                   '-t', str(target_dur), wna_with_intro]
                        r_mux = run(mux_cmd, timeout=60)
                        if r_mux.returncode == 0:
                            wna_with_intro_use = wna_with_intro
                        else:
                            wna_with_intro_use = str(work / 'video_wna.mp4')
                            log(f'Mux error, using original: {r_mux.stderr[-200]}')
                    else:
                        wna_with_intro_use = str(work / 'video_wna.mp4')

                    voice_srt = work / 'voice.srt'
                    final_out = work / 'video_final.mp4'
                    captioned = str(work / 'video_captioned.mp4')
                    pycaps_cmd = ['/opt/venv/bin/pycaps', 'render',
                                   '--input', wna_with_intro_use,
                                   '--output', captioned,
                                   '--template', 'hype-yellow',
                                   '--transcript', str(voice_srt),
                                   '--transcript-format', 'srt',
                                   '--style', f'word.font-size={fs}px',
                                   '--style', f'word.color={hc.lstrip("#")}',
                                   '--video-quality', 'high']
                    r2 = run(pycaps_cmd, timeout=600, cwd='/opt/video_pipeline')
                    log(f'Captions applied: exit={r2.returncode}')

                    # --- Logo overlay ---
                    final_with_logo = str(work / 'video_final.mp4')
                    logo_cfg = cfg.get('logoPath', '')
                    if logo_cfg and os.path.exists(logo_cfg):
                        write_status('Adding logo...')
                        logo_cmd = [
                            'ffmpeg', '-y', '-i', captioned,
                            '-i', logo_cfg,
                            '-filter_complex',
                            f"[1:v]scale=iw*{cfg.get('logoSize', 15)/100.0:-1}[logo];"
                            f"[0:v][logo]overlay="
                            + ({'top-left': '10:10',
                                'top-right': 'W-w-10:10',
                                'bottom-left': '10:H-h-10',
                                'bottom-right': 'W-w-10:H-h-10'}.get(cfg.get('logoPosition', 'bottom-right'), 'W-w-10:H-h-10')),
                            '-c:a', 'copy', final_with_logo
                        ]
                        r_logo = run(logo_cmd, timeout=120)
                        log(f'Logo overlay: exit={r_logo.returncode}')
                        write_status('Complete!', done=True, video_path=str(final_out.name))
                    else:
                        import shutil
                        shutil.copy2(captioned, final_with_logo)
                        write_status('Complete!', done=True, video_path=str(final_out.name))
                except Exception as e:
                    log(f'Build error: {e}')
                    try:
                        write_status(f'Error: {e}', done=False, video_path='')
                    except:
                        pass

            threading.Thread(target=do_build, daemon=True).start()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            resp = json.dumps({'success': True, 'job_id': job_id}).encode()
            try:
                self.wfile.write(resp)
                self.wfile.flush()
            except BrokenPipeError:
                pass
            return



        elif p == '/api/scrape':
            # Scrape a listing URL — delegates to shared scrape_listing()
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                data = json.loads(body)
                url = data.get('url', '')
                if not url:
                    raise ValueError('No URL provided')
                result = scrape_listing(url)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
            except Exception as e:
                log(f'Scrape error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
            return

        elif p in ('/api/create', '/api/send.php', '/send.php'):
            # Endpoint for create.html - accepts {settings, userEmail, images, musicUrl}
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                data = json.loads(body)
                settings = data.get('settings', {})
                images = data.get('images', [])
                user_email = data.get('userEmail', '')

                addr = settings.get('address', 'Listing')
                raw_price = settings.get('price', '')
                import re
                price_clean = re.sub(r'[^\d,]', '', raw_price)
                price = price_clean if price_clean and price_clean != '0' else ''
                beds = settings.get('beds', '')
                baths = settings.get('baths', '')
                sqft = settings.get('sqft', '')
                voice = settings.get('voice', 'Bella')
                script = settings.get('script', '')
                duration = int(settings.get('duration', 30))
                font_size = int(settings.get('fontSize', 55))
                text_color = settings.get('textColor', '#FFFF00')
                music_url = settings.get('musicUrl', '')

                # If price is still bad (garbage/empty) and we have a listing URL, scrape it directly
                listing_url = data.get('url', '')
                log(f'send.php: price="{price}", raw_price="{raw_price}", listing_url="{listing_url}"')
                if not price and listing_url:
                    log(f'Price bad — scraping: {listing_url}')
                    try:
                        scraped = scrape_listing(listing_url)
                        log(f'Scrape result: {scraped}')
                        if scraped.get('success'):
                            addr = scraped.get('address', '') or addr
                            scraped_price = scraped.get('price', '')
                            scraped_price = re.sub(r'[^\d]', '', scraped_price)
                            price = scraped_price if scraped_price else price
                            beds = scraped.get('beds', '') or beds
                            baths = scraped.get('baths', '') or baths
                            sqft = scraped.get('sqft', '') or sqft
                            log(f'Applied scraped: price={price}, beds={beds}')
                    except Exception as e:
                        log(f'Scrape error: {e}')



                job_id = 'review_' + str(uuid.uuid4())[:8]
                work = Path(f"/tmp/rs_uploads/{job_id}")
                img_dir = work / 'images'
                os.makedirs(img_dir, exist_ok=True)

                import base64
                for i, img_data in enumerate(images[:15]):
                    fname = f"image_{i+1:03d}.jpg"
                    try:
                        if img_data.startswith('data:'):
                            b64 = img_data.split(',')[1]
                            (img_dir / fname).write_bytes(base64.b64decode(b64))
                        elif img_data.startswith('http'):
                            import urllib.request
                            urllib.request.urlretrieve(img_data, img_dir / fname)
                        else:
                            (img_dir / fname).write_bytes(base64.b64decode(img_data))
                    except Exception as img_err:
                        log(f"Image save error: {img_err}")

                cfg_out = {
                    'address': addr, 'script': script, 'voice': voice,
                    'price': price, 'beds': beds, 'baths': baths, 'sqft': sqft,
                    'imageCount': len(list(img_dir.iterdir())),
                    'selectedIndices': list(range(len(list(img_dir.iterdir())))),
                    'captionStyle': {'fontSize': font_size, 'highlightColor': text_color.lstrip('#')},
                    'musicUrl': music_url,
                    'userEmail': user_email,
                }
                with open(work / 'pipeline_config.json', 'w') as f:
                    json.dump(cfg_out, f, indent=2)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                resp = {'job_id': job_id, 'status': f'Job created with {len(list(img_dir.iterdir()))} images, building...', 'done': False}
                self.wfile.write(json.dumps(resp).encode())

                def do_send_build():
                    try:
                        import edge_tts, asyncio
                        VENV = '/opt/venv/bin/python3'
                        voice_m4a = work / 'voice.m4a'
                        sel = list(range(min(15, len(list(img_dir.iterdir())))))
                        cap = cfg_out['captionStyle']
                        if script:
                            asyncio.run(edge_tts.Communicate(script, VOICE_MAP.get(voice, ('en-US-JennyNeural', 'hpp4J3VqNfWAUOO0d1Us'))[0]).save(str(voice_m4a)))
                            log(f'Voice generated: {voice_m4a.stat().st_size} bytes')
                        cfg_out['selectedIndices'] = sel
                        with open(work / 'pipeline_config.json', 'w') as f:
                            json.dump(cfg_out, f, indent=2)
                        result = run([VENV, '/opt/video_pipeline/scripts/build_vps.py',
                                      '--work', str(work), '--listing', str(img_dir),
                                      '--duration', str(duration)],
                                     timeout=300, cwd='/opt/video_pipeline')
                        log(f'Slides built: exit={result.returncode}')
                    except Exception as e:
                        log(f'Build error: {e}')

                threading.Thread(target=do_send_build, daemon=True).start()
                return

            except Exception as e:
                log(f'send.php error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        elif p.startswith('/api/status'):
            job_id = p.split('/api/status')[1].lstrip('/')
            if not job_id:
                job_id = payload.get('job_id', '')
            work = Path(f"/tmp/rs_uploads/{job_id}")
            status_file = work / 'status.json'
            if status_file.exists():
                with open(status_file) as f:
                    self.wfile.write(f.read().encode())
            else:
                self.wfile.write(json.dumps({'status': 'unknown'}).encode())

        elif p.startswith('/api/upload-images/'):
            # Upload images to an existing job
            job_id = p.replace('/api/upload-images/', '').split('/')[0]
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                payload = json.loads(body)
                images = payload.get('images', [])
                work = Path(f"/tmp/rs_uploads/{job_id}")
                img_dir = work / 'images'
                os.makedirs(img_dir, exist_ok=True)
                import base64
                for i, img in enumerate(images):
                    fname = img.get('name', f'image_{i+1:03d}.jpg')
                    data = img.get('data', '')
                    if data:
                        try:
                            (img_dir / fname).write_bytes(base64.b64decode(data))
                        except Exception as e:
                            log(f'Image write error: {e}')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                self.end_headers()
                self.wfile.write(json.dumps({'error': None}).encode())
            except Exception as e:
                log(f'Upload error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        elif p.startswith('/api/build/'):
            # Trigger build for an existing job
            job_id = p.replace('/api/build/', '').split('/')[0]
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            if not cfg_file.exists():
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'job not found'}).encode())
                return
            # Idempotency: if already building, return current status
            status_file = work / 'status.json'
            if status_file.exists():
                with open(status_file) as f:
                    st = json.load(f)
                if st.get('status', '').lower() in ('building...', 'done'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': st['status']}).encode())
                    return
            with open(cfg_file) as f:
                cfg = json.load(f)
            img_dir = work / 'images'
            write_job_status(work, 'Building...')
            def do_build():
                try:
                    import edge_tts, asyncio
                    VENV = '/opt/venv/bin/python3'
                    voice_m4a = work / 'voice.m4a'
                    script = cfg.get('script', '')
                    voice = cfg.get('voice', 'Bella')
                    duration = int(cfg.get('duration', 30))
                    if script:
                        asyncio.run(edge_tts.Communicate(
                            script,
                            VOICE_MAP.get(voice, ('en-US-JennyNeural', 'hpp4J3VqNfWAUOO0d1Us'))[0]
                        ).save(str(voice_m4a)))
                        log(f'Voice generated: {voice_m4a.stat().st_size} bytes')
                    sel = list(range(min(15, len(list(img_dir.iterdir())))))
                    cfg['selectedIndices'] = sel
                    with open(cfg_file, 'w') as f:
                        json.dump(cfg, f, indent=2)
                    result = run([VENV, '/opt/video_pipeline/scripts/build_vps.py',
                                  '--work', str(work), '--listing', str(img_dir),
                                  '--duration', str(duration)],
                                 timeout=300, cwd='/opt/video_pipeline')
                    log(f'Slides built: exit={result.returncode}')
                    status_file = work / 'status.json'
                    with open(status_file, 'w') as f:
                        json.dump({'status': 'Done' if result.returncode == 0 else f'Build error {result.returncode}'}, f)
                except Exception as e:
                    log(f'Build error: {e}')
                    status_file = work / 'status.json'
                    with open(status_file, 'w') as f:
                        json.dump({'status': f'Error: {e}'}, f)
            threading.Thread(target=do_build, daemon=True).start()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://vybord.com')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'Building...'}).encode())
            return

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')


def write_job_status(work, text):
    with open(work / 'status.json', 'w') as f:
        json.dump({'status': text}, f)


def cleanup_orphan_jobs(max_age_hours=24):
    """Remove job dirs older than max_age_hours to prevent disk bloat."""
    try:
        rs_dir = Path('/tmp/rs_uploads')
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        for job_dir in rs_dir.iterdir():
            if job_dir.is_dir():
                try:
                    mtime = job_dir.stat().st_mtime
                    if mtime < cutoff:
                        import shutil
                        shutil.rmtree(job_dir)
                        removed += 1
                except Exception:
                    pass
        if removed:
            log(f'Cleaned up {removed} orphan job(s)')
    except Exception as e:
        log(f'Orphan cleanup error: {e}')


if __name__ == '__main__':
    import socketserver
    cleanup_orphan_jobs(max_age_hours=24)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('0.0.0.0', PORT), Handler) as httpd:
        print(f'Review server running on port {PORT}', flush=True)
        httpd.serve_forever()
