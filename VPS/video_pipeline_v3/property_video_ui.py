#!/usr/bin/env python3
"""
Property Video Creator — v4 (fixed)
===================================
Clean deploy with proper \\n escaping in JS strings.
"""
import os, sys, re, time, secrets, subprocess, threading, shutil
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_file, make_response

app = Flask(__name__)
app.secret_key = "pvc-v4-2026"

WORKSPACE   = Path("/root/.openclaw/workspace")
SCRAPED_DIR = WORKSPACE / "scraped_images_v4"
OUTPUT_VIDEO = WORKSPACE / "generated_property_video.mp4"
SCRAPED_DIR.mkdir(exist_ok=True)

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Property Video Creator — v4</title>
<style>
:root{
  --bg:#0f1117;--surface:#1a1d27;--surface2:#242836;--border:#2e3347;
  --accent:#f7c144;--accent2:#e8a020;--text:#e8eaf0;--text-dim:#8b8fa8;
  --green:#3ecf6e;--red:#e85c4a;--blue:#4a9ee8
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;padding:20px}
.container{max-width:860px;margin:0 auto}
.header{text-align:center;margin-bottom:28px}
.version-tag{
  display:inline-block;background:rgba(247,193,68,.1);
  border:1px solid rgba(247,193,68,.3);border-radius:20px;
  padding:4px 16px;font-size:.72rem;color:var(--accent);letter-spacing:.5px;margin-bottom:8px
}
h1{font-size:1.7rem;color:var(--accent);margin-bottom:4px}
.subtitle{color:var(--text-dim);font-size:.88rem}
.url-banner{
  background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:18px 20px;margin-bottom:18px
}
.url-banner-label{
  font-size:.75rem;font-weight:700;color:var(--accent);
  letter-spacing:.5px;text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;gap:6px
}
.url-row{display:flex;gap:10px;align-items:flex-end}
.url-row input{flex:1}
.btn-fetch{
  padding:10px 20px;background:var(--accent);color:#0f1117;
  border:none;border-radius:8px;font-weight:700;font-size:.85rem;
  cursor:pointer;white-space:nowrap;flex-shrink:0;transition:background .2s
}
.btn-fetch:hover{background:var(--accent2)}
.btn-fetch:disabled{opacity:.4;cursor:not-allowed}
.url-status{margin-top:10px;font-size:.78rem}
.url-status .ok{color:var(--green)}
.url-status .err{color:var(--red)}
.url-status .loading{color:var(--accent)}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:22px;margin-bottom:16px
}
.card-title{
  font-size:.75rem;font-weight:700;color:var(--accent);
  letter-spacing:.5px;text-transform:uppercase;margin-bottom:16px;
  display:flex;align-items:center;gap:8px
}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.row-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.full{grid-column:1/-1}
label{display:block;font-size:.78rem;color:var(--text-dim);margin-bottom:5px;font-weight:500}
input,select,textarea{
  width:100%;background:var(--surface2);border:1px solid var(--border);
  border-radius:8px;color:var(--text);padding:10px 12px;font-size:.88rem;
  outline:none;transition:border .2s
}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
textarea{resize:vertical;min-height:68px}
.spacer{margin-top:14px}
input[type=range]{-webkit-appearance:none;background:var(--border);border-radius:4px;height:5px;padding:0}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:var(--accent);cursor:pointer}
.range-val{font-weight:700;color:var(--accent)}
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:5px 0}
.toggle{position:relative;width:42px;height:22px}
.toggle input{opacity:0;width:0;height:0}
.slider{
  position:absolute;cursor:pointer;inset:0;background:var(--border);
  border-radius:20px;transition:.3s
}
.slider:before{
  content:'';position:absolute;height:16px;width:16px;left:3px;bottom:3px;
  background:white;border-radius:50%;transition:.3s
}
.toggle input:checked+.slider{background:var(--green)}
.toggle input:checked+.slider:before{transform:translateX(20px)}
.img-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));
  gap:6px;margin-top:12px
}
.img-thumb{
  aspect-ratio:1;object-fit:cover;border-radius:6px;border:2px solid transparent;
  cursor:pointer;opacity:.65;transition:all .15s;width:100%;display:block;background:var(--surface2)
}
.img-thumb.selected{border-color:var(--accent);opacity:1}
.img-thumb:hover{opacity:1}
.img-meta{font-size:.72rem;color:var(--text-dim);margin-top:8px}
.selected-info{font-size:.76rem;color:var(--text-dim);margin-top:5px}
.btn-primary{
  width:100%;padding:14px;border-radius:8px;background:var(--accent);
  color:#0f1117;border:none;font-size:1rem;font-weight:700;
  cursor:pointer;margin-top:6px;transition:all .2s;display:flex;
  align-items:center;justify-content:center;gap:8px
}
.btn-primary:hover{background:var(--accent2);transform:translateY(-1px)}
.btn-primary:disabled{opacity:.45;cursor:not-allowed;transform:none}
.progress-wrap{margin-top:16px;display:none}
.progress-bar{background:var(--surface2);border-radius:8px;height:6px;overflow:hidden}
.progress-fill{
  background:linear-gradient(90deg,var(--accent2),var(--accent));
  height:100%;border-radius:8px;width:0%;transition:width .4s
}
.progress-text{margin-top:5px;font-size:.76rem;color:var(--text-dim)}
.log-box{
  background:#0d0f15;border:1px solid var(--border);border-radius:8px;
  padding:10px;margin-top:12px;max-height:150px;overflow-y:auto;
  font-family:'Courier New',monospace;font-size:.7rem;color:#8b8fa8;
  white-space:pre-wrap;display:none;line-height:1.5
}
.log-box .log-line{padding:0 2px}
.success-box{
  background:#0a1a0f;border:1px solid #1e4a2a;border-radius:8px;
  padding:16px;margin-top:14px;display:none
}
.success-box a{color:var(--green);word-break:break-all;font-size:.85rem}
.info-tag{
  display:inline-block;background:var(--surface2);border:1px solid var(--border);
  border-radius:4px;padding:2px 8px;font-size:.7rem;color:var(--text-dim);margin-top:4px
}
@media(max-width:600px){.row,.row-3{grid-template-columns:1fr}.url-row{flex-direction:column}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <div class="version-tag">v4 — 2026-03-28</div>
  <h1>Property Video Creator</h1>
  <p class="subtitle">Enter any listing URL, configure your video, generate in minutes</p>
</div>

<div class="url-banner">
  <div class="url-banner-label">&#128269; Step 1 &#8212; Find Property (enter URL to scrape images)</div>
  <div class="url-row">
    <input type="url" id="property_url" placeholder="https://... (any listing URL)">
    <button class="btn-fetch" id="fetchBtn" onclick="fetchImages()">Fetch Images</button>
  </div>
  <div class="url-status" id="urlStatus"></div>
  <div class="img-grid" id="imgGrid"></div>
  <div class="img-meta" id="imgMeta"></div>
  <div class="selected-info" id="selectedInfo"></div>
</div>

<form id="videoForm">

<div class="card">
  <div class="card-title">&#127968; Step 2 &#8212; Property Details</div>
  <div class="full spacer">
    <label>Address</label>
    <input type="text" name="address" id="address" placeholder="Street, City, State ZIP">
  </div>
  <div class="row spacer">
    <div><label>List Price ($)</label><input type="number" name="price" id="price" placeholder="490000"></div>
    <div><label>Beds</label><input type="number" name="beds" id="beds" placeholder="4"></div>
  </div>
  <div class="row spacer">
    <div><label>Baths</label><input type="number" name="baths" id="baths" placeholder="2"></div>
    <div><label>Sq Ft</label><input type="number" name="sqft" id="sqft" placeholder="2089"></div>
  </div>
  <div class="full spacer">
    <label>Features (one per line)</label>
    <textarea name="features" id="features" placeholder="Pool home&#10;New roof&#10;No HOA"></textarea>
  </div>
  <div class="full spacer">
    <label>Custom Narration (leave blank to auto-generate)</label>
    <textarea name="custom_narration" id="custom_narration" style="min-height:56px" placeholder="Leave blank to auto-generate from property details..."></textarea>
  </div>
</div>

<div class="card">
  <div class="card-title">&#128444; Step 3 &#8212; Image &amp; Video Settings</div>
  <div class="row">
    <div>
      <label>Image Source</label>
      <select name="image_folder" id="image_folder" onchange="updateSource()">
        <option value="property_images_juanmiami">JuanMiami MLS Photos</option>
        <option value="property_images">REMAX Medium (802 photos)</option>
        <option value="custom">From scraped URL above</option>
      </select>
    </div>
    <div>
      <label>Images to Use</label>
      <input type="number" name="num_images" id="num_images" min="1" max="802" value="20">
    </div>
  </div>
  <div class="spacer">
    <label>Seconds Per Image <span class="range-val" id="secVal">5s</span></label>
    <input type="range" name="sec_per_image" id="sec_per_image" min="2" max="10" value="5" step="0.5"
      oninput="document.getElementById('secVal').textContent=this.value+'s'">
  </div>
  <div class="row-3 spacer">
    <div>
      <label>Orientation</label>
      <select name="orientation" id="orientation">
        <option value="vertical">Vertical (1080&#215;1920)</option>
        <option value="horizontal">Horizontal (1920&#215;1080)</option>
        <option value="square">Square (1080&#215;1080)</option>
      </select>
    </div>
    <div>
      <label>Quality</label>
      <select name="quality" id="quality">
        <option value="low">Low (fast)</option>
        <option value="middle">Medium</option>
        <option value="high" selected>High</option>
        <option value="very_high">Very High</option>
      </select>
    </div>
    <div>
      <label>Caption Style</label>
      <select name="template" id="template">
        <option value="explosive" selected>Explosive (Yellow)</option>
        <option value="minimalist">Minimalist</option>
        <option value="vibrant">Vibrant</option>
        <option value="hype">Hype</option>
        <option value="retro-gaming">Retro Gaming</option>
        <option value="fast">Fast</option>
        <option value="word-focus">Word Focus</option>
        <option value="line-focus">Line Focus</option>
        <option value="default">Default</option>
      </select>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-title">&#127908; Step 4 &#8212; Voice &amp; Output</div>
  <div class="row">
    <div>
      <label>Voice</label>
      <select name="voice" id="voice">
        <option value="en-US-SarahNeural">Sarah (Female, US)</option>
        <option value="en-US-JennyNeural">Jenny (Female, US)</option>
        <option value="en-US-GuyNeural">Guy (Male, US)</option>
        <option value="en-US-AriaNeural">Aria (Female, US)</option>
        <option value="en-GB-SoniaNeural">Sonia (Female, UK)</option>
        <option value="en-AU-NatashaNeural">Natasha (Female, AU)</option>
        <option value="en-IN-NeerjaNeural">Neerja (Female, IN)</option>
      </select>
    </div>
    <div>
      <label>Font Size (px)</label>
      <input type="number" name="font_size" id="font_size" min="20" max="100" value="55">
    </div>
  </div>
  <div class="spacer">
    <div class="toggle-row">
      <label style="margin:0">Show Captions on Video</label>
      <label class="toggle"><input type="checkbox" name="show_captions" id="show_captions" checked><span class="slider"></span></label>
    </div>
    <div class="toggle-row">
      <label style="margin:0">Auto-upload to Catbox when done</label>
      <label class="toggle"><input type="checkbox" name="auto_upload" id="auto_upload" checked><span class="slider"></span></label>
    </div>
  </div>
</div>

<button type="submit" class="btn-primary" id="submitBtn">&#127916; Generate Video</button>

<div class="progress-wrap" id="progressWrap">
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="progress-text" id="progressText">Starting...</div>
</div>
<div class="log-box" id="logBox"></div>
<div class="success-box" id="successBox">
  <b style="color:var(--green)">&#9989; Video Complete!</b><br><br>
  <b>Download:</b> <a id="dlLink" href="/download" download>Click to Download</a><br><br>
  <b>Catbox:</b> <a id="catLink" href="#" target="_blank"></a>
</div>

</form>
</div>

<script>
var API_BASE = '';
var scrapedCount = 0;
var selectedImages = {};
var sessionId = Math.random().toString(36).slice(2);

function updateSource() {
  var f = document.getElementById('image_folder').value;
  if (f !== 'custom') {
    scrapedCount = 0;
    selectedImages = {};
    document.getElementById('imgGrid').innerHTML = '';
    document.getElementById('imgMeta').textContent = '';
    document.getElementById('selectedInfo').textContent = '';
    document.getElementById('urlStatus').textContent = '';
    document.getElementById('num_images').max = 802;
  }
}

function setStatus(html, cls) {
  document.getElementById('urlStatus').innerHTML = html;
  document.getElementById('urlStatus').className = 'url-status ' + (cls || '');
}

function countSelected() {
  return Object.keys(selectedImages).length;
}

function getSelectedArray() {
  return Object.keys(selectedImages).map(Number).sort(function(a,b){return a-b;});
}

async function fetchImages() {
  var url = document.getElementById('property_url').value.trim();
  var btn = document.getElementById('fetchBtn');
  if (!url) { alert('Enter a URL first'); return; }
  btn.disabled = true;
  btn.textContent = 'Scraping...';
  setStatus('Scraping... please wait', 'loading');
  document.getElementById('imgGrid').innerHTML = '';
  scrapedCount = 0;
  selectedImages = {};
  try {
    var res = await fetch(API_BASE + '/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url, session: sessionId })
    });
    var data = await res.json();
    if (data.error) {
      setStatus('ERROR: ' + data.error, 'err');
      btn.disabled = false; btn.textContent = 'Fetch Images'; return;
    }
    var pollSession = data.session || sessionId;
    var pollCount = 0;
    setStatus('Scraping in progress...', 'loading');
    while (pollCount < 40) {
      await new Promise(function(r){ setTimeout(r, 3000); });
      try {
        var sr = await fetch(API_BASE + '/scrape_status/' + pollSession).then(function(x){ return x.json(); });
        if (sr.status !== 'scraping') {
          scrapedCount = sr.count || 0;
          setStatus(scrapedCount + ' images ready', 'ok');
          document.getElementById('image_folder').value = 'custom';
          document.getElementById('num_images').max = scrapedCount;
          document.getElementById('num_images').value = Math.min(20, scrapedCount);
          if (sr.address) document.getElementById('address').value = sr.address;
          if (sr.price)  document.getElementById('price').value  = sr.price;
          if (sr.beds)   document.getElementById('beds').value   = sr.beds;
          if (sr.baths)  document.getElementById('baths').value  = sr.baths;
          if (sr.sqft)   document.getElementById('sqft').value   = sr.sqft;
          renderGrid(); break;
        }
      } catch(e) {}
      pollCount++;
      setStatus('Scraping... (' + (pollCount*3) + 's)', 'loading');
    }
  } catch(e) { setStatus('ERROR: ' + e.message, 'err'); }
  btn.disabled = false; btn.textContent = 'Fetch Images';
}

function renderGrid() {
  var grid = document.getElementById('imgGrid');
  grid.innerHTML = '';
  for (var i = 0; i < scrapedCount; i++) {
    var div = document.createElement('div');
    var img = document.createElement('img');
    img.className = 'img-thumb' + (selectedImages[i] ? ' selected' : '');
    img.src = API_BASE + '/image/' + i + '?s=' + sessionId;
    img.onclick = (function(idx, el) {
      return function() {
        if (selectedImages[idx]) {
          delete selectedImages[idx];
          el.classList.remove('selected');
        } else {
          selectedImages[idx] = true;
          el.classList.add('selected');
        }
        updateInfo();
      };
    })(i, img));
    div.appendChild(img);
    grid.appendChild(div);
  }
  document.getElementById('imgMeta').textContent = scrapedCount + ' images &#8212; click to select, or all used by default';
  updateInfo();
}

function updateInfo() {
  var el = document.getElementById('selectedInfo');
  var sel = countSelected();
  if (sel > 0) {
    el.textContent = sel + ' selected &#8212; [' + getSelectedArray().join(',') + ']';
  } else {
    el.textContent = scrapedCount + ' images available &#8212; all will be used';
  }
}

document.getElementById('videoForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  var btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerHTML = '&#8987; Generating...';
  var fd = new FormData(e.target);
  var form = {};
  for (var kv of fd.entries()) { form[kv[0]] = kv[1]; }
  if (form.image_folder === 'custom' && scrapedCount > 0) {
    form.scraped_session = sessionId;
    var sel = getSelectedArray();
    if (sel.length > 0) form.selected_indices = sel.join(',');
  }
  document.getElementById('logBox').style.display = 'block';
  document.getElementById('progressWrap').style.display = 'block';
  document.getElementById('successBox').style.display = 'none';
  document.getElementById('logBox').innerHTML = '';
  var logBox = document.getElementById('logBox');
  function log(m) {
    var d = document.createElement('div');
    d.className = 'log-line';
    d.textContent = new Date().toLocaleTimeString() + ' ' + m;
    logBox.appendChild(d);
    logBox.scrollTop = logBox.scrollHeight;
  }
  function setProg(p, s) {
    document.getElementById('progressFill').style.width = p + '%';
    document.getElementById('progressText').textContent = s;
  }
  try {
    log('Starting job...');
    setProg(3, 'Sending...');
    var res = await fetch(API_BASE + '/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form)
    });
    var r = await res.json();
    log('Job accepted &#8212; render takes 3-6 min...');
    setProg(5, 'Rendering video (3-6 min)...');
    var done = false;
    while (!done) {
      await new Promise(function(r2){ setTimeout(r2, 5000); });
      var sr;
      try { sr = await fetch(API_BASE + '/status').then(function(x){ return x.json(); }); }
      catch(e) { sr = {}; }
      setProg(sr.progress || 5, sr.step || 'Rendering...');
      if (sr.log) {
        var lg = sr.log;
        if (lg.length > 100) lg = lg.substring(0, 100);
        log(lg);
      }
      if (sr.done) {
        done = true;
        setProg(100, sr.step || 'Done!');
        if (sr.link) {
          document.getElementById('successBox').style.display = 'block';
          document.getElementById('catLink').href = sr.link;
          document.getElementById('catLink').textContent = sr.link;
          log('\u2705 DONE: ' + sr.link);
        } else if (sr.error) {
          log('\u274C ERROR: ' + sr.error);
        }
      }
    }
  } catch(err) { log('Error: ' + err.message); }
  btn.disabled = false;
  btn.innerHTML = '&#127916; Generate Video';
});
</script>
</body>
</html>"""

# ── Global state ──────────────────────────────────────────────────────────────
job_status = {"done": False, "error": None, "link": None, "progress": 0, "step": "", "log": ""}
_sessions = {}

# ── Scrape & download ──────────────────────────────────────────────────────────
def scrape_and_download(url, session):
    import httpx
    from urllib.parse import urljoin

    global _sessions
    SCRAPED_DIR.mkdir(exist_ok=True)

    driver = None
    try:
        import undetected_chromedriver as uc
        from time import sleep
        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--ignore-ssl-errors")
        driver = uc.Chrome(options=opts, version_main=146)
        driver.set_page_load_timeout(30)
    except Exception as e:
        _sessions[session]["status"] = "error"
        return {"error": "Browser error: " + str(e), "count": 0}

    img_files = []
    address = price = beds = baths = sqft = None

    try:
        driver.get(url)
        sleep(3)
        for pos in [500, 1000, 1500, 2000, 2500, 3000]:
            driver.execute_script("window.scrollTo(0," + str(pos) + ")")
            sleep(0.4)
        sleep(2)
        html = driver.page_source

        addr_m = re.search(r'([\d]+\s+[\w\s]+(?:St|Ave|Rd|Dr|Ln|Blvd|Ct|Way)[^,]{0,70}(?:FL|Florida|FL\s+\d{5}))', html, re.IGNORECASE)
        if not addr_m:
            addr_m = re.search(r'"address"\s*:\s*"([^"]{10,100})"', html)
        address = addr_m.group(1).strip() if addr_m else None

        price_m = re.search(r'[\$]([\d,]+)', html)
        price = int(re.sub(r'[^\d]', '', price_m.group(1))) if price_m else None

        beds_m = re.search(r'(\d+)\s*bed', html, re.IGNORECASE)
        beds = int(beds_m.group(1)) if beds_m else None

        baths_m = re.search(r'(\d+(?:\.\d+)?)\s*bath', html, re.IGNORECASE)
        baths = float(baths_m.group(1)) if baths_m else None

        sqft_m = re.search(r'([\d,]+)\s*sq\.?\s*ft', html, re.IGNORECASE)
        sqft = int(re.sub(r'[^\d]', '', sqft_m.group(1))) if sqft_m else None

        s3_urls = re.findall(
            r'https://loopt-idx\.s3\.us-east-005\.backblazeb2\.com/upload/pictures/trestle/\d+/[A-Z0-9]+/[A-Z0-9]+_\d+\.jpg',
            html)
        s3_urls = sorted(set(s3_urls))

        mls_m = re.search(r'mls-(A119\d+)', url) or re.search(r'A119\d+', html)
        if mls_m:
            mlsp = mls_m.group(0)
            s3_urls = [u for u in s3_urls if mlsp in u]

        count = len(s3_urls)
        if count == 0:
            _sessions[session]["status"] = "done"
            return {"status": "done", "error": "No images found on this page.", "count": 0}

        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        sess = httpx.Client(timeout=30)
        for i, img_url in enumerate(s3_urls):
            fname = SCRAPED_DIR / (session + "_" + ("%03d" % i) + ".jpg")
            if not fname.exists() or fname.stat().st_size < 5000:
                try:
                    r = sess.get(img_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': url})
                    if r.status_code == 200 and len(r.content) > 5000:
                        fname.write_bytes(r.content)
                except:
                    pass
            if fname.exists() and fname.stat().st_size > 5000:
                img_files.append(fname)

        sess.close()
        _sessions[session] = {"status": "done", "count": len(img_files), "files": img_files, "address": address, "price": price, "beds": beds, "baths": baths, "sqft": sqft}
        return {"count": len(img_files), "address": address, "price": price,
                "beds": beds, "baths": baths, "sqft": sqft, "session": session}
    except Exception as e:
        _sessions[session]["status"] = "error"
        _sessions[session]["error_msg"] = str(e)
    finally:
        if driver is not None:
            try: driver.quit()
            except: pass

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(TEMPLATE)

@app.route("/scrape", methods=["POST"])
def scrape():
    from json import loads
    data = loads(request.get_data(as_text=True))
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"})
    session = data.get("session") or secrets.token_hex(4)
    _sessions[session] = {"status": "scraping", "count": 0, "files": [], "address": None, "price": None, "beds": None, "baths": None, "sqft": None}
    t = threading.Thread(target=scrape_and_download, args=(url, session))
    t.start()
    return jsonify({"status": "scraping", "session": session})

@app.route("/scrape_status/<session>")
def scrape_status(session):
    s = _sessions.get(session, {})
    return jsonify({
        "status": s.get("status", "unknown"),
        "count": s.get("count", 0),
        "address": s.get("address"),
        "price": s.get("price"),
        "beds": s.get("beds"),
        "baths": s.get("baths"),
        "sqft": s.get("sqft"),
        "session": session
    })

@app.route("/session_preload", methods=["POST"])
def session_preload():
    """Pre-load a session from disk files (session name prefix)."""
    from json import loads
    d = loads(request.get_data(as_text=True))
    session = d.get("session", "")
    address = d.get("address", "")
    price = d.get("price", "")
    beds = d.get("beds", "")
    baths = d.get("baths", "")
    sqft = d.get("sqft", "")
    files = sorted(SCRAPED_DIR.glob(session + "_*.jpg"))
    _sessions[session] = {
        "status": "done",
        "count": len(files),
        "files": files,
        "address": address,
        "price": price,
        "beds": beds,
        "baths": baths,
        "sqft": sqft
    }
    return jsonify({"status": "loaded", "count": len(files), "session": session})

@app.route("/image/<int:idx>")
def serve_image(idx):
    session = request.args.get("s", "")
    data = _sessions.get(session, {})
    files = data.get("files", [])
    if idx < len(files) and files[idx].exists():
        resp = make_response(files[idx].read_bytes())
        resp.headers['Content-Type'] = 'image/jpeg'
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp
    return "Not found", 404

@app.route("/generate", methods=["POST"])
def generate():
    from json import loads
    form = loads(request.get_data(as_text=True))
    t = threading.Thread(target=_generate_video, args=(form,))
    t.start()
    return jsonify({"status": "ok"})

@app.route("/status")
def status():
    return jsonify(job_status)

@app.route("/download")
def download():
    if OUTPUT_VIDEO.exists():
        return send_file(OUTPUT_VIDEO, as_attachment=True, download_name="property_video.mp4")
    return "Not found", 404

# ── Video generation ──────────────────────────────────────────────────────────
def _generate_video(form):
    global job_status
    job_status = {"done": False, "error": None, "link": None, "progress": 0, "step": "", "log": ""}
    try:
        ws = WORKSPACE
        sel_idx_str = form.get("selected_indices", "")
        sel_idx = sorted([int(x) for x in sel_idx_str.split(",")]) if sel_idx_str else []

        if form.get("image_folder") == "custom" and form.get("scraped_session"):
            session = form["scraped_session"]
            data = _sessions.get(session, {})
            files = data.get("files", [])
            count = data.get("count", 0)
            to_use = sel_idx if sel_idx else list(range(min(int(form.get("num_images", 20)), count)))
            img_files = [files[i] for i in to_use if i < len(files)]
        else:
            folder = form.get("image_folder", "property_images_juanmiami")
            img_dir = ws / folder
            n = int(form.get("num_images", 20))
            img_files = sorted(img_dir.glob("A11989615_*.jpg"))[:n]

        if not img_files:
            raise Exception("No images. Try fetching from URL first.")

        job_status["progress"] = 10
        job_status["step"] = "Building narration..."
        if form.get("custom_narration", "").strip():
            narration = form["custom_narration"].strip()
        else:
            addr  = form.get("address", "")
            price = form.get("price", "")
            beds  = form.get("beds", "")
            baths = form.get("baths", "")
            sqft  = form.get("sqft", "")
            feats = [f.strip() for f in form.get("features", "").strip().split("\n") if f.strip()]
            feat_str = ", ".join(feats[:6])
            price_fmt = ("$" + str(int(price))) if str(price).isdigit() else str(price)
            parts = []
            if addr:
                parts.append("Welcome to this beautiful property at " + addr + ".")
            else:
                parts.append("Welcome to this stunning property.")
            if beds and baths:
                if sqft:
                    parts.append("This stunning " + str(beds) + " bedroom, " + str(baths) + " bathroom home offers " + str(sqft) + " square feet of living space.")
                else:
                    parts.append("This stunning " + str(beds) + " bedroom, " + str(baths) + " bathroom home.")
            elif sqft:
                parts.append("This home offers " + str(sqft) + " square feet of living space.")
            parts.append("Priced at " + price_fmt + ".")
            if feat_str:
                parts.append("Features include " + feat_str + ".")
            parts.append("Don't miss this incredible opportunity. Schedule your showing today.")
            narration = " ".join(parts)

        job_status["progress"] = 15
        job_status["step"] = "Generating audio..."
        audio_path = ws / "ui_narration.mp3"
        voice = form.get("voice", "en-US-AndrewNeural")
        import asyncio, edge_tts
        async def gen_audio():
            communicate = edge_tts.Communicate(narration, voice)
            await communicate.save(str(audio_path))
        asyncio.run(gen_audio())

        job_status["progress"] = 20
        job_status["step"] = "Building slideshow..."
        sec = float(form.get("sec_per_image", 5))
        dur = int(sec * len(img_files))
        orient = form.get("orientation", "vertical")
        wh = {"vertical": (1080, 1920), "horizontal": (1920, 1080)}.get(orient, (1080, 1080))
        w, h = wh

        concat = ws / "ui_concat.txt"
        with open(str(concat), "w") as f:
            for img in img_files:
                f.write("file '" + str(img) + "'\n")
                f.write("duration " + str(sec) + "\n")
            f.write("file '" + str(img_files[-1]) + "'\n")

        raw = ws / "ui_raw.mp4"
        r = subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-vf", "scale=" + str(w) + ":" + str(h) + ":force_original_aspect_ratio=decrease,pad=" + str(w) + ":" + str(h) + ":(ow-iw)/2:(oh-ih)/2:black",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-t", str(dur), str(raw)
        ], capture_output=True, text=True)
        if r.returncode != 0:
            raise Exception("Slideshow build failed: " + r.stderr[-300:])

        job_status["progress"] = 50
        job_status["step"] = "Combining audio..."
        va = ws / "ui_va.mp4"
        r = subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw), "-i", str(audio_path),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(va)
        ], capture_output=True, text=True)
        if r.returncode != 0:
            raise Exception("Audio combine failed: " + r.stderr[-200:])

        job_status["progress"] = 60
        job_status["step"] = "Applying captions..."
        final = ws / "ui_final.mp4"
        template  = form.get("template", "explosive")
        fsize     = form.get("font_size", "55")
        quality   = form.get("quality", "high")
        show_caps = form.get("show_captions", "on")

        subprocess.run(["rm", "-f", str(final)])
        if show_caps:
            pycaps_bin = "/root/.venv/bin/pycaps"
            r = subprocess.run([
                pycaps_bin, "render",
                "--input", str(va), "--output", str(final),
                "--template", template,
                "--style", "word.font-size=" + str(fsize) + "px",
                "--video-quality", quality,
            ], capture_output=True, text=True, cwd=str(ws))
            if r.returncode != 0:
                raise Exception("pycaps failed: " + r.stderr[-400:])
        else:
            shutil.copy(str(va), str(final))

        job_status["progress"] = 90
        job_status["step"] = "Copying output..."
        shutil.copy(str(final), str(OUTPUT_VIDEO))

        job_status["progress"] = 95
        job_status["step"] = "Uploading to Catbox..."
        link = None
        if form.get("auto_upload", "on") == "on":
            r = subprocess.run([
                "curl", "-s", "-F", "reqtype=fileupload",
                "-F", "fileToUpload=@" + str(final),
                "https://catbox.moe/user/api.php"
            ], capture_output=True, text=True, timeout=300)
            if r.returncode == 0 and "catbox.moe" in r.stdout:
                link = r.stdout.strip()

        job_status["progress"] = 100
        job_status["step"] = "Done!"
        job_status["done"] = True
        job_status["link"] = link or ""

    except Exception as e:
        import traceback
        job_status["done"] = True
        job_status["error"] = str(e)
        job_status["log"] = traceback.format_exc()

if __name__ == "__main__":
    print("Property Video Creator v4: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
