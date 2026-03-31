#!/usr/bin/env python3
"""Video Pipeline API Server — FastAPI on VPS. Port 8000."""
import os, sys, json, uuid, asyncio, subprocess, shutil, time, re, smtplib, email.message, hashlib
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import httpx, requests

BASE_DIR = Path('/opt/video_pipeline')
WORK_DIR = BASE_DIR / 'work'
VENV = '/opt/venv/bin/python'
os.makedirs(WORK_DIR, exist_ok=True)

jobs = {}

VOICE_MAP = {
    'Bella':    ('en-US-JennyNeural',  'hpp4J3VqNfWAUOO0d1Us'),
    'Sarah':    ('en-US-AriaNeural',   'EXAVITQu4vr4xnSDxMaL'),
    'Roger':    ('en-US-RogerNeural',  'CwhRBWXzGAHq8TQ4Fs17'),
    'George':   ('en-US-AndrewNeural', 'JBFqnCBsd6RMkjVDRZzb'),
    'Jessica':  ('en-US-AvaNeural',   'cgSgspJ2msm6clMCkdW9'),
    'Charlie':  ('en-US-BrianNeural',  'IKne3meq5aSn9XLyUdCD'),
    'Laura':    ('en-US-EmmaNeural',   'FGY2WhTYpPnrIDTdsKH5'),
    'Liam':     ('en-US-GuyNeural',   'TX3LPaxmHKxFdv7VOQHJ'),
}

# Default slide durations per video duration
DURATION_DEFAULTS = {
    15: (3.0, 5.0),
    30: (4.0, 7.5),
    40: (5.0, 9.0),
    60: (6.0, 12.0),
}

def log(jid, msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] [{jid}] {msg}"
    print(line, flush=True)
    if jid and jid in jobs:
        jobs[jid]['log'].append(line)

def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=600)

def whisper_to_srt(whisper_json_path, srt_path):
    try:
        import json as _json
        with open(whisper_json_path) as _f:
            _data = _json.load(_f)
        with open(srt_path, 'w') as _f:
            for _seg in _data.get('segments', []):
                _s = _seg['start']; _e = _seg['end']; _txt = _seg['text'].strip()
                _sh=int(_s//3600);_sm=int((_s%3600)//60);_ss=int(_s%60);_sms=int((_s-int(_s))*1000)
                _eh=int(_e//3600);_em=int((_e%3600)//60);_es=int(_e%60);_ems=int((_e-int(_e))*1000)
                _f.write('%d\n%02d:%02d:%02d,%03d --> %02d:%02d:%02d,%03d\n%s\n\n' % (
                    _seg.get('id',0)+1,_sh,_sm,_ss,_sms,_eh,_em,_es,_ems,_txt))
        return True
    except Exception as e:
        log(jid, 'SRT err: ' + str(e))
        return False

async def dl(url, dest):
    import shutil, subprocess, os
    if 'youtube.com' in url or 'youtu.be' in url:
        try:
            r = subprocess.run(
                ['/opt/venv/bin/yt-dlp', '-x', '--audio-format', 'mp3', '-o', dest, url],
                capture_output=True, text=True, timeout=120
            )
            return os.path.getsize(dest) if os.path.exists(dest) else 0
        except: pass
        return 0
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(url, timeout=60, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(dest, 'wb') as f:
                    f.write(r.content)
                return len(r.content)
    except: pass
    return 0

def send_email(to, address, price, video_url, size_mb):
    body = f"Your video is ready!\n\nAddress: {address}\nPrice: {price}\nSize: {size_mb}MB\n\nDownload: {video_url}\n\n— Brodly Pipeline"
    msg = email.message.EmailMessage()
    msg['From'] = 'make@grpid.com'
    msg['To'] = to
    msg['Subject'] = f'Video Ready: {address}'
    msg.set_content(body)
    try:
        with smtplib.SMTP('smtp.hostinger.com', 587) as s:
            s.starttls()
            s.login('make@grpid.com', '()ONLy2025T$')
            s.send_message(msg)
        log(None, f"Email sent to {to}")
    except Exception as e:
        log(None, f"Email failed: {e}")

async def pipeline(
    jid, url, voice, max_imgs, email_to, script='',
    duration=30, ratio='16:9', effect='random',
    template='word-focus', font_size=55, text_color='#FF69B4', bg_color='#000000',
    music_url='', music='none', cta='',
    user_images=None,
    transition='smoothleft', images_per_slide=1
):
    j = jobs[jid]
    j['status'] = 'running'
    j['started_at'] = datetime.now().isoformat()
    work = WORK_DIR / jid
    os.makedirs(work, exist_ok=True)

    # Determine slide durations based on target duration
    sl_dur, last_dur = DURATION_DEFAULTS.get(duration, (4.0, 7.5))
    # 3 seconds of silence at end (music continues)
    SILENCE_END = 3.0
    TOTAL_DUR = float(duration)
    VOICE_DUR = TOTAL_DUR - SILENCE_END  # voice fills up to (total - 3s)

    try:
        log(jid, f"Scraping: {url}")
        import requests
        from bs4 import BeautifulSoup

        # ── Step 1: Try scrapling AsyncStealthySession (anti-bot / Cloudflare bypass) ──
        text = ''
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from scrapling.engines._browsers._stealth import AsyncStealthySession
            log(jid, "Trying scrapling AsyncStealthySession...")
            async with AsyncStealthySession() as session:
                result = await session.fetch(url, network_idle=True, timeout=60000,
                                              disable_resources=True)
                content_val = str(result)
            if len(content_val) > 5000:
                text = content_val
                open(work / 'listing.html', 'w').write(text)
                log(jid, f"scrapling OK: {len(text)} chars")
            else:
                log(jid, f"scrapling returned {len(content_val)} chars (too small)")
        except Exception as e:
            log(jid, f"scrapling error: {e}")

        # ── Step 2: Fall back to requests if scrapling failed ──
        if not text or len(text) < 5000:
            log(jid, "Falling back to requests...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            for attempt in range(3):
                try:
                    rp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
                    text = rp.text
                    open(work / 'listing.html', 'w').write(text)
                    log(jid, f"requests: {len(text)} chars, status={rp.status_code}")
                    if len(text) > 10000:
                        break
                    log(jid, f"Page too small (可能被反爬), retry {attempt+1}/3")
                    import time; time.sleep(5)
                except Exception as e:
                    log(jid, f"requests error: {e}, retry {attempt+1}/3")
                    import time; time.sleep(3)

        if len(text) < 5000 and not (user_images and len(user_images) > 0):
            raise Exception("Scraping failed: both scrapling and requests returned < 5KB")
        elif len(text) < 5000:
            log(jid, "Scraping skipped — using provided images")

        soup = BeautifulSoup(text, 'html.parser')
        full_addr = price = beds = baths = sqft = desc = ''
        for tag in soup.find_all(True):
            t = tag.name.lower()
            if t in ('h1','h2','h3','h4') and not full_addr:
                full_addr = re.sub(r'\s+', ' ', tag.get_text()).strip()
            if not price and tag.get('data-testid'):
                if 'price' in tag.get('data-testid','').lower():
                    price = re.sub(r'[^\d$,]', '', tag.get_text()).strip()
        addr_match = re.search(r'class="address[^"]*">([^<]+)', text)
        if addr_match:
            full_addr = addr_match.group(1).strip()
        price_match = re.search(r'\$\d{1,3}(?:,\d{3})*(?:/\w+)?', text)
        if price_match:
            price = price_match.group(0)
        beds_match = re.search(r'(\d+)\s*bed', text, re.I)
        baths_match = re.search(r'(\d+(?:\.\d+)?)\s*bath', text, re.I)
        sqft_match = re.search(r'([\d,]+)\s*sq\s*ft', text, re.I)
        if beds_match: beds = beds_match.group(1)
        if baths_match: baths = baths_match.group(1)
        if sqft_match: sqft = sqft_match.group(1).replace(',','')
        desc_els = soup.find_all('p')
        for p in desc_els[:3]:
            t = p.get_text().strip()
            if 50 < len(t) < 500:
                desc = t
                break
        img_urls = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if 'listhub' in src or 'photo' in src or 'media' in src:
                if src not in img_urls:
                    img_urls.append(src)
        re_urls = re.findall(r'https?://[^\s"\'<>]+\.(?:jpg|jpeg|png)', text)
        clean = []
        seen = set()
        for u in re_urls:
            if any(x in u for x in ['listhub','photo','media','listing','property']):
                u2 = re.sub(r'[?#].*', '', u)
                if u2 not in seen:
                    seen.add(u2)
                    clean.append(u2)
        for u in clean:
            if u not in img_urls:
                img_urls.append(u)
        img_urls = list(dict.fromkeys(img_urls))  # preserve order, dedupe

        # Filter to listing-related images only
        clean = []
        seen = set()
        for u in img_urls:
            u2 = re.sub(r'[?#].*', '', u).split('/')[-1]
            if u2 not in seen and len(u2) > 10:
                seen.add(u2)
                clean.append(u)
        img_urls = clean[:max_imgs * 2]
        log(jid, f"Found {len(img_urls)} raw image URLs")
        log(jid, f"Found: {full_addr} | {price} | {len(img_urls)} images")

        # Prepare listing_dir
        listing_dir = work
        os.makedirs(listing_dir, exist_ok=True)
        n_images = 0

        # ── User uploaded images → save directly, skip scraping ──
        if user_images:
            log(jid, f"Saving {len(user_images)} user-uploaded images...")
            import base64
            n_saved = 0
            for i, img in enumerate(user_images, 1):
                data = img.get('data', '')
                if not data:
                    continue
                if ',' in data:
                    data = data.split(',', 1)[1]
                try:
                    decoded = base64.b64decode(data)
                    if len(decoded) < 5000:
                        continue
                    ext = 'png' if img.get('type', '').lower().find('png') >= 0 else 'jpg'
                    p = listing_dir / f'img{i:02d}.{ext}'
                    with open(p, 'wb') as _f:
                        _f.write(decoded)
                    n_images += 1
                    n_saved += 1
                    log(jid, f"  [{i}] img{i:02d}.{ext} ({len(decoded)//1024}KB)")
                except Exception as _e:
                    log(jid, f"  [{i}] decode error: {_e}")
            log(jid, f"Saved {n_saved} user images")

        if not user_images:
            # ── Scrape images from URL ──
            img_urls = list(dict.fromkeys(img_urls))  # preserve order, dedupe
            # Filter to listing-related images only
            clean = []
            seen = set()
            for u in img_urls:
                u2 = re.sub(r'[?#].*', '', u).split('/')[-1]
                if u2 not in seen and len(u2) > 10:
                    seen.add(u2)
                    clean.append(u2)
            img_urls = clean[:max_imgs * 2]
            log(jid, f"Found {len(img_urls)} raw image URLs")
            log(jid, f"Found: {full_addr} | {price} | {len(img_urls)} images")
            for i, u in enumerate(img_urls[:max_imgs], 1):
                p = listing_dir / f'img{i:02d}.jpg'
                sz = await dl(u, p)
                if sz > 30000:
                    n_images += 1
                    log(jid, f"  [{i}] img{i:02d}.jpg ({sz//1024}KB)")
            log(jid, f"Downloaded {n_images} images")

        j['images'] = n_images
        j['address'] = full_addr
        j['price'] = price

        # Build script — use provided, else auto-generate
        if script and script.strip():
            script = script.strip()
        else:
            ac = re.sub(r',?\s*(MLS|R\d+|RX-)[^,]*', '', full_addr).strip()
            script = f"Welcome to {ac}."
        if beds != '—' and baths != '—':
            script += f" This {beds}-bedroom, {baths}-bathroom"
        if sqft != '—':
            script += f", {sqft} square feet,"
        script += " property offers exceptional value."
        if desc:
            for s in re.split(r'(?<=[.!?])\s+', desc)[:6]:
                if 40 < len(s) < 200:
                    script += f" {s}"
        if cta:
            script += f" {cta}"
        else:
            script += " Call today to schedule your private showing or visit us online to learn more."
            script += " We'd love to tell you more about this beautiful property. Reach out anytime — we're here to help."
        log(jid, f"Script: {len(script.split())} words ({VOICE_DUR}s voice window)")

        # TTS
        voice_m4a = work / 'voice.m4a'
        ev, eid = VOICE_MAP.get(voice, ('en-US-AriaNeural', 'EXAVITQu4vr4xnSDxMaL'))
        log(jid, f"TTS: {voice} ({ev}), target {VOICE_DUR}s voice")
        try:
            import edge_tts
            await edge_tts.Communicate(script, ev).save(str(voice_m4a))
            log(jid, "TTS OK")
        except Exception as e1:
            log(jid, f"TTS failed ({e1}), 11 Labs fallback")
            try:
                import urllib.request
                data = json.dumps({'text': script, 'model_id': 'eleven_flash_v2_5',
                    'voice_settings': {'stability': 0.5, 'similarity_boost': 0.8}}).encode()
                req = urllib.request.Request(
                    f'https://api.elevenlabs.io/v1/text-to-speech/{eid}',
                    data=data,
                    headers={'xi-api-key': 'sk_8fc024b5406b1e3ac437db283f36bb69a40a13b5e72c6041',
                             'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=60) as r:
                    with open(voice_m4a, 'wb') as f:
                        f.write(r.read())
                log(jid, "11 Labs OK")
            except Exception as e2:
                raise Exception(f"TTS failed: {e2}")

        # Whisper
        r = run([VENV, '-m', 'whisper', str(voice_m4a), '--model', 'small',
                  '--output_dir', str(work), '--output_format', 'json',
                  '--word_timestamps', 'True', '--language', 'en'])
        wj = work / 'voice.json'
        if wj.exists():
            whisper_to_srt(wj, work/'voice.srt')
            shutil.copy2(wj, work/'voice_transcript.json')
        vd = float((run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1', str(voice_m4a)]
                     )).stdout.strip() or 0)
        log(jid, f"Voice: {vd:.1f}s")

        # Music
        music_file = None
        if music_url:
            log(jid, f"Downloading music from: {music_url}")
            mf = work / 'music.mp3'
            sz = await dl(music_url, mf)
            if sz > 50000:
                music_file = str(mf)
                log(jid, f"Music downloaded: {sz//1024}KB")
            else:
                log(jid, "Music download failed, proceeding without music")
        elif music and music != 'none':
            # Built-in presets — check for local music files
            preset_paths = [
                Path('/opt/video_pipeline/music') / f'{music}.mp3',
                Path('/opt/video_pipeline/music') / f'{music}_1.mp3',
            ]
            for pp in preset_paths:
                if pp.exists():
                    music_file = str(pp)
                    log(jid, f"Music preset: {music}")
                    break

        # Config for build
        n = min(15, n_images)
        if n == 0:
            raise Exception("No images downloaded")

        # Determine actual number of slides and durations
        # Total video = sum of slide durations + 3s silence at end
        # Voice fills (total - 3s), slides are distributed to fill that time
        actual_voice_dur = min(vd, VOICE_DUR)

        # KB patterns
        kb_path = Path('/opt/video_pipeline/kb_patterns.json')
        kb = json.load(open(kb_path)) if kb_path.exists() else {'patterns': [{}]*15}

        # Apply effect: random selects from patterns
        if effect == 'random':
            import random
            selected_patterns = random.sample(kb.get('patterns', []), min(n, len(kb.get('patterns', []))))
            while len(selected_patterns) < n:
                selected_patterns.extend(kb.get('patterns', []))
            kb['patterns'] = selected_patterns[:n]
        elif effect == 'zoom':
            for p in kb.get('patterns', []):
                p['zoom'] = 1.4; p['zoom_dir'] = 'zoom_in'
        elif effect == 'slow':
            for p in kb.get('patterns', []):
                p['zoom'] = 1.05
        elif effect == 'vintage':
            pass  # handled in ffmpeg filter
        elif effect == 'glow':
            pass  # handled in ffmpeg filter

        # Set durations per slide
        for i, p in enumerate(kb.get('patterns', [])[:n]):
            dur = last_dur if i == n - 1 else sl_dur
            p['duration'] = dur
            p['fade_out_start'] = dur - 1.0
            p['fade_out_dur'] = 1.0
        kb['image_count'] = n
        kb['slide_duration'] = sl_dur
        kb['last_slide_duration'] = last_dur
        kb['total_duration'] = TOTAL_DUR
        kb['silence_end'] = SILENCE_END
        json.dump(kb, open(work/'kb.json','w'), indent=2)

        # Caption / PyCaps config
        cfg = {
            'address': full_addr, 'price': price, 'beds': beds, 'baths': baths, 'sqft': sqft,
            'script': script, 'listingType': 'Real Estate',
            'captionStyle': {
                'fontSize': font_size,
                'highlightColor': text_color.lstrip('#'),
                'glowIntensity': 'explosive' if template == 'explosive' else 'medium',
            },
            'template': template,
            'voice': voice, 'imageCount': n, 'selectedIndices': list(range(n)),
            'ratio': ratio,
        }
        json.dump(cfg, open(work/'pipeline_config.json','w'), indent=2)

        # Build video
        log(jid, f"Building {n}-image video ({TOTAL_DUR}s, {ratio})...")
        elite_py = Path('/opt/video_pipeline/scripts/build_vps.py')
        if not elite_py.exists():
            raise Exception(f"build_vps.py not found at {elite_py}")

        build_cmd = [
            VENV, str(elite_py),
            '--work', str(work),
            '--listing', str(listing_dir),
            '--output', str(work/'video.mp4'),
            '--config', str(work/'pipeline_config.json'),
            '--kb', str(work/'kb.json'),
            '--duration', str(TOTAL_DUR),
            '--ratio', ratio,
            '--effect', effect,
            '--transition', transition,
            '--images_per_slide', str(images_per_slide),
        ]
        if music_file:
            build_cmd += ['--music', music_file]

        r = run(build_cmd, cwd=str(elite_py.parent))
        if r.returncode != 0:
            raise Exception(f"Build failed: {r.stderr[-300:]}")
        for line in r.stdout.split('\n'):
            if line.strip():
                log(jid, f"  {line.strip()}")

        # Compress
        run(['ffmpeg', '-y', '-i', str(work/'video.mp4'),
              '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
              '-c:a', 'aac', '-b:a', '192k',
              str(work/'video_compressed.mp4')])
        final = work/'video_compressed.mp4'
        if not final.exists():
            final = work/'video.mp4'

        # Upload
        log(jid, "Uploading...")
        vsz = os.path.getsize(final)
        log(jid, f"Video: {vsz//1024//1024}MB")
        with open(final, 'rb') as f:
            r = requests.post('https://store-na-phx-5.gofile.io/contents/uploadfile',
                           files={'file': (f'video_{jid[:8]}.mp4', f, 'video/mp4')}, timeout=180)
        data = r.json()
        vurl = (data.get('data', {}) or {}).get('downloadPage', '') if data.get('status') == 'ok' else ''
        if not vurl:
            with open(final, 'rb') as f:
                r = requests.post('https://catbox.moe/user/api.php',
                               data={'reqtype': 'fileupload'},
                               files={'fileToUpload': f}, timeout=180)
            if r.status_code == 200 and r.text.startswith('https://'):
                vurl = r.text.strip()
        log(jid, f"Done: {vurl}")
        j['status'] = 'done'
        j['video_url'] = vurl
        j['size_mb'] = vsz // 1024 // 1024
        j['completed_at'] = datetime.now().isoformat()
        if email_to:
            send_email(email_to, full_addr, price, vurl, vsz//1024//1024)

    except Exception as e:
        log(jid, f"ERROR: {e}")
        j['status'] = 'failed'
        j['error'] = str(e)
        j['completed_at'] = datetime.now().isoformat()

# ── FastAPI ───────────────────────────────────────────────────────────
app = FastAPI(title='Video Pipeline API', version='2.0')

class GenReq(BaseModel):
    url: str
    voice: str = 'Sarah'
    max_images: int = 15
    email: str = None
    # User-uploaded images (base64, skip image scraping if provided)
    images: list = []
    # Video settings
    duration: int = 30       # 15/30/40/60 seconds
    ratio: str = '16:9'      # '16:9' or '9:16'
    effect: str = 'random'   # random/kenburns/zoom/slow/vintage/glow/contrast
    # Caption / PyCaps
    template: str = 'word-focus'
    font_size: int = 55
    text_color: str = '#FF69B4'
    bg_color: str = '#000000'
    # Music
    music_url: str = ''
    music: str = 'none'      # none/upbeat/chill/cinematic or URL
    # Script
    cta: str = ''
    script: str = ''
    # Slide settings
    transition: str = 'smoothleft'   # smoothleft/smoothright/fade/zoom/blur
    images_per_slide: int = 1       # how many images per slide

class GenResp(BaseModel):
    job_id: str
    status: str
    created_at: str

@app.get('/')
async def root():
    return {'service': 'Video Pipeline API', 'version': '2.0', 'status': 'running'}

@app.get('/health')
async def health():
    return {'status': 'ok', 'jobs': len(jobs)}

@app.post('/generate', response_model=GenResp)
async def generate(req: GenReq, bg: BackgroundTasks):
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {'status': 'pending', 'created_at': datetime.now().isoformat(),
                 'address': req.url, 'log': []}
    bg.add_task(
        pipeline, jid, req.url, req.voice, req.max_images, req.email,
        duration=req.duration, ratio=req.ratio, effect=req.effect,
        template=req.template, font_size=req.font_size,
        text_color=req.text_color, bg_color=req.bg_color,
        music_url=req.music_url, music=req.music, cta=req.cta,
        user_images=req.images or None,
        script=req.script or '',
        transition=req.transition, images_per_slide=req.images_per_slide
    )
    return GenResp(job_id=jid, status='pending', created_at=jobs[jid]['created_at'])

@app.get('/status/{jid}')
async def status(jid: str):
    if jid not in jobs:
        raise HTTPException(404, 'Job not found')
    j = jobs[jid]
    return {
        'job_id': jid, 'status': j['status'],
        'address': j.get('address', ''), 'price': j.get('price', ''),
        'images': j.get('images', 0), 'video_url': j.get('video_url', ''),
        'size_mb': j.get('size_mb', 0), 'error': j.get('error', ''),
        'created_at': j.get('created_at', ''), 'completed_at': j.get('completed_at', ''),
        'log': j.get('log', [])[-20:],
    }

@app.get('/jobs')
async def list_jobs():
    return [{'job_id': k, 'status': v['status'], 'created_at': v['created_at']}
            for k, v in jobs.items()]

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')
