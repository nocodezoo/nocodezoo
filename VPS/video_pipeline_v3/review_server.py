#!/usr/bin/env python3
"""Review Web Server — VPS version with full pipeline. Port 7073."""
import signal  # noqa: E402
signal.signal(signal.SIGPIPE, signal.SIG_IGN)  # prevent crashes on disconnected clients
import http.server, socketserver, json, os, subprocess, shutil, re, uuid, time
from dotenv import load_dotenv; load_dotenv(override=True)
import asyncio, threading
from urllib.parse import urlparse
from pathlib import Path
import sys
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta

# Load .env so we can share JWT_SECRET with main.py
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from auth import decode_token, COOKIE_NAME
from queue_manager import init_dispatcher, enqueue, get_queue_position, USER_DB
from email_automation import capture_lead as _email_capture_lead

PORT = int(os.getenv("PORT", 7073))

# ─── In-memory per-user rate limiter ──────────────────────────────────────────
# Sliding window using sorted list of request timestamps per key.
# Limits are enforced AFTER auth so we rate-limit by user_id, not IP.
# A cleanup thread runs periodically to avoid unbounded memory growth.

class RateLimiter:
    def __init__(self):
        self._buckets = {}          # key → sorted list of request timestamps
        self._lock = threading.Lock()
        self._cleanup_interval = 300  # cleanup every 5 minutes
        self._last_cleanup = time.time()
        # Limits: (max_requests, window_seconds)
        self._limits = {
            '/api/generate':       (10, 60),    # 10 gen/min per user
            '/api/scrape':         (10, 60),    # 10 scrape/min per user
            '/api/model-video':    ( 5, 60),    # 5 model-video/min per user
            '/api/build':          (10, 60),    # 10 rebuilds/min per user
            '/api/script/generate':(20, 60),    # 20 script-gen/min per user
            '/api/upload-images':  (30, 60),    # 30 upload/min per user
            '/api/save':           (30, 60),    # 30 saves/min per user
        }
        self._default_limit = (60, 60)           # 60 req/min default for other api calls

    def _cleanup(self):
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - 120  # drop entries older than 2 minutes
        with self._lock:
            for key, timestamps in list(self._buckets.items()):
                # Remove old timestamps in-place to avoid dict churn
                while timestamps and timestamps[0] < cutoff:
                    timestamps.pop(0)
                if not timestamps:
                    del self._buckets[key]

    def _clean_expired(self, key):
        """Remove timestamps outside the sliding window for a given key."""
        now = time.time()
        limit, window = self._limits.get(key, self._default_limit)
        cutoff = now - window
        timestamps = self._buckets.get(key, [])
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        self._buckets[key] = timestamps

    def check(self, key, user_id=None):
        """Returns (allowed: bool, retry_after_seconds: int).
        key is the endpoint path prefix (e.g. '/api/generate').
        user_id is required for authed endpoints.
        """
        self._cleanup()

        # Build the bucket key: use user_id for authed calls, else IP-based (IP comes from HTTPRequestHandler)
        if user_id:
            bucket_key = f"u:{user_id}:{key}"
        else:
            # For unauthenticated calls, use remote IP
            bucket_key = f"ip:{key}"

        now = time.time()
        limit, window = self._limits.get(key, self._default_limit)

        with self._lock:
            if bucket_key not in self._buckets:
                self._buckets[bucket_key] = []

            timestamps = self._buckets[bucket_key]

            # Remove timestamps outside the sliding window
            cutoff = now - window
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)

            if len(timestamps) >= limit:
                # How long until the oldest request exits the window?
                retry_after = int(timestamps[0] + window - now) + 1
                return False, max(1, retry_after)

            timestamps.append(now)
            return True, 0

    def limit_info(self, key, user_id=None):
        """Return (current_count, limit, window_seconds) for monitoring."""
        if user_id:
            bucket_key = f"u:{user_id}:{key}"
        else:
            bucket_key = f"ip:{key}"
        with self._lock:
            timestamps = self._buckets.get(bucket_key, [])
            now = time.time()
            limit, window = self._limits.get(key, self._default_limit)
            cutoff = now - window
            active = [t for t in timestamps if t >= cutoff]
            return len(active), limit, window

_rate_limiter = RateLimiter()


def _rate_limit_response(seconds):
    """Return a 429 Too Many Requests response dict."""
    body = json.dumps({'error': 'Rate limit exceeded', 'retry_after': seconds})
    return (
        429,
        [('Content-Type', 'application/json'),
         ('Retry-After', str(seconds)),
         ('Access-Control-Allow-Origin', 'https://vybord.com'),
         ('Access-Control-Allow-Credentials', 'true')],
        body.encode()
    )


def _trigger_next_pending():
    """Called after global lock is released. If pending builds exist, launch the next one.
    Re-acquires lock inline (no reliance on do_POST closures)."""
    if not _PENDING_BUILDS:
        return
    job_id = _PENDING_BUILDS.pop(0)
    work = Path(f"/tmp/rs_uploads/{job_id}")
    cfg_file = work / 'pipeline_config.json'
    if not cfg_file.exists():
        log(f'Queued job {job_id} config gone, skipping')
        _trigger_next_pending()  # try next
        return
    # Re-acquire lock inline (imports are cached so this is safe)
    import time as _time
    _lock = Path('/tmp/rs_uploads/.global_build.lock')
    acquired = False
    for _ in range(60):  # wait up to 60s for lock (separate from the original 120s wait)
        if _lock.exists():
            try:
                pid = int(_lock.read_text().strip())
                import os as _os
                _os.kill(pid, 0)
                _time.sleep(1)
                continue
            except (ValueError, ProcessLookupError, OSError):
                try: _lock.unlink()
                except: pass
        try:
            _lock.write_text(str(__import__('os').getpid()))
            acquired = True
            log(f'Queue: acquired lock for {job_id}')
            break
        except:
            _time.sleep(1)
            continue
    if not acquired:
        log(f'Queue: could not re-acquire lock for {job_id}, re-queuing')
        _PENDING_BUILDS.insert(0, job_id)  # put back at front
        return
    # Re-launch build in a daemon thread
    def do_queued_build():
        try:
            import sys as _sys
            _sys.path.insert(0, '/opt/video_pipeline_v3/scripts')
            from build_vps import build_slides
            from typer.testing import CliRunner
            from pycaps.cli.render_cli import render_app
            import asyncio, gtts, edge_tts
            cfg = {}
            with open(cfg_file) as f:
                cfg = json.load(f)
            work = Path(f"/tmp/rs_uploads/{job_id}")
            img_dir = work / 'listing_src'
            voice_m4a = work / 'voice.m4a'
            captioned = work / 'video_captioned.mp4'
            script = cfg.get('script', '')
            voice = cfg.get('voice', 'Roger')
            addr = cfg.get('address', 'Listing')
            price = cfg.get('price', '')
            beds = cfg.get('beds', '')
            baths = cfg.get('baths', '')
            sqft = cfg.get('sqft', '')
            duration = int(cfg.get('duration', 60) or 60)
            sel_indices = cfg.get('selectedIndices', list(range(15)))
            caption_style = cfg.get('captionStyle', {})
            ratio = cfg.get('ratio', '9:16')
            logo_cfg = cfg.get('logoPath', '')
            logo_size = int(cfg.get('logoSize', 15))
            logo_position = cfg.get('logoPosition', 'bottom-right')
            def write_status(msg, done=False, video_path='', progress=0, **kw):
                try:
                    with open(work / 'status.json', 'w') as f:
                        json.dump({'status': msg, 'done': done, 'video': video_path,
                                   'progress': progress, 'address': addr, 'price': price,
                                   'beds': beds, 'baths': baths, 'sqft': sqft,
                                   'images': len(list(img_dir.iterdir())) if img_dir.exists() else 0, **kw}, f)
                except: pass
            write_status('Generating voice...', progress=5)
            edge_voice = get_edge_voice(voice)
            try:
                asyncio.run(edge_tts.Communicate(script, edge_voice).save(str(voice_m4a)))
                if voice_m4a.stat().st_size == 0:
                    raise ValueError('empty')
            except:
                try:
                    gtts.gTTS(script, lang='en').save(str(voice_m4a))
                except Exception as e2:
                    log(f'GTTS fallback error: {e2}')
            if not voice_m4a.exists() or voice_m4a.stat().st_size == 0:
                log(f'Warning: voice file empty for {job_id}')
            # Whisper
            try:
                from whisper import transcribe
                result = transcribe(str(voice_m4a))
                segments = result.get('segments', [])
                voice_srt = work / 'voice.srt'
                def _fmt(t):
                    h = int(t // 3600); m = int(t % 3600 // 60); s = int(t % 60); ms = int((t % 1) * 1000)
                    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
                with open(voice_srt, 'w') as f:
                    for i, seg in enumerate(segments):
                        f.write(f'{i+1}\n{_fmt(seg.get("start",0))} --> {_fmt(seg.get("end",0))}\n{seg.get("text","").strip()}\n\n')
                log(f'Whisper done: {len(segments)} segments')
            except Exception as e:
                log(f'Whisper error: {e}')
            motion_val = cfg.get('motion', 'cinematic')
            write_status('Building slides...', progress=30)
            VENV = '/opt/venv/bin/python3'
            result = subprocess.run(
                [VENV, '/opt/video_pipeline_v3/scripts/build_vps.py',
                 '--work', str(work),
                 '--listing', str(img_dir),
                 '--duration', str(duration),
                 '--motion', motion_val,
                 '--ratio', ratio,
                 '--images_per_slide', '1'],
                capture_output=True, text=True, timeout=300
            )
            log(f'Slides built: exit={result.returncode}')
            if result.returncode != 0:
                log(f'BUILD ERR: {result.stderr[-300:]}')
                write_status('Error: slide build failed', done=False)
                _lock.unlink(missing_ok=True)
                _trigger_next_pending()
                return
            # Captions, audio, final — same as original do_build
            fs = caption_style.get('fontSize', 55)
            hc = caption_style.get('highlightColor', '#FFFF00')
            fc = caption_style.get('fontColor', '#FFFFFF')
            # Use video_wna.mp4 (slides + voice) for pycaps, NOT video_noaudio.mp4.
            # pycaps needs audio to re-transcribe via Whisper (even with --transcript).
            video_for_captions = work / 'video_wna.mp4'
            orig_cwd = os.getcwd()
            try:
                os.chdir('/opt/video_pipeline_v3')
                r2 = CliRunner(mix_stderr=False).invoke(render_app, [
                    '--input', str(video_for_captions), '--output', str(captioned),
                    '--template', 'hype', '--transcript', str(work / 'voice.srt'),
                    '--transcript-format', 'srt',
                    '--style', f'word.font-size={fs}px',
                    '--style', f'word-being-narrated.color={hc}!important',
                    '--style', f'word-already-narrated.color={fc}!important',
                    '--style', f'word.color={fc}!important',
                    '--video-quality', 'high',
                ])
                log(f'Captions applied: exit={r2.exit_code if r2 else 1}')
            finally:
                os.chdir(orig_cwd)
            captions_ok = captioned.exists() and captioned.stat().st_size > 1000
            if not captions_ok:
                shutil.copy2(video_for_captions, captioned)
            # --- Music mix ---
            final_ts = datetime.now().strftime('%H%M%S')
            ts_music = f'video_music_{final_ts}.mp4'
            music_out = str(work / ts_music)
            final_path = _mix_music(str(captioned), music_out, work, cfg.get('music', 'ambient_piano'))
            ts_video = Path(final_path).name
            log(f'Final video: {ts_video}')
            # History
            vp = work / 'videos.json'
            videos_list = [ts_video]
            if vp.exists():
                with open(vp) as vf:
                    videos_list = [ts_video] + json.load(vf).get('videos', [])
            with open(vp, 'w') as vf:
                json.dump({'videos': videos_list}, vf)
            write_status('Complete!', done=True, video_path=ts_video, videos=videos_list)
            _update_video_status(job_id, 'completed', datetime.now().isoformat())
        except Exception as e:
            log(f'Queued build error {job_id}: {e}')
            try:
                write_status(f'Error: {e}', done=False)
            except:
                pass
        finally:
            try:
                _lock.unlink(missing_ok=True)
            except:
                pass
            _trigger_next_pending()
    threading.Thread(target=do_queued_build, daemon=True).start()

def _insert_video_record(user_id, job_id):
    """Insert a video job record into the users DB. Silently fails if DB unavailable."""
    try:
        conn = sqlite3.connect(str(USER_DB), timeout=5)
        conn.execute("INSERT OR IGNORE INTO videos (user_id, job_id, status, created_at) VALUES (?, ?, 'processing', ?)",
                     (user_id, job_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f'[DB] video record insert failed: {e}')

def _update_video_status(job_id, status, completed_at=None):
    """Update video job status in users DB."""
    try:
        conn = sqlite3.connect(str(USER_DB), timeout=5)
        if completed_at:
            conn.execute("UPDATE videos SET status=?, completed_at=? WHERE job_id=?",
                         (status, completed_at, job_id))
        else:
            conn.execute("UPDATE videos SET status=? WHERE job_id=?", (status, job_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f'[DB] video status update failed: {e}')
CURRENT_JOB_ID = [None]  # thread-safe mutable container
WORK_DIR = Path('/opt/video_pipeline_v3/work')
LISTING_DIR_BASE = WORK_DIR / 'review_images'

# Per-job locks to prevent concurrent script generation for the same job
_script_gen_locks = {}
_script_gen_lock = threading.Lock()


# ── AI Script Generation via MiniMax ──────────────────────────────────────────
_MINIMAX_KEY = None

def _get_minimax_key():
    global _MINIMAX_KEY
    if _MINIMAX_KEY:
        return _MINIMAX_KEY
    # Read from .env files — same pattern Hermes uses
    for env_path in [
        Path.home() / '.hermes' / '.env',
        Path('/opt/video_pipeline_v3/.env'),
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith('MINIMAX_API_KEY='):
                    _MINIMAX_KEY = line.split('=', 1)[1].strip()
                    return _MINIMAX_KEY
    return None


def _make_script(addr, beds, baths, sqft, price, duration):
    """Template-based fallback — used only if MiniMax API is unavailable."""
    def fmt_price(p):
        try:
            num = int(str(p).replace(',', '').replace('$', '').strip())
            return f'${num:,}'.replace(',', '')
        except:
            return str(p) if p else ''

    facts = []
    if beds:
        facts.append(f'{beds}')
    if baths:
        facts.append(f'{baths}')
    if sqft:
        sqft_clean = str(sqft).strip()
        if 'sq' not in sqft_clean.lower() and 'ft' not in sqft_clean.lower():
            sqft_clean += ' sq ft'
        facts.append(sqft_clean)
    prop_str = ' '.join(facts) if facts else ''

    import random
    middle_options = [
        ' This beautiful home features an open floor plan, bathed in natural light, with quality finishes throughout every room.',
        ' Every space has been thoughtfully updated to feel warm and welcoming the moment you walk through the door.',
        ' The primary suite offers generous proportions and a calm, comfortable feel — a true retreat at the end of each day.',
        ' The kitchen is ready for everything from your morning coffee to dinner with friends, with practical space for every occasion.',
        ' Step outside to your private outdoor space — ideal for quiet mornings with coffee, golden afternoon light, and easy evening gatherings.',
        ' A wonderful layout with lovely natural light fills every room, highlighting beautiful details and creating a warm atmosphere throughout.',
        ' Natural light pours through the home day and evening, showing off quality finishes and a welcoming feel in every space.',
        ' This is a home built for real life — comfortable, practical, and designed for making new memories with family and friends.',
    ]

    chosen = random.sample(middle_options, min(5, len(middle_options)))
    parts = [f'Welcome to this beautiful property.']
    if prop_str:
        parts.append(f' {prop_str}.')
    parts.extend(chosen)
    if price:
        parts.append(f' Priced at {fmt_price(price)}.')
    parts.append(f' Come see it for yourself.')

    script = ' '.join(parts)
    # Hard cap: never exceed 950 chars
    if len(script) > 950:
        script = script[:950]
    return script


def _generate_script_ai(addr, beds, baths, sqft, price, duration):
    """Generate a real estate narration script using MiniMax AI.
    Falls back to template if API is unavailable or fails."""
    key = _get_minimax_key()
    log(f'[ScriptGen] DEBUG: key found = {bool(key)}, key_prefix = {key[:8] if key else "NONE"}')
    log(f'[ScriptGen] DEBUG: calling MiniMax API...')
    if not key:
        log('[ScriptGen] No MINIMAX_API_KEY found — using template fallback')
        return _make_script(addr, beds, baths, sqft, price, duration)

    # Build a concise property summary for the prompt
    details = []
    if beds: details.append(f"{beds.strip()}")
    if baths: details.append(f"{baths.strip()}")
    if sqft:
        sq = str(sqft).strip()
        if 'sq' not in sq.lower() and 'ft' not in sq.lower():
            sq += ' sq ft'
        details.append(sq)
    if price:
        try:
            num = int(str(price).replace(',', '').replace('$', '').strip())
            details.append(f'${num:,}')
        except:
            details.append(str(price))

    prop_str = ', '.join(details) if details else 'a beautiful property'
    style_note = ''
    if duration and int(duration or 0) <= 30:
        style_note = ' Keep it very concise — 2 to 3 short sentences total.'

    prompt = (
        f"Write a short, enthusiastic real estate video narration script.{style_note}\n"
        f"Property features: {prop_str}.\n"
        f"Requirements:\n"
        f"- 2 to 4 sentences maximum\n"
        f"- No commas, no periods, no quotation marks\n"
        f"- Natural, conversational tone — like a friendly agent showing the home\n"
        f"- Do NOT include the price in the script\n"
        f"- Do NOT include any broker name or contact info\n"
        f"- Do NOT exceed 250 words\n"
        f"- Start with something inviting like 'Welcome to this beautiful property'\n"
        f"Output only the script — no preamble, no explanation."
    )

    payload = {
        "model": "MiniMax-M2.7",
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        import httpx
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.minimax.io/anthropic/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code != 200:
            log(f'[ScriptGen] MiniMax API error {resp.status_code}: {resp.text[:200]}')
            return _make_script(addr, beds, baths, sqft, price, duration)

        data = resp.json()
        log(f'[ScriptGen] DEBUG: response keys = {list(data.keys())}, content type = {type(data.get("content"))}')
        content = data.get("content", [])
        if isinstance(content, list) and len(content) > 0:
            script = content[0].get("text", "").strip()
        else:
            log(f'[ScriptGen] DEBUG: content is not a list: {repr(content)[:200]}')
            script = str(content).strip() if content else ""

        log(f'[ScriptGen] DEBUG: raw script (first 200): {script[:200]}')

        # Clean: remove any残留 quotes, commas, periods
        import re
        if not script:
            log('[ScriptGen] Empty script from AI — using template')
            return _make_script(addr, beds, baths, sqft, price, duration)
        script = re.sub(r'["\']', '', script)
        script = re.sub(r',\s*', ' ', script)
        script = re.sub(r'\.\s+', '. ' if len(script) < 200 else ' ')

        # Hard cap at 950 chars
        if len(script) > 950:
            script = script[:950].rsplit(' ', 1)[0]

        log(f'[ScriptGen] AI generated script: {script[:60]}...')
        return script

    except Exception as e:
        log(f'[ScriptGen] MiniMax exception: {e} — using template fallback')
        return _make_script(addr, beds, baths, sqft, price, duration)

def get_job_listing_dir(job_id):
    # Try both with and without 'review_' prefix
    for jid in [job_id, job_id.replace("review_", "")]:
        for path in [
            Path(f"/opt/video_pipeline_v3/work/{jid}/listing_src"),
            Path(f"/tmp/rs_uploads/{jid}/listing_src"),
            Path(f"/opt/video_pipeline_v3/work/{jid}/images"),
            Path(f"/tmp/rs_uploads/{jid}/images"),
        ]:
            if path.exists():
                return path
    # Last fallback: global listing dir
    return LISTING_DIR_BASE

def get_job_config(job_id):
    # Try both with and without 'review_' prefix — different code paths create jobs differently
    for jid in [job_id, job_id.replace("review_", "")]:
        for cfg_path in [
            Path(f"/opt/video_pipeline_v3/work/{jid}/pipeline_config.json"),
            Path(f"/opt/video_pipeline_v3/work/{jid}/review_config.json"),
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
WWW_DIR = Path('/opt/video_pipeline_v3/review_www')
VENV = '/opt/venv/bin/python'
ELEVENLABS_API_KEY = 'sk_8fc024b5406b1e3ac437db283f36bb69a40a13b5e72c6041'

# Keyed by "lang:voicename" → (edge_voice, display_name)
# Languages: en-US, en-GB, en-AU, en-IN, es, fr, de
VOICE_MAP = {
    # ── English (US) ─────────────────────────────────────────────────────────
    'en-US:Roger':       ('en-US-RogerNeural',       'Roger (US)'),
    'en-US:Jenny':       ('en-US-JennyNeural',       'Jenny (US)'),
    'en-US:Aria':        ('en-US-AriaNeural',         'Aria (US)'),
    'en-US:Ana':         ('en-US-AnaNeural',          'Ana (US)'),
    'en-US:Andrew':      ('en-US-AndrewNeural',      'Andrew (US)'),
    'en-US:Emma':        ('en-US-EmmaNeural',         'Emma (US)'),
    'en-US:Brian':       ('en-US-BrianNeural',        'Brian (US)'),
    'en-US:Eric':        ('en-US-EricNeural',         'Eric (US)'),
    'en-US:Guy':         ('en-US-GuyNeural',          'Guy (US)'),
    'en-US:Michelle':    ('en-US-MichelleNeural',     'Michelle (US)'),
    'en-US:Steffan':     ('en-US-SteffanNeural',      'Steffan (US)'),
    'en-US:Christopher': ('en-US-ChristopherNeural', 'Christopher (US)'),
    'en-US:Ava':         ('en-US-AvaNeural',          'Ava (US)'),
    'en-US:Sonia':       ('en-US-SoniaNeural',        'Sonia (US)'),

    # ── English (UK) ─────────────────────────────────────────────────────────
    'en-GB:Sonia':   ('en-GB-SoniaNeural',      'Sonia (UK)'),
    'en-GB:Libby':   ('en-GB-LibbyNeural',      'Libby (UK)'),
    'en-GB:Maisie':  ('en-GB-MaisieNeural',     'Maisie (UK)'),
    'en-GB:Ryan':    ('en-GB-RyanNeural',        'Ryan (UK)'),
    'en-GB:Thomas':  ('en-GB-ThomasNeural',      'Thomas (UK)'),

    # ── English (Australia) ──────────────────────────────────────────────────
    'en-AU:Natasha': ('en-AU-NatashaNeural',    'Natasha (AU)'),
    'en-AU:William': ('en-AU-WilliamMultilingualNeural', 'William (AU)'),

    # ── English (India) ──────────────────────────────────────────────────────
    'en-IN:Neerja':  ('en-IN-NeerjaNeural',     'Neerja (IN)'),
    'en-IN:Prabhat': ('en-IN-PrabhatNeural',    'Prabhat (IN)'),

    # ── Spanish ──────────────────────────────────────────────────────────────
    'es:Elena':      ('es-ES-ElviraNeural',     'Elena (ES)'),
    'es:Alvaro':     ('es-ES-AlvaroNeural',      'Alvaro (ES)'),
    'es:Ximena':     ('es-ES-XimenaNeural',      'Ximena (CO)'),

    # ── French ───────────────────────────────────────────────────────────────
    'fr:Denise':     ('fr-FR-DeniseNeural',     'Denise (FR)'),
    'fr:Henri':      ('fr-FR-HenriNeural',       'Henri (FR)'),
    'fr:Eloise':     ('fr-FR-EloiseNeural',      'Eloise (FR)'),
    'fr:Vivienne':   ('fr-FR-VivienneMultilingualNeural', 'Vivienne (FR)'),

    # ── German ───────────────────────────────────────────────────────────────
    'de:Katja':      ('de-DE-KatjaNeural',       'Katja (DE)'),
    'de:Conrad':     ('de-DE-ConradNeural',       'Conrad (DE)'),
    'de:Killian':    ('de-DE-KillianNeural',     'Killian (DE)'),
    'de:Amala':      ('de-DE-AmalaNeural',        'Amala (DE)'),
    'de:Seraphina':  ('de-DE-SeraphinaMultilingualNeural', 'Seraphina (DE)'),

    # ── Simple-name entries (frontend voice names) ───────────────────────────
    # These match the voice= values sent by review.html / create.html
    'Roger':    ('en-US-RogerNeural',      'Roger (US)'),
    'Jenny':    ('en-US-JennyNeural',      'Jenny (US)'),
    'Aria':     ('en-US-AriaNeural',       'Aria (US)'),
    'Ana':      ('en-US-AnaNeural',        'Ana (US)'),
    'Andrew':   ('en-US-AndrewNeural',     'Andrew (US)'),
    'Emma':     ('en-US-EmmaNeural',       'Emma (US)'),
    'Brian':    ('en-US-BrianNeural',      'Brian (US)'),
    'Eric':     ('en-US-EricNeural',       'Eric (US)'),
    'Guy':      ('en-US-GuyNeural',        'Guy (US)'),
    'Michelle': ('en-US-MichelleNeural',   'Michelle (US)'),
    'Steffan':  ('en-US-SteffanNeural',    'Steffan (US)'),
    'Christopher': ('en-US-ChristopherNeural', 'Christopher (US)'),
    'Ava':      ('en-US-AvaNeural',        'Ava (US)'),
    'Sonia':    ('en-US-SoniaNeural',      'Sonia (US)'),
    # Extra frontend voices (not in standard lang: maps — Edge-tts approximations)
    'Bella':    ('en-US-JennyNeural',      'Bella (US)'),
    'Sarah':    ('en-US-AriaNeural',       'Sarah (US)'),
    'George':   ('en-US-AndrewNeural',     'George (US)'),
    'Jessica':  ('en-US-AvaNeural',        'Jessica (US)'),
    'Charlie':  ('en-US-BrianNeural',      'Charlie (US)'),
    'Laura':    ('en-US-EmmaNeural',       'Laura (US)'),
    'Liam':     ('en-US-GuyNeural',        'Liam (US)'),
    'Harry':    ('en-GB-RyanNeural',       'Harry (UK)'),
    'Will':     ('en-GB-ThomasNeural',     'Will (UK)'),
    'Daniel':   ('en-GB-SoniaNeural',      'Daniel (UK)'),
    'Adam':     ('en-US-ChristopherNeural','Adam (US)'),
}


def get_edge_voice(voice_name):
    """Resolve a voice name to an edge_tts voice ID.
    Handles both simple names ('George') and lang: prefixed names ('en-US:Roger').
    """
    # Try direct match first (simple name or lang:voicename)
    if voice_name in VOICE_MAP:
        return VOICE_MAP[voice_name][0]
    # Try constructing lang:voicename for backward compat with old saved configs
    for lang in ('en-US', 'en-GB', 'en-AU', 'en-IN'):
        for suffix in ('', ':'):
            key = f'{lang}:{voice_name}'
            if key in VOICE_MAP:
                return VOICE_MAP[key][0]
    return 'en-US-RogerNeural'  # ultimate fallback


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
        err_out = (r.stdout + r.stderr)[-500:]
        log(f'RUN ERR: {err_out}')
    return r

MUSIC_MAP = {
    'ambient_piano': '/opt/video_pipeline_v3/music/ambient_piano.mp3',
    'corporate_cinematic': '/opt/video_pipeline_v3/music/corporate_cinematic.mp3',
    'downtempo_nu_jazz': '/opt/video_pipeline_v3/music/downtempo_nu_jazz.mp3',
    'electronic_techno': '/opt/video_pipeline_v3/music/electronic_techno.mp3',
    'lofi_hip_hop': '/opt/video_pipeline_v3/music/lofi_hip_hop.mp3',
    'modern_jazz_lounge': '/opt/video_pipeline_v3/music/modern_jazz_lounge.mp3',
}

def _mix_music(video_in, video_out, work, music_key='ambient_piano'):
    """Mix a music clip looped to match video duration, with fade-out at the end."""
    music_src = MUSIC_MAP.get(music_key, MUSIC_MAP['ambient_piano'])
    mix_cmd = [
        'ffmpeg', '-y', '-i', video_in, '-i', music_src,
        '-filter_complex',
        '[1:a]aloop=1,atrim=0:6,afade=t=out:st=5:d=1[music];'
        '[0:a]volume=1.5[voice];[voice][music]amix=inputs=2:duration=longest[aout]',
        '-map', '0:v', '-map', '[aout]',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        video_out
    ]
    r = run(mix_cmd, timeout=120)
    if r.returncode == 0:
        log(f'Music mix OK: {video_out}')
        return video_out
    log(f'Music mix failed: {r.stderr[-200:]}, serving without music')
    return video_in

def render_page(cfg, listing_dir=None, job_id=None):
    ld = listing_dir if listing_dir else LISTING_DIR_BASE
    img_files = sorted([f for f in os.listdir(ld) if f.lower().endswith(('.jpg','.jpeg'))])
    sel = cfg.get('selectedIndices', list(range(min(30, len(img_files)))))
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
            "<div class='mini-card'><img src='/listing_src/" + (job_id or '') + "/" + p['fname'] + "' alt='S" + str(p['i'])
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
    saved_motion = cfg.get('motion', 'none')
    motion_labels = {
        'none': 'No Motion', 'zoom_in': 'Zoom In', 'zoom_out': 'Zoom Out',
        'pan_left': 'Pan Left', 'pan_right': 'Pan Right', 'cinematic': 'Cinematic'
    }
    motion_opts = '\n'.join(
        f'<option value="{m}"{" selected" if m == saved_motion else ""}>{motion_labels.get(m, m)}</option>'
        for m in ['none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'cinematic']
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
    if not color_val.startswith('#'):
        color_val = '#' + color_val
    font_color_val = cap.get('fontColor', '#FFFFFF')
    if not font_color_val.startswith('#'):
        font_color_val = '#' + font_color_val
    sel_json = json.dumps(sel)
    files_json = json.dumps(img_files)

    img_cards_html = ''
    for c in cards:
        img_cards_html += (
            "<div class='img-card" + (" selected" if c["is_selected"] else "") + "' data-index='" + str(c["index"])
            + "' onclick=\"toggle(" + str(c["index"]) + ")\" draggable='true'"
            " ondragstart='dragStart(event)' ondragover='dragOver(event)' ondrop='drop(event)' ondragend='dragEnd(event)'>"
            "<img src='/listing_src/" + (job_id or '') + "/" + c["fname"] + "' alt='Img" + str(c["index"]+1)
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
<script>
</script>
<div class="container">
    <div style="position:fixed;top:8px;right:12px;background:#f59e0b;color:#000;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;z-index:9999;">v1.12</div>
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
        <div class="section-title">Image Pool &mdash; """ + str(len(img_files)) + """ images &middot; Click to select (max 30)</div>
        <div class="sel-hint"><span id="sel-count">""" + str(sel_len) + """</span> selected &middot; First 30 in order used for video</div>
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
        <div class="section-title">Narration Script
            <button id="gen-script-btn" onclick="generateScript()" style="float:right;font-size:0.85rem;padding:4px 12px;background:#3b82f6;color:white;border:none;border-radius:6px;cursor:pointer;">✨ Generate Script</button>
        </div>
        <textarea id="script">""" + script_html + """</textarea>
        <div class="char-count"><span id="char-count">""" + str(len(script_html)) + """</span> chars <span id="script-status" style="margin-left:12px;color:#22c55e;display:none;">✅ Generated</span></div>
    </div>

    <div class="section">
        <div class="section-title">Caption Style</div>
        <div class="sgrid">
            <div class="field"><label>Font Size (px)</label>
                <input type="number" id="fontSize" value=""" + str(font_size) + """ min="24" max="80" /></div>
            <div class="field"><label>Highlight Color</label>
                <input type="color" id="highlightColor" value=""" + color_val + """ /></div>
            <div class="field"><label>Font Color</label>
                <input type="color" id="fontColor" value=""" + font_color_val + """ /></div>
            <div class="field"><label>Glow Intensity</label>
                <select id="glowIntensity">""" + glow_opts + """</select></div>
        </div>
        <div id="caption-preview">
            <span class="word-being" id="prev-word-being">Pool</span><span class="done-word" id="prev-done-word">views</span><span class="done-word" id="prev-done-word2">and</span><span class="done-word" id="prev-done-word3">sunset</span>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Voice</div>
        <select id="voice">""" + voice_opts + """</select>
    </div>

    <div class="section">
        <div class="section-title">Slide Motion</div>
        <select id="motion">""" + motion_opts + """</select>
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
        <button class="btn btn-secondary" id="save-btn" onclick="saveConfig()" style="background:#6366f1;margin-right:12px;">💾 Save</button>
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
        return "<div class='mini-card'><img src='/listing_src/" + (jobId || '') + "/" + imgFiles[si] + "' /><span class='mini-num'>" + (di+1) + "</span></div>";
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
function updatePreview() {
    var fs = parseInt((document.getElementById('fontSize') || {value:55}).value) || 55;
    var hc = ((document.getElementById('highlightColor') || {value:'#FF69B4'}).value.startsWith('#') ? '' : '#') + (document.getElementById('highlightColor') || {value:'#FF69B4'}).value;
    var fc = ((document.getElementById('fontColor') || {value:'#FFFFFF'}).value.startsWith('#') ? '' : '#') + (document.getElementById('fontColor') || {value:'#FFFFFF'}).value;
    var preview = document.getElementById('caption-preview');
    if (!preview) return;
    // Scale preview font down: actual video ~55px, preview is ~22px so scale = 22/55
    var scale = 22 / 55;
    var previewFs = Math.round(fs * scale);
    preview.style.fontSize = previewFs + 'px';
    // Scale glow proportionally
    var wordBeing = document.getElementById('prev-word-being');
    var doneWords = [document.getElementById('prev-done-word'), document.getElementById('prev-done-word2'), document.getElementById('prev-done-word3')];
    if (wordBeing) {
        var scaledFs = fs;
        wordBeing.style.color = hc;
        wordBeing.style.textShadow = ''.concat(
            '-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000, ',
            Math.round(2 * scale) + 'px ' + Math.round(2 * scale) + 'px ' + Math.round(4 * scale) + 'px rgba(0,0,0,0.9), ',
            '0 0 ' + Math.round(10 * scale) + 'px ' + hc + ', ',
            '0 0 ' + Math.round(20 * scale) + 'px ' + hc + '40'
        );
    }
    doneWords.forEach(function(el) {
        if (el) el.style.color = fc;
    });
}
// Call updatePreview when settings change
window.addEventListener('DOMContentLoaded', function() {
    var fsEl = document.getElementById('fontSize');
    var hcEl = document.getElementById('highlightColor');
    var fcEl = document.getElementById('fontColor');
    if (fsEl) fsEl.addEventListener('input', updatePreview);
    if (hcEl) hcEl.addEventListener('input', updatePreview);
    if (fcEl) fcEl.addEventListener('input', updatePreview);
    updatePreview();
});

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

function saveConfig() {
    var btn = document.getElementById('save-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    var payload = {
        jobId: jobId,
        script: (document.getElementById('script') || {value:''}).value,
        voice: (document.getElementById('voice') || {value:'Bella'}).value,
        motion: (document.getElementById('motion') || {value:'none'}).value,
        startCaption: (document.getElementById('startCaption') || {value:''}).value,
        endCaption: (document.getElementById('endCaption') || {value:''}).value,
        ratio: (document.getElementById('ratio') || {value:'16:9'}).value,
        duration: parseInt((document.getElementById('duration') || {value:'60'}).value) || 60,
        fontSize: parseInt((document.getElementById('fontSize') || {value:'55'}).value) || 55,
        highlightColor: (document.getElementById('highlightColor') || {value:'#FF69B4'}).value,
        fontColor: (document.getElementById('fontColor') || {value:'#FFFFFF'}).value,
        beds: (document.getElementById('beds') || {value:''}).value,
        baths: (document.getElementById('baths') || {value:''}).value,
        sqft: (document.getElementById('sqft') || {value:''}).value,
        price: (document.getElementById('price') || {value:''}).value,
        logoSize: parseInt((document.getElementById('logoSize') || {value:'15'}).value) || 15,
        logoPosition: (document.getElementById('logoPosition') || {value:'bottom-right'}).value,
        logoBase64: ''
    };
    var logoFileInput = document.getElementById('logo');
    var logoFile = logoFileInput ? logoFileInput.files[0] : null;
    if (logoFile) {
        var reader = new FileReader();
        reader.onload = function(e) { payload.logoBase64 = e.target.result; doSave(payload); };
        reader.readAsDataURL(logoFile);
    } else {
        doSave(payload);
    }
}
function doSave(payload) {
    fetch('/api/save/' + payload.jobId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(function(r) { return r.json(); })
      .then(function(d) {
          var btn = document.getElementById('save-btn');
          btn.disabled = false;
          btn.textContent = d.success ? '✅ Saved!' : '❌ Error';
          setTimeout(function() { btn.textContent = '💾 Save'; }, 2000);
      });
}
function generateScript() {
    var btn = document.getElementById('gen-script-btn');
    var status = document.getElementById('script-status');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = 'Generating...';
    if (status) { status.style.display = 'none'; }
    var jobId = location.pathname.split('/review/')[1] || '';
    var initialScript = document.getElementById('script').value;
    fetch('/api/script/generate/' + jobId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'include',
        body: JSON.stringify({})
    }).then(function(res) { return res.json(); }).then(function(r) {
        if (!r.success) {
            btn.disabled = false;
            btn.textContent = '✨ Generate Script';
            alert('Script generation failed: ' + (r.error || 'unknown error'));
            return;
        }
        // Poll until the script on disk changes (async gen finished)
        var tries = 0;
        var pollInterval = setInterval(function() {
            tries++;
            fetch('/api/config/' + jobId, {credentials: 'include'}).then(function(res) { return res.json(); }).then(function(cfg) {
                if (cfg.script && cfg.script !== initialScript) {
                    clearInterval(pollInterval);
                    document.getElementById('script').value = cfg.script;
                    var cc = document.getElementById('char-count');
                    if (cc) cc.textContent = cfg.script.length + ' chars';
                    if (status) { status.style.display = 'inline'; }
                    btn.disabled = false;
                    btn.textContent = '✨ Generate Script';
                } else if (tries > 20) {
                    clearInterval(pollInterval);
                    btn.disabled = false;
                    btn.textContent = '✨ Generate Script';
                }
            }).catch(function() {
                if (tries > 20) { clearInterval(pollInterval); btn.disabled = false; btn.textContent = '✨ Generate Script'; }
            });
        }, 2000);
    }).catch(function(e) {
        btn.disabled = false;
        btn.textContent = '✨ Generate Script';
        alert('Script generation failed: ' + e);
    });
}
function generate() {
    var btn = document.getElementById('gen-btn');
    var status = document.getElementById('status');
    if (sel.size === 0) { status.className = 'error'; status.textContent = 'Select at least 1 image.'; return; }
    btn.disabled = true;
    status.className = 'running';
    status.textContent = 'Building video (~45s)...';

    // Handle logo file upload
    var logoBase64 = '';
    var logoFileInput = document.getElementById('logo');
    var logoFile = logoFileInput ? logoFileInput.files[0] : null;
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
                highlightColor: ((document.getElementById('highlightColor') || {value:'#FFFF00'}).value.startsWith('#') ? '' : '#') + (document.getElementById('highlightColor') || {value:'#FFFF00'}).value,
                glowIntensity: (document.getElementById('glowIntensity') || {value:'explosive'}).value
            },
            voice: (document.getElementById('voice') || {value:'Bella'}).value,
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
                    fetch('/api/status/' + jobId, {credentials: 'include'}).then(function(res) { return res.json(); }).then(function(s) {
                        status.textContent = s.status || 'Building...';
                        if (s.done) {
                            clearInterval(pollInterval);
                            btn.disabled = false;
                            status.className = 'done';
                            status.textContent = '✅ Video ready!';
                            // Render all generated videos, newest first
                            var videos = s.videos || (s.video ? [s.video] : []);
                            var container = document.querySelector('.container');
                            var dlDiv = document.getElementById('dl-section');
                            if (!dlDiv) {
                                dlDiv = document.createElement('div');
                                dlDiv.id = 'dl-section';
                                dlDiv.className = 'section';
                                container.appendChild(dlDiv);
                            }
                            dlDiv.innerHTML = '<div class="section-title">Your Videos (' + videos.length + ')</div>';
                            videos.forEach(function(vidFile, idx) {
                                var isFirst = (idx === 0);
                                var wrapper = document.createElement('div');
                                wrapper.style.marginBottom = '24px';
                                var label = isFirst ? 'Latest' : 'Version ' + (videos.length - idx);
                                var dlLink = document.createElement('a');
                                dlLink.href = '/videos/' + jobId + '/' + vidFile;
                                dlLink.download = vidFile;
                                dlLink.style.display = 'inline-block';
                                dlLink.style.background = isFirst ? '#22c55e' : '#6366f1';
                                dlLink.style.color = 'white';
                                dlLink.style.padding = '10px 20px';
                                dlLink.style.borderRadius = '8px';
                                dlLink.style.textDecoration = 'none';
                                dlLink.style.fontWeight = '600';
                                dlLink.style.fontSize = '0.95rem';
                                dlLink.style.marginBottom = '10px';
                                dlLink.style.marginRight = '8px';
                                dlLink.innerHTML = '⬇ ' + label;
                                var videoEl = document.createElement('video');
                                videoEl.controls = true;
                                videoEl.style.width = '100%';
                                videoEl.style.maxWidth = '640px';
                                videoEl.style.borderRadius = '8px';
                                videoEl.style.boxShadow = '0 4px 20px rgba(0,0,0,0.4)';
                                if (isFirst) videoEl.setAttribute('autoplay', '');
                                var src = document.createElement('source');
                                src.src = '/videos/' + jobId + '/' + vidFile;
                                src.type = 'video/mp4';
                                videoEl.appendChild(src);
                                wrapper.appendChild(dlLink);
                                wrapper.appendChild(document.createElement('br'));
                                wrapper.appendChild(videoEl);
                                dlDiv.appendChild(wrapper);
                            });
                            if (videos.length === 0) {
                                dlDiv.innerHTML = '<div class="section-title">Your Video</div><p style="color:#94a3b8">No videos generated yet.</p>';
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

    result = {'address': '', 'price': '', 'beds': '', 'baths': '', 'sqft': '', 'description': '', 'images': [], 'success': False}
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

            # Description — look for the remarks/description section
            for desc_sel in ['.te-heading-property-details-remarks', '.property-remarks', '[class*="description"]', '.remarks']:
                desc_el = soup.select_one(desc_sel)
                if desc_el:
                    result['description'] = desc_el.get_text(strip=True)
                    break
            if not result['description']:
                # Fallback: first long paragraph
                for p in soup.find_all('p'):
                    t = p.get_text(strip=True)
                    if len(t) > 100:
                        result['description'] = t
                        break

            # Extract listing ID from URL to filter correct images (page JSON-LD may contain wrong listing)
            url_listing_id = None
            mls_m = _re.search(r'A119\d+', url)
            if mls_m:
                url_listing_id = mls_m.group(0)

            images = []
            for el in soup.find_all(style=True):
                style = el.get('style', '')
                if 'background-image' in style and 'url(' in style:
                    m = _re.search(r'url\("?([^)]+)"?\)', style)
                    if m:
                        src = m.group(1)
                        if url_listing_id and url_listing_id not in src:
                            continue  # skip images from other listings
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
            # Description: og:description meta, or first long paragraph
            result['description'] = (
                text('meta[property="og:description"]') or
                text('[data-testid="description"], .description, .listing-description') or
                ''
            )
            if not result['description'] or len(result['description']) < 50:
                for p in soup.find_all('p'):
                    t = p.get_text(strip=True)
                    if len(t) > 80:
                        result['description'] = t
                        break
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
        origin = self.headers.get("Origin", ""); allowed = ["https://vybord.com","https://app.vybord.com"]; self.send_header("Access-Control-Allow-Origin", origin if origin in allowed else "https://vybord.com")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


    def authenticate(self):
        """Validate the vyb_token cookie. Returns (user_id, email) or (None, None)."""
        cookie_header = self.headers.get('Cookie', '')
        print(f"[DEBUG authenticate] Cookie: {repr(cookie_header[:80])}", flush=True)
        for part in cookie_header.split(';'):
            key, _, val = part.strip().partition('=')
            if key == COOKIE_NAME and val:
                try:
                    payload = decode_token(val)
                    return int(payload.get('sub')), payload.get('email')
                except Exception as e:
                    print(f"[DEBUG authenticate] Token decode failed: {e}, token[:30]={val[:30]}", flush=True)
                    return None, None
        return None, None


    def require_auth(self):
        """Send a 401 response if the request is not authenticated."""
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(json.dumps({'error': 'Unauthorized', 'login_url': '/login.html'}).encode())

    def check_rate_limit(self, endpoint_key, user_id=None):
        """Check rate limit for the given endpoint key.
        Returns True if allowed, False if limited.
        When limited, sends a 429 response automatically.
        """
        allowed, retry_after = _rate_limiter.check(endpoint_key, user_id=user_id)
        if not allowed:
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', str(retry_after))
            origin = self.headers.get('Origin', ''); allowed_list = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed_list else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Rate limit exceeded',
                'retry_after': retry_after,
                'login_url': '/login.html'
            }).encode())
            return False
        return True


    def do_HEAD(self):
        # Delegate to do_GET logic for headers only
        p = urlparse(self.path).path
        self.send_response(200)
        if p.startswith('/listing_src/'):
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'max-age=3600')
        elif p in ('/app.css', '/style.css'):
            self.send_header('Content-Type', 'text/css')
        else:
            self.send_header('Content-Type', 'text/html')
        self.end_headers()
        return

    def do_OPTIONS(self):
        self.send_response(200)
        origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        return

    def do_GET(self):
        p = urlparse(self.path).path

        if p.startswith('/listing_src/'):
            # Format: /images/{job_id}/{fname} — extract job_id from path
            parts = p[13:].split('/', 1)  # strip '/listing_src/' (13 chars) then split job_id/filename
            job_id_from_path = parts[0] if len(parts) > 1 else None
            fname = parts[1] if len(parts) > 1 else parts[0]
            job_id = job_id_from_path or CURRENT_JOB_ID[0]
            if job_id:
                work_path = Path(f"/opt/video_pipeline_v3/work/{job_id}/listing_src/{fname}")
                if work_path.exists():
                    fpath = str(work_path)
                else:
                    fpath = str(Path(f"/tmp/rs_uploads/{job_id}/listing_src/{fname}"))
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

        if p == '/review.html' or p.startswith('/review.html?'):
            # Serve the dark static review.html (client-side API calls load job data)
            fpath = '/opt/video_pipeline_v3/review.html'
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                with open(fpath, 'rb') as fh:
                    self.wfile.write(fh.read())
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Not found')
            return

        if p in ('/model_video.html', '/modelvideo', '/model-video'):
            fpath = '/opt/video_pipeline_v3/model_video.html'
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Not found')
            return

        if p == '/test.html':
            fpath = '/opt/video_pipeline_v3/test.html'
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        if p == '/profile.html':
            fpath = '/opt/video_pipeline_v3/profile.html'
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                with open(fpath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        # v3.7 review page images: /images/<jobId>/image_NNN.jpg
        if p.startswith('/images/') and len(p) > 8:
            parts = p[8:].split('/', 1)
            if len(parts) < 2:
                self.send_response(404)
                self.end_headers()
                return
            job_id_img = parts[0]
            fname = parts[1]
            fpath_candidates = [
                Path(f"/opt/video_pipeline_v3/work/{job_id_img}/images/{fname}"),
                Path(f"/opt/video_pipeline_v3/work/{job_id_img}/listing_src/{fname}"),
                Path(f"/tmp/rs_uploads/{job_id_img}/images/{fname}"),
                Path(f"/tmp/rs_uploads/{job_id_img}/listing_src/{fname}"),
            ]
            fpath = None
            for candidate in fpath_candidates:
                if candidate.exists():
                    fpath = str(candidate)
                    break
            if fpath:
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

        # Config endpoint (for polling after script generation)
        if p.startswith('/api/config/'):
            job_id = p.replace('/api/config/', '').split('/')[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing job_id'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            if not cfg_file.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found'}).encode())
                return
            with open(cfg_file) as f:
                cfg = json.load(f)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', '')
            allowed = ['https://vybord.com', 'https://app.vybord.com']
            self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps(cfg).encode())
            return

        # Status check endpoint
        if p.startswith('/api/status/'):
            raw_id = p.split('/api/status/')[1].split('/')[0]
            # Normalize: add review_ prefix if missing — but not for mv_ job IDs
            job_id = raw_id if raw_id.startswith('review_') or raw_id.startswith('mv_') else 'review_' + raw_id
            work = Path(f"/tmp/rs_uploads/{job_id}")
            status_file = work / 'status.json'
            cfg_file = work / 'pipeline_config.json'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            # Merge status.json + pipeline_config.json so v3.7 JS gets full config
            result = {'status': 'Starting...', 'done': False, 'job_id': job_id}
            if status_file.exists():
                try: result.update(json.loads(status_file.read_text()))
                except: pass
            if cfg_file.exists():
                try: result.update(json.loads(cfg_file.read_text()))
                except: pass
            # Include image filenames from listing_src for the review page
            img_dir = work / 'listing_src'
            if img_dir.exists():
                img_files = sorted([f.name for f in img_dir.iterdir() if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')])
                result['images'] = img_files
            else:
                result['images'] = []
            self.wfile.write(json.dumps(result).encode())
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
            vid_job_id = vid_job_id if vid_job_id.startswith('review_') or vid_job_id.startswith('mv_') else 'review_' + vid_job_id
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

        if p.startswith('/review/'):
            # Redirect /review/JOBID to dark static page (job data loads client-side)
            job = p.split('/review/')[1].split('?')[0].split('#')[0]
            self.send_response(302)
            self.send_header('Location', f'/review.html?job={job}')
            self.end_headers()
            return

        if p in ('/', '/review', '/index.html'):
            # Redirect root to main page
            self.send_response(302)
            self.send_header('Location', '/test.html')
            self.end_headers()
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

            # Verify images exist before building
            listing_dir = Path(f"/tmp/rs_uploads/{job_id}/listing_src")
            if not listing_dir.exists() or not list(listing_dir.iterdir()):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'No images found. Please fetch listing images before generating video.'}).encode())
                return

            # Trigger build
            try:
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "job_id": job_id, "exit": result.returncode}).encode())
            except Exception as e:
                log(f"Build error {job_id}: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return


        # Videos endpoint — GET returns JSON list, POST not allowed
        if p.startswith('/api/videos/'):
            job_id = p.split('/api/videos/')[1].rstrip('/')
            if not job_id.startswith('review_'):
                job_id = 'review_' + job_id
            work = Path(f"/tmp/rs_uploads/{job_id}")
            videos_json = work / 'videos.json'
            if videos_json.exists():
                with open(videos_json) as f:
                    vid_data = json.load(f)
            else:
                # Priority: timestamped/piano videos first, then intermediate outputs
                timestamped = []
                for fname in sorted(work.glob('video_piano_*.mp4'), key=lambda f: f.stat().st_mtime, reverse=True):
                    if fname.stat().st_size > 1000:
                        timestamped.append({'name': fname.name, 'size': fname.stat().st_size, 'mtime': fname.stat().st_mtime})
                for fname in sorted(work.glob('video_[0-9][0-9][0-9][0-9][0-9][0-9].mp4'), key=lambda f: f.stat().st_mtime, reverse=True):
                    if fname.stat().st_size > 1000:
                        timestamped.append({'name': fname.name, 'size': fname.stat().st_size, 'mtime': fname.stat().st_mtime})
                # Fallback: if no timestamped/piano videos, show best available intermediate
                if not timestamped:
                    for fname in ['video_wna.mp4', 'video_captioned.mp4', 'video_noaudio.mp4']:
                        fpath = work / fname
                        if fpath.exists() and fpath.stat().st_size > 1000:
                            timestamped.append({'name': fname, 'size': fpath.stat().st_size, 'mtime': fpath.stat().st_mtime})
                vid_data = {'videos': [e['name'] for e in timestamped[:3]]}
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.send_header('Content-Type', 'application/json')
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(vid_data).encode())
            return

        # Video list endpoint — GET returns JSON list of up to 3 recent videos
        if p.startswith('/api/video-list/'):
            job_id = p.split('/api/video-list/')[1].rstrip('/')
            if not job_id.startswith('review_'):
                job_id = 'review_' + job_id
            work = Path(f"/tmp/rs_uploads/{job_id}")
            videos_json = work / 'videos.json'
            if videos_json.exists():
                with open(videos_json) as f:
                    vid_data = json.load(f)
            else:
                # Priority: timestamped/piano videos first, then intermediate outputs
                timestamped = []
                for fname in sorted(work.glob('video_piano_*.mp4'), key=lambda f: f.stat().st_mtime, reverse=True):
                    if fname.stat().st_size > 1000:
                        timestamped.append({'name': fname.name, 'size': fname.stat().st_size, 'mtime': fname.stat().st_mtime})
                for fname in sorted(work.glob('video_[0-9][0-9][0-9][0-9][0-9][0-9].mp4'), key=lambda f: f.stat().st_mtime, reverse=True):
                    if fname.stat().st_size > 1000:
                        timestamped.append({'name': fname.name, 'size': fname.stat().st_size, 'mtime': fname.stat().st_mtime})
                # Fallback: if no timestamped/piano videos, show best available intermediate
                if not timestamped:
                    for fname in ['video_wna.mp4', 'video_captioned.mp4', 'video_noaudio.mp4']:
                        fpath = work / fname
                        if fpath.exists() and fpath.stat().st_size > 1000:
                            timestamped.append({'name': fname, 'size': fpath.stat().st_size, 'mtime': fpath.stat().st_mtime})
                vid_data = {'videos': [e['name'] for e in timestamped[:3]]}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.end_headers()
            self.wfile.write(json.dumps(vid_data).encode())
            return

        # GET /api/profile/videos — return all video jobs for the logged-in user
        if p == '/api/profile/videos':
            user_id, email = self.authenticate()
            if not user_id:
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'unauthorized'}).encode())
                return
            try:
                conn = sqlite3.connect(str(USER_DB), timeout=5)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT v.job_id, v.status, v.created_at, v.completed_at
                      FROM videos v
                     WHERE v.user_id = ?
                     ORDER BY v.created_at DESC
                     LIMIT 50
                """, (user_id,)).fetchall()
                conn.close()
                records = []
                for r in rows:
                    job_id = r['job_id']
                    work = Path(f"/tmp/rs_uploads/{job_id}")
                    video_files = []
                    if work.exists():
                        for f in sorted(work.glob('video_piano_*.mp4'), key=lambda x: x.stat().st_mtime, reverse=True):
                            if f.stat().st_size > 1000:
                                video_files.append(f.name)
                        if not video_files:
                            for fallback in ['video_captioned.mp4', 'video_wna2.mp4', 'video_noaudio.mp4']:
                                fp = work / fallback
                                if fp.exists() and fp.stat().st_size > 1000:
                                    video_files.append(fp.name)
                                    break
                    records.append({
                        'job_id': job_id,
                        'status': r['status'],
                        'created_at': r['created_at'],
                        'completed_at': r['completed_at'],
                        'videos': video_files,
                        'address': (work / 'pipeline_config.json').exists() and
                                   json.load(open(work / 'pipeline_config.json')).get('address', '') or '',
                    })
                payload_out = {'videos': records}
            except Exception as e:
                payload_out = {'videos': [], 'error': str(e)}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.end_headers()
            self.wfile.write(json.dumps(payload_out).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        """Handle DELETE /api/profile/videos/<job_id> — delete a video job."""
        p = urlparse(self.path).path
        if p.startswith('/api/profile/videos/'):
            job_id = p.split('/api/profile/videos/')[1].strip()
            if not job_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header('Access-Control-Allow-Credentials', 'true')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'job_id required'}).encode())
                return
            user_id, email = self.authenticate()
            if not user_id:
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header('Access-Control-Allow-Credentials', 'true')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'unauthorized'}).encode())
                return
            try:
                # Verify ownership
                conn = sqlite3.connect(str(USER_DB), timeout=5)
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (job_id,)).fetchone()
                if not row:
                    conn.close()
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json')
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header('Access-Control-Allow-Credentials', 'true')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'job not found'}).encode())
                    return
                if row['user_id'] != user_id:
                    conn.close()
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/json')
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header('Access-Control-Allow-Credentials', 'true')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'forbidden'}).encode())
                    return
                # Delete job directory
                job_dir = Path(f"/tmp/rs_uploads/{job_id}")
                if job_dir.exists():
                    shutil.rmtree(job_dir)
                # Delete DB record
                conn.execute("DELETE FROM videos WHERE job_id = ?", (job_id,))
                conn.commit()
                conn.close()
                print(f'[DELETE] Deleted job {job_id} for user {user_id}', flush=True)
            except Exception as e:
                print(f'[DELETE] Error deleting job {job_id}: {e}', flush=True)
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header('Access-Control-Allow-Credentials', 'true')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path

        if p == '/api/fetch-html':
            # Handle CORS preflight
            if self.command == 'OPTIONS':
                self.send_response(200)
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
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
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
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
                    # Strip inline styles, noscripts, and nonce attrs to reduce size
                    # Keep <script type=application/ld+json> for listing metadata
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    for tag in soup(['style', 'noscript']):
                        tag.decompose()
                    # Remove regular script tags but preserve JSON-LD
                    for tag in soup.find_all('script'):
                        if tag.get('type', '').lower() not in ('', 'application/ld+json', 'application/json'):
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
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                self.send_response(502)
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        # --- ModelVideo: URL → viral video package ---#(same pipeline as run_pipeline.py but runs inline via subprocess)
        if p == '/api/model-video':
            # Auth required: prevent anonymous GPU compute abuse
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/model-video', user_id=user_id):
                return
            print(f'[model-video] REQUEST START pid={os.getpid()} path={p}', flush=True)
            origin = self.headers.get('Origin', '')
            allowed = ['https://vybord.com', 'https://app.vybord.com']
            if self.command == 'OPTIONS':
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode()
            try:
                payload = json.loads(body)
            except:
                payload = {}
            model_url = payload.get('url', '')
            if not model_url:
                self.send_response(400)
                self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'url required'}).encode())
                return


            # Run pipeline in background, return job_id immediately
            job_id = f"mv_{uuid.uuid4().hex[:12]}"
            work = Path(f"/tmp/rs_uploads/{job_id}")
            work.mkdir(parents=True, exist_ok=True)

            # Write the URL to a signal file so the worker knows what to fetch
            (work / "model_url.txt").write_text(model_url)

            # Enqueue — worker checks for model_url.txt and runs the full pipeline
            import time as _time
            _t0 = _time.time()
            init_dispatcher()
            _t1 = _time.time()
            position = enqueue(job_id, user_id=0)
            _t2 = _time.time()
            log(f'[model-video] init_dispatcher={(_t1-_t0)*1000:.0f}ms enqueue={(_t2-_t1)*1000:.0f}ms')

            # Write initial status so /api/status/<job_id> returns something useful
            status_path = work / "status.json"
            _t3 = _time.time()
            status_path.write_text(json.dumps({
                "status": f"Queued ModelVideo at position {position}...",
                "done": False, "video": "", "job_id": job_id, "progress": 0
            }))
            _t4 = _time.time()
            log(f'[model-video] write_status={(_t4-_t3)*1000:.0f}ms')

            self.send_response(202)
            self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            resp = json.dumps({
                'success': True,
                'job_id': job_id,
                'status': 'queued',
                'position': position,
                'message': 'ModelVideo pipeline started',
            }).encode()
            _t5 = _time.time()
            self.wfile.write(resp)
            self.wfile.flush()
            _t6 = _time.time()
            log(f'[model-video] send_response={(_t6-_t5)*1000:.0f}ms total={(_t6-_t0)*1000:.0f}ms')
            return


        # --- Shared helpers available to all handlers inside do_POST ---
        _GLOBAL_BUILD_LOCK = Path('/tmp/rs_uploads/.global_build.lock')

        def is_lock_stale(lock_path):
            """Check if .build.lock exists but its PID is dead. If stale, remove it and return True."""
            if not lock_path.exists():
                return True
            try:
                pid = int(lock_path.read_text().strip())
                os.kill(pid, 0)
                return False  # PID is alive, lock is valid
            except (ValueError, ProcessLookupError, OSError):
                try:
                    os.unlink(lock_path)
                except:
                    pass
                return True  # Stale, removed

        def acquire_global_lock(wait_secs=120, poll_interval=2):
            """Wait up to wait_secs for global lock to be released, then acquire it.
            Returns True if acquired, False if timed out."""
            import time
            start = time.time()
            while time.time() - start < wait_secs:
                if _GLOBAL_BUILD_LOCK.exists():
                    try:
                        pid = int(_GLOBAL_BUILD_LOCK.read_text().strip())
                        os.kill(pid, 0)
                        # Lock is held by alive process — wait for it
                        time.sleep(poll_interval)
                        continue
                    except (ValueError, ProcessLookupError, OSError):
                        try: os.unlink(_GLOBAL_BUILD_LOCK)
                        except: pass
                # Lock is free — try to acquire
                try:
                    _GLOBAL_BUILD_LOCK.write_text(str(os.getpid()))
                    log(f'Acquired global build lock for PID {os.getpid()}')
                    return True
                except:
                    time.sleep(poll_interval)
                    continue
            return False  # Timed out

        def release_global_lock(job_id=None):
            try:
                if _GLOBAL_BUILD_LOCK.exists() and int(_GLOBAL_BUILD_LOCK.read_text().strip()) == os.getpid():
                    os.unlink(_GLOBAL_BUILD_LOCK)
                    log(f'Released global build lock')
            except:
                pass
            # If a job_id is given, check the pending queue after releasing lock
            if job_id:
                _trigger_next_pending()

        if p == '/api/generate':
            # Handle CORS preflight
            if self.command == 'OPTIONS':
                self.send_response(200)
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                return
            # Auth required: verify session and ownership of the job
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/generate', user_id=user_id):
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode()
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {}
            # Verify ownership of source job if referenced (prevents stealing other users' images)
            source_job_id = payload.get('sourceJobId', '')
            if source_job_id:
                src_id = source_job_id if source_job_id.startswith('review_') else 'review_' + source_job_id
                conn = sqlite3.connect(str(USER_DB), timeout=5)
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (src_id,)).fetchone()
                conn.close()
                if not row or row['user_id'] != user_id:
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/json')
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Forbidden: you do not own this job'}).encode())
                    return
            # ALWAYS load from saved config when sourceJobId is provided
            # This ensures saved settings are used as the base, form values override on top
            source_job_id = payload.get('sourceJobId', '')
            if source_job_id:
                src_id = source_job_id if source_job_id.startswith('review_') else 'review_' + source_job_id
                src_work = Path(f"/tmp/rs_uploads/{src_id}")
                src_cfg_file = src_work / 'pipeline_config.json'
                saved_cfg = {}
                if src_cfg_file.exists():
                    with open(src_cfg_file) as f:
                        saved_cfg = json.load(f)
                # Apply form values as overrides on top of saved config
                # Use dict() to create a SHALLOW COPY so we don't mutate the source cfg
                saved_cfg = dict(saved_cfg) if saved_cfg else {}
                for key in ("script", "voice", "motion", "startCaption", "endCaption",
                            'ratio', 'duration', 'fontSize', 'highlightColor', 'fontColor', 'beds', 'baths',
                            'sqft', 'price', 'logoSize', 'logoPosition', 'startDuration', 'endDuration',
                            'music',
                            'selectedIndices', 'logoBase64', 'address', 'logo'):
                    if key in payload and payload.get(key) not in (None, ''):
                        saved_cfg[key] = payload[key]
                if 'captionStyle' in payload:
                    cs = payload['captionStyle']
                    for k in ('fontSize', 'highlightColor', 'fontColor', 'glowIntensity'):
                        if k in cs and cs[k] not in (None, ''):
                            saved_cfg[k] = cs[k]
                payload = saved_cfg  # use merged cfg as the payload going forward
            addr = payload.get('address', 'Listing')
            # If selectedIndices not provided, count from the source job's uploaded images
            # (the new job's listing_src is empty at this point — images live in source job)
            if source_job_id:
                src_id = source_job_id if source_job_id.startswith('review_') else 'review_' + source_job_id
                src_work = Path(f"/tmp/rs_uploads/{src_id}")
                src_img_dir = src_work / 'listing_src'
                actual_count = len(list(src_img_dir.iterdir())) if src_img_dir.exists() else 0
            else:
                actual_count = 0
            sel_indices = payload.get('selectedIndices', list(range(min(30, actual_count))) if actual_count > 0 else list(range(15)))
            voice = payload.get('voice', 'Roger')
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
            logo_b64 = payload.get('logo', '') or payload.get('logoBase64', '')
            logo_position = payload.get('logoPosition', 'bottom-right')
            logo_size = int(payload.get('logoSize', 15))
            start_caption = payload.get('startCaption', '')
            start_duration = float(payload.get('startDuration', 3))
            end_caption = payload.get('endCaption', '')
            end_duration = float(payload.get('endDuration', 4))
            ratio = payload.get('ratio', '9:16')

            log(f'Generate request: {addr} | {len(sel_indices)} images | voice={voice}')

            # noPipeline=true means: create job + stage images/config but do NOT start the pipeline.
            # Used by test.html which only wants to upload images to review page.
            no_pipeline = payload.get('noPipeline', False)

            # Always create a fresh job_id — source_job_id only controls config/images sourcing
            job_id = 'review_' + str(uuid.uuid4())[:8]
            work = Path(f"/tmp/rs_uploads/{job_id}")
            img_dir = work / 'listing_src'
            os.makedirs(img_dir, exist_ok=True)

            # Track in user DB if logged in
            if user_id:
                _insert_video_record(user_id, job_id)

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
            if source_job_id:
                # Try both listing_src (new) and images (old) for backward compat
                src_job = source_job_id if source_job_id.startswith('review_') else 'review_' + source_job_id
                for src_path in [
                    Path(f"/tmp/rs_uploads/{src_job}/listing_src"),
                    Path(f"/tmp/rs_uploads/{src_job}/images"),
                ]:
                    if src_path.exists() and src_path != img_dir:
                        for fname in sorted(src_path.iterdir()):
                            if fname.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                                shutil.copy2(fname, img_dir / fname.name)
                        if any(img_dir.iterdir()):
                            log(f"Copied {len(list(img_dir.iterdir()))} images from {src_path.parent.name}/{src_path.name}")
                            break  # only break if we got files; empty dir → try next source
            else:
                # Download images from URLs provided directly in payload
                img_urls = payload.get('images', [])
                for i, img_url in enumerate(img_urls[:25]):
                    if not img_url or not isinstance(img_url, str):
                        continue
                    fname = f"image_{i+1:03d}.jpg"
                    try:
                        if img_url.startswith('data:'):
                            import base64
                            b64 = img_url.split(',')[1]
                            (img_dir / fname).write_bytes(base64.b64decode(b64))
                            log(f"Saved base64 image {i+1}")
                        elif img_url.startswith('http'):
                            import urllib.request
                            req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
                            with urllib.request.urlopen(req, timeout=15) as resp:
                                content_type = resp.headers.get('Content-Type', 'image/jpeg')
                                ext = 'webp' if 'webp' in content_type else 'jpg'
                                actual_fname = fname.replace('.jpg', f'.{ext}')
                                (img_dir / actual_fname).write_bytes(resp.read())
                                log(f"Downloaded image {i+1} ({ext}): {img_url[:80]}")
                    except Exception as img_err:
                        log(f"Image download error {i+1}: {img_err}")
                if any(img_dir.iterdir()):
                    log(f"Saved {len(list(img_dir.iterdir()))} images from URLs")
            edge_voice = get_edge_voice(voice)
            voice_m4a = work / 'voice.m4a'

            def write_status(status_msg, done=False, video_path='', videos=None, progress=None, **extra):
                try:
                    if videos is None:
                        vp = work / 'videos.json'
                        if vp.exists():
                            with open(vp) as vf:
                                videos = json.load(vf).get('videos', [])
                        else:
                            videos = []
                    # Load existing status to preserve listing fields across updates
                    existing = {}
                    st_path = work / 'status.json'
                    if st_path.exists():
                        try:
                            with open(st_path) as sf:
                                existing = json.load(sf)
                        except:
                            pass
                    status_data = {
                        'status': status_msg, 'done': done, 'video': video_path,
                        'videos': videos, 'job_id': job_id, 'progress': progress
                    }
                    # Preserve listing fields from previous writes
                    for k in ('address', 'price', 'beds', 'baths', 'sqft', 'images'):
                        if k in existing:
                            status_data[k] = existing[k]
                    # Apply new listing fields if provided
                    for k, v in extra.items():
                        if k in ('address', 'price', 'beds', 'baths', 'sqft', 'images') and v:
                            status_data[k] = v
                    with open(st_path, 'w') as f:
                        json.dump(status_data, f)
                except:
                    pass

            def do_build():
                nonlocal script
                caption_style = payload.get('captionStyle', {})
                """All blocking work in one async thread — returns immediately to HTTP."""
                if not acquire_global_lock():
                    log(f'Global build lock held, queuing {job_id}')
                    try:
                        write_status('Queued — build in progress on another job, will start shortly...',
                            done=False, video_path='')
                    except:
                        pass
                    _PENDING_BUILDS.append(job_id)
                    return
                lock_file = work / '.build.lock'
                if not is_lock_stale(lock_file):
                    log(f'Build already in progress for {job_id}, skipping')
                    try:
                        with open(work / 'status.json', 'w') as f:
                            json.dump({'status': 'Build already in progress, please wait...', 'done': False, 'video': '', 'job_id': job_id}, f)
                    except:
                        pass
                    release_global_lock()
                    return
                with open(lock_file, 'w') as f:
                    f.write(str(os.getpid()))
                # Clean stale output files from previous failed attempts before build_vps.py runs
                for stale in [work / 'video_final.mp4', work / 'video_captioned.mp4',
                               work / 'video_wna.mp4', work / 'video_wna2.mp4',
                               work / 'video_with_audio.mp4', work / 'video_with_intro_outro.mp4',
                               work / 'intro_card_anim.mp4', work / 'outro_card_anim.mp4',
                               work / 'video_logo.mp4']:
                    if stale.exists():
                        try:
                            os.unlink(stale)
                            log(f'Cleaned stale: {stale.name}')
                        except Exception as e:
                            log(f'Could not clean stale {stale.name}: {e}')
                try:
                    price = payload.get('price', '')
                    beds = payload.get('beds', '')
                    baths = payload.get('baths', '')
                    sqft = payload.get('sqft', '')
                    duration = int(payload.get('duration', 60) or 60)
                    # Script is passed in from the UI — no server-side generation here.
                    # (Script generation for the UI lives in /api/script/generate/{jobId})

                    # --- Voice generation (edge_tts with gTTS fallback) ---
                    write_status('Generating voice...',
                        progress=5,
                        address=addr, price=price, beds=beds, baths=baths, sqft=sqft,
                        images=len(list(img_dir.iterdir())) if img_dir.exists() else 0)
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
                                 str(voice_m4a)], timeout=30, cwd='/opt/video_pipeline_v3')
                            os.unlink(tmp_mp3)
                            log(f'gTTS voice generated: {voice_m4a.stat().st_size} bytes')
                        except Exception as e2:
                            log(f'gTTS fallback also failed: {e2}')

                    # --- Whisper transcript ---
                    log(f'Whisper: starting transcription of {voice_m4a}')
                    try:
                        wj = work / 'voice.json'
                        # Run whisper; if it fails or returns <2 segments, retry with medium model
                        r = run([VENV, '-m', 'whisper', str(voice_m4a), '--model', 'base', '--language', 'English',
                                '--word_timestamps', 'True', '--output_dir', str(work)],
                               cwd='/opt/video_pipeline_v3', timeout=300)
                        log(f'Whisper done: returncode={r.returncode} stdout_len={len(r.stdout)}')
                        log(f'Whisper: voice.json exists={wj.exists()} size={wj.stat().st_size if wj.exists() else 0}')
                        wdata = {}
                        if wj.exists():
                            with open(wj) as f:
                                wdata = json.load(f)
                            num_segs = len(wdata.get('segments', []))
                            log(f'Whisper segments: {num_segs}')
                            # Skip medium retry — medium model gets OOM-killed on this machine
                            log(f'Whisper final segments: {num_segs}')
                            srt_path = work / 'voice.srt'
                            with open(srt_path, 'w') as f:
                                word_id = 0
                                for seg in wdata.get('segments', []):
                                    words = seg.get('words', [])
                                    if words:
                                        # Word-level SRT: one entry per word with individual timestamps
                                        for w in words:
                                            word_text = w['word'].strip()
                                            if not word_text:
                                                continue
                                            word_id += 1
                                            w_start = float(w['start'])
                                            w_end = float(w['end'])
                                            f.write(f"{word_id}\n")
                                            f.write(f"{format_srt_time(w_start)} --> {format_srt_time(w_end)}\n")
                                            f.write(f"{word_text}\n\n")
                                    else:
                                        # Fallback: segment-level SRT
                                        seg_id = seg['id'] + 1
                                        start = float(seg['start'])
                                        end = float(seg['end'])
                                        text = seg['text'].strip()
                                        f.write(f"{seg_id}\n")
                                        f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                                        f.write(f"{text}\n\n")
                            pc_path = work / 'voice_transcript.json'
                            with open(pc_path, 'w') as f:
                                json.dump({'segments': [{
                                    'structure_tags': [],
                                    'max_layout': {'width': 1920, 'height': 1080, 'left': 0, 'top': 0},
                                    'time': {'start': seg['start'], 'end': seg['end']},
                                    'words': [{'word': w['word'].strip(), 'start': w['start'], 'end': w['end']} for w in seg.get('words', [])],
                                    'text': seg.get('text', '').strip()
                                } for seg in wdata.get('segments', [])]}, f)
                    except Exception as e:
                        log(f'Whisper error: {e}')

                    # --- Pipeline config ---
                    # Count actual images available (may have been copied from source job)
                    actual_imgs = len(list(img_dir.iterdir()))
                    # Only treat selectedIndices as "explicit" if the USER provided it in the
                    # request payload — not if it came from the source job's saved config
                    explicit_sel = 'selectedIndices' in payload and payload.get('selectedIndices') is not None
                    if explicit_sel:
                        # User explicitly chose indices — trust them but cap at 30
                        sel_indices = list(payload.get('selectedIndices', list(range(15))))[:30]
                    elif actual_imgs > 0:
                        # No explicit selection — use all available images (up to 30)
                        sel_indices = list(range(min(30, actual_imgs)))
                    else:
                        sel_indices = list(range(15))
                    n = min(30, len(sel_indices))
                    cfg_out = {
                        'address': addr, 'script': script, 'voice': voice,
                        'motion': payload.get('motion', 'cinematic'),
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
                        'music': payload.get('music', 'ambient_piano'),
                    }
                    with open(work / 'pipeline_config.json', 'w') as f:
                        json.dump(cfg_out, f, indent=2)
                    log(f'Pipeline config written for {job_id}')
                    write_status('Voice ready, building slides...', progress=20)

                    # --- Generate intro card ---
                    intro_mp4 = ''
                    if start_caption:
                        try:
                            intro_png = str(work / 'intro_card.png')
                            intro_anim = str(work / 'intro_card.mp4')
                            ratio_val = ratio
                            run(['python3', '/opt/video_pipeline_v3/scripts/branding.py',
                                 '--mode', 'intro',
                                 '--text', start_caption,
                                 '--subtext', addr,
                                 '--output', intro_png,
                                 '--ratio', ratio_val,
                                 '--duration', str(start_duration)],
                                timeout=30, cwd='/opt/video_pipeline_v3')
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
                            run(['python3', '/opt/video_pipeline_v3/scripts/branding.py',
                                 '--mode', 'outro',
                                 '--text', end_caption,
                                 '--subtext', '',
                                 '--output', outro_png,
                                 '--ratio', ratio_val,
                                 '--duration', str(end_duration)],
                                timeout=30, cwd='/opt/video_pipeline_v3')
                            outro_mp4 = outro_anim
                            log(f'Outro card generated: {outro_mp4}')
                        except Exception as e:
                            log(f'Outro generation error: {e}')

                    # --- Slides + captions ---
                    write_status('Building slides...', progress=25)
                    cfg = json.loads((work / 'pipeline_config.json').read_text())
                    motion_val = cfg.get('motion', 'cinematic')
                    cap = cfg.get('captionStyle', {})
                    fs = cap.get('fontSize', 55)
                    hc = '#' + cap.get('highlightColor', 'FFFF00').lstrip('#')
                    fc = cap.get('fontColor', '#FFFFFF')
                    # Stream build_vps.py stdout for real progress updates
                    n_total = max(1, len(list(img_dir.iterdir())) if img_dir.exists() else 1)
                    proc = subprocess.Popen(
                        [VENV, '/opt/video_pipeline_v3/scripts/build_vps.py',
                         '--work', str(work),
                         '--listing', str(img_dir),
                         '--duration', str(duration),
                         '--motion', motion_val,
                         '--ratio', ratio,
                         '--images_per_slide', '1'],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        cwd='/opt/video_pipeline_v3')
                    slide_pct = 0
                    for line in proc.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        # Parse slide completion: "  slide N: OK | ..."  → map to 26-34%
                        m = re.search(r'slide\s+(\d+):\s+OK', line)
                        if m:
                            slide_num = int(m.group(1))
                            slide_pct = int(10 * slide_num / max(n_total, 1))
                            write_status(f'Building slides... ({min(99,n_total)} total)', progress=min(34, 25 + slide_pct))
                    proc.wait()
                    result = type('Result', (), {'returncode': proc.returncode})()
                    log(f'Slides built: exit={result.returncode}')
                    write_status('Slides ready, assembling...', progress=35)
                    if result.returncode != 0:
                        try:
                            with open(work / 'status.json', 'w') as f:
                                json.dump({'status': f'Slides build failed (exit {result.returncode})', 'done': False, 'video': '', 'job_id': job_id}, f)
                        except:
                            pass
                        log(f'Build aborted: build_vps.py failed')
                        return

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
                    write_status('Concatenating clips...', progress=40)
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
                    write_status('Merging audio...', progress=50)
                    # Ensure audio is looped/padded to full video duration so pycaps doesn't truncate
                    wna_with_intro = str(work / 'video_wna2.mp4')
                    if video_with_intro_outro != str(work / 'video_wna.mp4'):
                        # Get target duration from video_with_intro_outro
                        dur_r = subprocess.run(
                            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                             '-of', 'csv=p=0', video_with_intro_outro],
                            capture_output=True, text=True)
                        target_dur = float(dur_r.stdout.strip() or 0)
                        # Use stream_loop to extend short audio to full video duration,
                        # then pad with silence to cover any remainder
                        mux_cmd = ['ffmpeg', '-y', '-i', video_with_intro_outro,
                                   '-stream_loop', '-1', '-i', str(work / 'video_wna.mp4'),
                                   '-map', '0:v:0', '-map', '1:a',
                                   '-c:v', 'copy',
                                   '-af', f'apad=whole_dur={target_dur}',
                                   '-t', str(target_dur), wna_with_intro]
                        r_mux = run(mux_cmd, timeout=120)
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

                    # Guard: if voice.srt is missing (whisper failed), generate empty SRT to avoid crash
                    if not voice_srt.exists():
                        log(f'WARNING: voice.srt missing — generating empty SRT')
                        with open(voice_srt, 'w') as f:
                            f.write("1\n00:00:00,000 --> 00:00:00,001\n\n")

                    # Remove stale output files — but first save current video as a history version
                    prior_final = work / 'video_final.mp4'
                    if prior_final.exists() and prior_final.stat().st_size > 1000:
                        from datetime import datetime as _dt
                        ts = _dt.now().strftime('%H%M%S')
                        ts_video = f'video_{ts}.mp4'
                        try:
                            import shutil as _shutil3
                            _shutil3.copy2(str(prior_final), work / ts_video)
                            # Maintain history list
                            vp = work / 'videos.json'
                            if vp.exists():
                                with open(vp) as vf:
                                    videos_list = [ts_video] + json.load(vf).get('videos', [])
                            else:
                                videos_list = [ts_video]
                            with open(vp, 'w') as vf:
                                json.dump({'videos': videos_list}, vf)
                            log(f'Stored prior video as {ts_video}')
                        except Exception as _e:
                            log(f'Could not store prior video: {_e}')
                    for stale in [work / 'video_captioned.mp4', work / 'video_final.mp4',
                                   work / 'video_with_audio.mp4']:
                        if stale.exists():
                            try:
                                os.unlink(stale)
                                log(f'Removed stale: {stale}')
                            except Exception as e:
                                log(f'Could not remove stale {stale}: {e}')

                    write_status('Burning in captions...', progress=60)

                    # Call pycaps render via Typer CliRunner (runs in-process, sets cwd to find template)
                    from typer.testing import CliRunner
                    from pycaps.cli.render_cli import render_app
                    runner = CliRunner(mix_stderr=False)
                    import os as _os
                    orig_cwd = _os.getcwd()
                    try:
                        _os.chdir('/opt/video_pipeline_v3')
                        r2 = runner.invoke(render_app, [
                            '--input', str(wna_with_intro_use),
                            '--output', str(captioned),
                            '--template', 'hype',
                            '--transcript', str(voice_srt),
                            '--transcript-format', 'srt',
                            '--style', f'word.font-size={fs}px',
                            '--style', f'word-being-narrated.color={hc}!important',
                            '--style', f'word-already-narrated.color={fc}!important',
                            '--style', f'word.color={fc}!important',
                            '--video-quality', 'high',
                        ])
                        result_code = r2.exit_code if r2 else 1
                        if r2 and r2.stderr:
                            log(f'pycaps stderr: {r2.stderr[:200]}')
                    finally:
                        _os.chdir(orig_cwd)
                    log(f'Captions applied: exit={result_code}')
                    captions_ok = Path(captioned).exists() and Path(captioned).stat().st_size > 1000
                    log(f'Captions applied: output_exists={Path(captioned).exists()}')
                    if not captions_ok:
                        # Fallback: copy wna_with_intro (the audio-bearing video) so pipeline can continue
                        fallback_src = wna_with_intro_use
                        log(f'Caption fallback: copying {fallback_src} to {captioned}')
                        shutil.copy2(fallback_src, captioned)
                        log(f'Caption fallback complete: {Path(captioned).stat().st_size // 1024 // 1024}MB')

                    # --- Music mix (before logo overlay) ---
                    final_ts = datetime.now().strftime('%H%M%S')
                    ts_music = f'video_music_{final_ts}.mp4'
                    music_out = str(work / ts_music)
                    captioned_for_out = _mix_music(str(captioned), music_out, work, cfg.get('music', 'ambient_piano'))

                    # --- Logo overlay ---
                    final_with_logo = str(work / 'video_final.mp4')
                    logo_cfg = cfg.get('logoPath', '')
                    if logo_cfg and os.path.exists(logo_cfg):
                        write_status('Adding logo...', progress=75)
                        logo_cmd = [
                            'ffmpeg', '-y', '-i', captioned_for_out,
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
                        # Save timestamped copy for history (logo applied, music mixed)
                        from datetime import datetime
                        import shutil as _shutil
                        ts = datetime.now().strftime('%H%M%S')
                        ts_video = f'video_{ts}.mp4'
                        _shutil.copy2(captioned_for_out, work / ts_video)
                        if final_out.exists():
                            _shutil.copy2(str(final_out), work / ts_video)
                        # Maintain videos list
                        videos_list = [ts_video]
                        vp = work / 'videos.json'
                        if vp.exists():
                            with open(vp) as vf:
                                videos_list = [ts_video] + json.load(vf).get('videos', [])
                        with open(vp, 'w') as vf:
                            json.dump({'videos': videos_list}, vf)
                        # Final output: music-mixed captioned (with logo applied via final_with_logo)
                        ts_video = datetime.now().strftime('%H%M%S')
                        ts_video = f'video_{ts_video}.mp4'
                        ts_path = work / ts_video
                        if not ts_path.exists() or ts_path.stat().st_size == 0:
                            _shutil.copy2(final_with_logo, ts_path)
                        log(f'Final video: {ts_video}')
                        videos_list = [ts_video]
                        vp = work / 'videos.json'
                        if vp.exists():
                            with open(vp) as vf:
                                videos_list = [ts_video] + json.load(vf).get('videos', [])
                        with open(vp, 'w') as vf:
                            json.dump({'videos': videos_list}, vf)
                        write_status('Complete!', done=True, video_path=ts_video, videos=videos_list, progress=100)
                        _update_video_status(job_id, 'completed', datetime.now().isoformat())
                    # Final output: captioned video with no piano music mixing
                    import shutil as _shutil2
                    from datetime import datetime
                    ts_video = datetime.now().strftime('%H%M%S')
                    ts_video = f'video_{ts_video}.mp4'
                    ts_path = work / ts_video
                    if not ts_path.exists() or ts_path.stat().st_size == 0:
                        _shutil2.copy2(captioned_for_out, ts_path)
                    log(f'Final video: {ts_video}')
                    videos_list = [ts_video]
                    vp = work / 'videos.json'
                    if vp.exists():
                        with open(vp) as vf:
                            videos_list = [ts_video] + json.load(vf).get('videos', [])
                    with open(vp, 'w') as vf:
                        json.dump({'videos': videos_list}, vf)
                    write_status('Complete!', done=True, video_path=ts_video, videos=videos_list, progress=100)
                    _update_video_status(job_id, 'completed', datetime.now().isoformat())
                except Exception as e:
                    log(f'Build error: {e}')
                    _update_video_status(job_id, 'failed')
                    try:
                        write_status(f'Error: {e}', done=False, video_path='')
                    except:
                        pass
                finally:
                    try:
                        os.unlink(lock_file)
                    except:
                        pass
                    release_global_lock()

            # Start pipeline only if not suppressed (noPipeline flag from test.html)
            if not no_pipeline:
                init_dispatcher()
                position = enqueue(job_id, user_id)
                write_status(f'Queued at position {position}...', done=False, video_path='')

            # Write config SYNCHRONOUSLY before returning — so save-settings works immediately
            # Use actual image count (images already downloaded to img_dir) not sel_indices default
            actual_sync_count = len(list(img_dir.iterdir())) if img_dir.exists() else 0
            n_sync = min(30, actual_sync_count) if actual_sync_count > 0 else min(30, len(sel_indices))
            cap_style = payload.get('captionStyle', {})
            try:
                with open(work / 'pipeline_config.json', 'w') as f:
                    json.dump({
                        'address': addr, 'script': script, 'voice': voice,
                        'motion': payload.get('motion', 'cinematic'),
                        'imageCount': n_sync, 'selectedIndices': list(range(n_sync)),
                        'captionStyle': cap_style,
                        'sourceJobId': source_job_id or '',
                        'price': payload.get('price', ''),
                        'beds': payload.get('beds', ''),
                        'baths': payload.get('baths', ''),
                        'sqft': payload.get('sqft', ''),
                        'description': payload.get('description', ''),
                        'logoPosition': payload.get('logoPosition', 'bottom-right'),
                        'logoSize': int(payload.get('logoSize', 15)),
                        'startCaption': payload.get('startCaption', ''),
                        'startDuration': float(payload.get('startDuration', 3)),
                        'endCaption': payload.get('endCaption', ''),
                        'endDuration': float(payload.get('endDuration', 4)),
                        'ratio': ratio,
                        'duration': int(payload.get('duration', 60) or 60),
                        'music': payload.get('music', 'ambient_piano'),
                        'musicUrl': payload.get('musicUrl', ''),
                    }, f, indent=2)
            except:
                pass
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
            # Auth required: prevent anonymous abuse of scraping
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/scrape', user_id=user_id):
                return
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
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
            except Exception as e:
                log(f'Scrape error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
            return

        elif p == '/api/lead':
            # Lead capture: POST {email, name, source?, plan?, brokerage?}
            # Saves to leads.db AND sends welcome email via email_automation
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                data = json.loads(body)
                email = (data.get('email') or '').strip().lower()
                name = (data.get('name') or '').strip()
                source = data.get('source', 'register_page')
                if not email or '@' not in email:
                    raise ValueError('Valid email required')

                # Use email_automation.capture_lead — handles DB insert + welcome email
                result = _email_capture_lead(email, name, source)

                if result.get('status') == 'already_subscribed':
                    _status = 'already_subscribed'
                else:
                    _status = result.get('status', 'captured')

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', '')
                allowed = ['https://vybord.com', 'https://app.vybord.com', 'https://www.vybord.com']
                self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'status': _status, 'email': email}).encode())
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', '')
                allowed = ['https://vybord.com', 'https://app.vybord.com', 'https://www.vybord.com']
                self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
            except Exception as e:
                log(f'Lead capture error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', '')
                allowed = ['https://vybord.com', 'https://app.vybord.com', 'https://www.vybord.com']
                self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
            return

        elif p == '/api/model-video':
            # ModelVideo pipeline: accepts {url, job_id?} → enqueues to v3 queue
            # Auth required: prevent anonymous GPU compute abuse
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/model-video', user_id=user_id):
                return
            # Uses subprocess to avoid polluting the HTTP server's Python state
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                data = json.loads(body)
                url = data.get('url', '')
                job_id = data.get('job_id', '')
                if not url:
                    raise ValueError('No URL provided')

                # Run as subprocess so stdout/sys.path pollution stays isolated
                cmd = [
                    '/opt/venv/bin/python',
                    '/root/.openclaw/workspace/model_video/run_pipeline.py',
                    url,
                ]
                if job_id:
                    cmd.extend(['--job-id', job_id])

                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd='/root/.openclaw/workspace/model_video',
                )

                if proc.returncode != 0:
                    raise RuntimeError(f"Pipeline failed: {proc.stderr or proc.stdout}")

                # Extract job_id from output (last JSON line or parse stdout)
                output = proc.stdout.strip()
                # Find the last JSON object in output
                job_id_out = None
                for line in reversed(output.splitlines()):
                    line = line.strip()
                    if line.startswith('{'):
                        try:
                            parsed = json.loads(line)
                            job_id_out = parsed.get('job_id')
                            break
                        except json.JSONDecodeError:
                            continue
                if not job_id_out:
                    raise RuntimeError(f"No job_id in pipeline output: {output[:200]}")

                queue_pos = None
                for line in reversed(output.splitlines()):
                    if 'position' in line.lower() and 'queue' in line.lower():
                        try:
                            for part in line.split():
                                if part.isdigit():
                                    queue_pos = int(part)
                                    break
                        except:
                            pass
                        break

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'job_id': job_id_out,
                    'position': queue_pos or 1,
                    'video_url': '',
                }, ensure_ascii=False).encode())
            except subprocess.TimeoutExpired:
                log('ModelVideo timeout')
                self.send_response(504)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Pipeline timeout (120s)', 'success': False}).encode())
            except Exception as e:
                import traceback
                log(f'ModelVideo error: {e}')
                log(f'ModelVideo traceback: {traceback.format_exc()}')
                try:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': str(e), 'success': False}).encode())
                except Exception as inner:
                    log(f'ModelVideo error in error handler: {inner}')
            return

        elif p in ('/api/create', '/api/send.php', '/send.php'):
            # Endpoint for create.html - accepts {settings, userEmail, images, musicUrl}
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/create', user_id=user_id):
                return
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
                voice = settings.get('voice', 'Roger')
                script = settings.get('script', '')
                duration = int(settings.get('duration', 60))
                font_size = int(settings.get('fontSize', 55))
                text_color = settings.get('textColor', '#FFFF00')
                # If price is still bad
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
                img_dir = work / 'listing_src'
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
                            req = urllib.request.Request(img_data, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
                            with urllib.request.urlopen(req, timeout=15) as resp:
                                content_type = resp.headers.get('Content-Type', 'image/jpeg')
                                ext = 'webp' if 'webp' in content_type else 'jpg'
                                actual_fname = fname.replace('.jpg', f'.{ext}')
                                (img_dir / actual_fname).write_bytes(resp.read())
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
                    "duration": duration,
                    'userEmail': user_email,
                }
                with open(work / 'pipeline_config.json', 'w') as f:
                    json.dump(cfg_out, f, indent=2)

                # Write initial status.json so /api/status returns useful data immediately
                with open(work / 'status.json', 'w') as f:
                    json.dump({
                        'status': 'Queued, starting shortly...',
                        'done': False, 'job_id': job_id, 'progress': 0
                    }, f)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                resp = {'job_id': job_id, 'status': f'Job created with {len(list(img_dir.iterdir()))} images, building...', 'done': False}
                self.wfile.write(json.dumps(resp).encode())

                def do_send_build():
                    if not acquire_global_lock():
                        log(f'Global build lock held, skipping send_build {job_id}')
                        return
                    try:
                        import edge_tts, asyncio
                        VENV = '/opt/venv/bin/python3'
                        voice_m4a = work / 'voice.m4a'
                        sel = list(range(min(30, len(list(img_dir.iterdir())))))
                        cap = cfg_out['captionStyle']
                        if script:
                            asyncio.run(edge_tts.Communicate(script, get_edge_voice(voice)).save(str(voice_m4a)))
                            log(f'Voice generated: {voice_m4a.stat().st_size} bytes')
                        cfg_out['selectedIndices'] = sel
                        with open(work / 'pipeline_config.json', 'w') as f:
                            json.dump(cfg_out, f, indent=2)
                        motion_val = cfg_out.get('motion', 'cinematic')
                        result = run([VENV, '/opt/video_pipeline_v3/scripts/build_vps.py',
                                      '--work', str(work), '--listing', str(img_dir),
                                      '--duration', str(duration),
                                      '--motion', motion_val,
                                      '--ratio', cfg_out.get('ratio', '9:16'),
                                      '--images_per_slide', '1'],
                                     timeout=300, cwd='/opt/video_pipeline_v3')
                        log(f'Slides built: exit={result.returncode}')
                        write_status('Slides ready, assembling...', progress=35)
                        if result.returncode != 0:
                            try:
                                with open(work / 'status.json', 'w') as f:
                                    json.dump({'status': f'Slides build failed (exit {result.returncode})', 'done': False, 'video': '', 'job_id': job_id}, f)
                            except:
                                pass
                            log(f'Build aborted: build_vps.py failed')
                            return
                    except Exception as e:
                        log(f'Build error: {e}')
                    finally:
                        release_global_lock()

                threading.Thread(target=do_send_build, daemon=True).start()
                return

            except Exception as e:
                log(f'send.php error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # Queue position endpoint — returns {"status": "pending", "position": 3} or 404
        elif p.startswith('/api/queue/'):
            job_id = p.split('/api/queue/')[1].lstrip('/')
            info = get_queue_position(job_id)
            if info:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(info).encode())
            else:
                self.send_response(404)
            return

        elif p.startswith('/api/status') and not p.startswith('/api/videos'):
            job_id = p.split('/api/status')[1].lstrip('/')
            if not job_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing job_id'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            status_file = work / 'status.json'
            cfg_file = work / 'pipeline_config.json'
            # Merge pipeline_config into status so review page gets all fields
            merged = {'job_id': job_id}
            if status_file.exists():
                with open(status_file) as f:
                    merged.update(json.load(f))
            if cfg_file.exists():
                with open(cfg_file) as f:
                    cfg = json.load(f)
                    # config fields override status fields
                    for k, v in cfg.items():
                        merged[k] = v
            self.wfile.write(json.dumps(merged).encode())
            return
        elif p.startswith('/api/videos/'):
            # videos list — handled via /api/video-list GET endpoint
            self.send_response(404)
            self.end_headers()
            return

        elif p.startswith('/api/upload-images/'):
            # Auth required: prevent uploading images to other users' jobs
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/upload-images', user_id=user_id):
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode()
                payload = json.loads(body)
                images = payload.get('images', [])
                job_id = p.replace('/api/upload-images/', '').split('/')[0]
                # Ownership check: only the job owner can upload images to it
                conn = sqlite3.connect(str(USER_DB), timeout=5)
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (job_id,)).fetchone()
                conn.close()
                if not row or row['user_id'] != user_id:
                    self.send_response(403)
                    self.send_header('Content-Type', 'application/json')
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Forbidden: you do not own this job'}).encode())
                    return
                work = Path(f"/tmp/rs_uploads/{job_id}")
                img_dir = work / 'listing_src'
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
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': None}).encode())
            except Exception as e:
                log(f'Upload error: {e}')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        elif p.startswith('/api/script/generate/'):
            """Generate narration script for a job. Returns script immediately (fast, ~100ms)."""
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/script/generate', user_id=user_id):
                return
            job_id = p.replace('/api/script/generate/', '').split('/')[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing job_id'}).encode())
                return
            # Ownership check: only the job owner can regenerate its script
            conn = sqlite3.connect(str(USER_DB), timeout=5)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (job_id,)).fetchone()
            conn.close()
            if not row or row['user_id'] != user_id:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Forbidden: you do not own this job'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            st_file = work / 'status.json'
            if not work.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found'}).encode())
                return
            # pipeline_config.json is written after voice completes; fall back to status.json if not ready
            if cfg_file.exists():
                with open(cfg_file) as f:
                    cfg = json.load(f)
            elif st_file.exists():
                with open(st_file) as f:
                    st = json.load(f)
                cfg = {
                    'address': st.get('address', 'the property'),
                    'beds': st.get('beds', ''),
                    'baths': st.get('baths', ''),
                    'sqft': st.get('sqft', ''),
                    'price': st.get('price', ''),
                    'script': st.get('script', ''),
                }
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found — not ready yet'}).encode())
                return
            addr = cfg.get('address', 'the property')
            beds = cfg.get('beds', '')
            baths = cfg.get('baths', '')
            sqft = cfg.get('sqft', '')
            price = cfg.get('price', '')
            duration = int(cfg.get('duration', 60) or 60)
            script = _generate_script_ai(addr, beds, baths, sqft, price, duration)
            cfg['script'] = script
            with open(cfg_file, 'w') as f:
                json.dump(cfg, f, indent=2)
            log(f'Script gen done: {script[:80]}...')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', '')
            allowed = ['https://vybord.com', 'https://app.vybord.com']
            self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'script': script}).encode())
            return

        elif p.startswith('/api/config/'):
            """Return current config for a job (for polling after script gen)."""
            # Auth optional: job_id is random and non-guessable
            job_id = p.replace('/api/config/', '').split('/')[0]
            log(f'[/api/config] job_id={job_id}')
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            st_file = work / 'status.json'
            if cfg_file.exists():
                with open(cfg_file) as f:
                    cfg = json.load(f)
            elif st_file.exists():
                with open(st_file) as f:
                    st = json.load(f)
                cfg = {
                    'address': st.get('address', ''),
                    'script': st.get('script', ''),
                    'voice': st.get('voice', 'Roger'),
                    'price': st.get('price', ''),
                    'beds': st.get('beds', ''),
                    'baths': st.get('baths', ''),
                    'sqft': st.get('sqft', ''),
                    'ratio': st.get('ratio', '16:9'),
                    'captionStyle': st.get('captionStyle', {}),
                    'imageCount': st.get('imageCount', 0),
                    'selectedIndices': st.get('selectedIndices', list(range(15))),
                }
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Job not found'}).encode())
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', '')
            allowed = ['https://vybord.com', 'https://app.vybord.com']
            self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps(cfg).encode())
            return

        elif p.startswith('/api/save-settings/'):
            # Alias for /api/save/ — used by v3.7 static review page
            # Auth required + ownership check: only the job owner can modify its settings
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/save', user_id=user_id):
                return
            job_id = p.replace('/api/save-settings/', '').split('/')[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Missing job_id'}).encode())
                return
            # Ownership check
            conn = sqlite3.connect(str(USER_DB), timeout=5)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (job_id,)).fetchone()
            conn.close()
            if not row or row['user_id'] != user_id:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Forbidden: you do not own this job'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            if not cfg_file.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Job not found'}).encode())
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode() if length > 0 else '{}'
            try:
                data = json.loads(body)
            except:
                data = {}
            # Update config (including nested captionStyle)
            try:
                with open(cfg_file) as f:
                    cfg = json.loads(f.read())
            except:
                cfg = {}
            for key in ('script', 'voice', 'motion', 'startCaption', 'endCaption',
                        'ratio', 'duration', 'fontSize', 'highlightColor', 'fontColor', 'beds', 'baths',
                        'sqft', 'price', 'logoSize', 'logoPosition', 'logoBase64',
                        'selectedIndices', 'captionStyle', 'startDuration', 'endDuration',
                        'music', 'musicUrl'):
                if key in data:
                    cfg[key] = data[key]
            with open(cfg_file, 'w') as f:
                json.dump(cfg, f, indent=2)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
            return

        elif p.startswith('/api/save/'):
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/save', user_id=user_id):
                return
            job_id = p.replace('/api/save/', '').split('/')[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Missing job_id'}).encode())
                return
            # Ownership check
            conn = sqlite3.connect(str(USER_DB), timeout=5)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT user_id FROM videos WHERE job_id = ?", (job_id,)).fetchone()
            conn.close()
            if not row or row['user_id'] != user_id:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Forbidden: you do not own this job'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            if not cfg_file.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Job not found'}).encode())
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode() if length > 0 else '{}'
            try:
                data = json.loads(body)
            except:
                data = {}
            # Update config
            with open(cfg_file) as f:
                cfg = json.load(f)
            for key in ('script', 'voice', 'motion', 'startCaption', 'endCaption',
                        'ratio', 'duration', 'fontSize', 'highlightColor', 'fontColor', 'beds', 'baths',
                        'sqft', 'price', 'logoSize', 'logoPosition', 'logoBase64',
                        'selectedIndices', 'captionStyle', 'startDuration', 'endDuration',
                        'music', 'musicUrl'):
                if key in data:
                    cfg[key] = data[key]
            with open(cfg_file, 'w') as f:
                json.dump(cfg, f, indent=2)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
            return

        elif p.startswith('/api/build/'):
            user_id, email = self.authenticate()
            if not user_id:
                self.require_auth()
                return
            # Rate limit: per-user sliding window
            if not self.check_rate_limit('/api/build', user_id=user_id):
                return
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
                    origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                    self.send_header("Access-Control-Allow-Credentials", "true")
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': st['status']}).encode())
                    return
            # Parse request body for script/voice overrides
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length > 0 else "{}"
            try:
                payload = json.loads(body)
            except:
                payload = {}

            with open(cfg_file) as f:
                cfg = json.load(f)
            img_dir = work / 'listing_src'

            # Merge ALL fields from payload into config and save
            for key in ['script', 'voice', 'startCaption', 'endCaption', 'startDuration', 'endDuration',
                        'motion', 'ratio', 'duration', 'fontSize', 'highlightColor', 'fontColor',
                        'beds', 'baths', 'sqft', 'price', 'logoSize', 'logoPosition']:
                if key in payload and payload[key] not in (None, ''):
                    cfg[key] = payload[key]
            # Also save caption style (all color/size fields in one object)
            if 'fontSize' in cfg or 'highlightColor' in cfg or 'fontColor' in cfg:
                cfg['captionStyle'] = {
                    'fontSize': int(cfg.get('fontSize', cfg.get('captionStyle', {}).get('fontSize', 55))),
                    'highlightColor': cfg.get('highlightColor', cfg.get('captionStyle', {}).get('highlightColor', '#FF69B4')),
                    'fontColor': cfg.get('fontColor', cfg.get('captionStyle', {}).get('fontColor', '#FFFFFF')),
                }
            with open(cfg_file, 'w') as f:
                json.dump(cfg, f, indent=2)
            log(f'Config updated from review page: script={cfg.get("script","")[:50]}')

            # Bail if a build is already running (generate may have started one)
            lock_file = work / '.build.lock'
            if not is_lock_stale(lock_file):
                log(f'Build already in progress for {job_id} via /api/build, skipping')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'Build already in progress...'}).encode())
                return

            # Create lock SYNCHRONOUSLY before spawning thread — prevents race with generate
            try:
                with open(lock_file, 'w') as f:
                    f.write(str(os.getpid()))
            except:
                pass

            write_job_status(work, 'Building...')
            def do_build():
                if not acquire_global_lock():
                    log(f'Global build lock held, skipping {job_id}')
                    write_job_status(work, 'Another build is in progress, please wait...')
                    return
                try:
                    import edge_tts, asyncio, shutil
                    VENV = '/opt/venv/bin/python3'
                    voice_m4a = work / 'voice.m4a'
                    # Read from SAVED config (so any fields we saved above are used)
                    script = cfg.get('script', '')
                    voice = cfg.get('voice', 'Roger')
                    duration = int(cfg.get('duration', 60))
                    if script:
                        asyncio.run(edge_tts.Communicate(
                            script,
                            get_edge_voice(voice)
                        ).save(str(voice_m4a)))
                        log(f'Voice generated: {voice_m4a.stat().st_size} bytes')
                        sel = list(range(min(30, len(list(img_dir.iterdir())))))
                        cfg['selectedIndices'] = sel
                    with open(cfg_file, 'w') as f:
                        json.dump(cfg, f, indent=2)

                    # --- Build slides ---
                    write_job_status(work, 'Building slides...')
                    motion_val = cfg.get('motion', 'cinematic')
                    result = run([VENV, '/opt/video_pipeline_v3/scripts/build_vps.py',
                                  '--work', str(work), '--listing', str(img_dir),
                                  '--duration', str(duration),
                                  '--motion', motion_val,
                                  '--ratio', cfg.get('ratio', '9:16')],
                                 timeout=300, cwd='/opt/video_pipeline_v3')
                    log(f'Slides built: exit={result.returncode}')
                    write_job_status(work, 'Slides ready, assembling...', progress=35)
                    if result.returncode != 0:
                        write_job_status(work, f'Slides build failed (exit {result.returncode})')
                        return

                    # --- Whisper transcript ---
                    write_job_status(work, 'Generating captions...')
                    log(f'Whisper: starting transcription')
                    try:
                        r = run([VENV, '-m', 'whisper', str(voice_m4a), '--model', 'base',
                                '--language', 'English', '--word_timestamps', 'True', '--output_dir', str(work)],
                               cwd='/opt/video_pipeline_v3', timeout=300)
                        log(f'Whisper done: returncode={r.returncode}')
                        wj = work / 'voice.json'
                        if wj.exists():
                            from datetime import timedelta
                            def fmt(t):
                                td = timedelta(seconds=t)
                                s = int(td.total_seconds())
                                ms = int((t - s) * 1000)
                                return f"{s//3600:02d}:{s%3600//60:02d}:{s%60:02d},{ms:03d}"
                            with open(wj) as f:
                                wdata = json.load(f)
                            srt_path = work / 'voice.srt'
                            with open(srt_path, 'w') as f:
                                word_id = 0
                                for seg in wdata.get('segments', []):
                                    words = seg.get('words', [])
                                    if words:
                                        for w in words:
                                            word_text = w['word'].strip()
                                            if not word_text:
                                                continue
                                            word_id += 1
                                            w_start = float(w['start'])
                                            w_end = float(w['end'])
                                            f.write(f"{word_id}\n{fmt(w_start)} --> {fmt(w_end)}\n{word_text}\n\n")
                                    else:
                                        text = seg['text'].strip()
                                        if not text:
                                            continue
                                        seg_id = seg['id'] + 1
                                        f.write(f"{seg_id}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{text}\n\n")
                            log(f'SRT written: {srt_path.stat().st_size} bytes ({word_id} words)')
                        else:
                            log(f'Whisper: voice.json not found')
                    except Exception as e:
                        log(f'Whisper error: {e}')

                    # --- Captioned video with pycaps ---
                    write_job_status(work, 'Adding captions...')
                    captioned = str(work / 'video_captioned.mp4')
                    cap = cfg.get('captionStyle', {})
                    fs = cap.get('fontSize', 55)
                    hc = '#' + cap.get('highlightColor', 'FF69B4').lstrip('#')
                    fc = '#' + cap.get('fontColor', 'FFFFFF').lstrip('#')
                    # Input: use latest timestamped video (post-mux slides+voice) if it exists,
                    # otherwise video_wna2.mp4 (pre-mux). Never use video_wna.mp4 (overwritten by mux).
                    import glob as _glob
                    ts_videos = sorted(Path(work).glob('video_??????.mp4'), reverse=True)
                    video_for_captions = str(ts_videos[0]) if ts_videos else str(work / 'video_wna2.mp4')
                    from typer.testing import CliRunner
                    from pycaps.cli.render_cli import render_app
                    runner = CliRunner(mix_stderr=False)
                    import os as _os
                    orig_cwd = _os.getcwd()
                    result_code = 1
                    try:
                        _os.chdir('/opt/video_pipeline_v3')
                        r2 = runner.invoke(render_app, [
                            '--input', video_for_captions,
                            '--output', captioned,
                            '--template', 'hype',
                            '--transcript', str(work / 'voice.srt'),
                            '--transcript-format', 'srt',
                            '--style', f'word.font-size={fs}px',
                            '--style', f'word-being-narrated.color={hc}!important',
                            '--style', f'word-already-narrated.color={fc}!important',
                            '--style', f'word.color={fc}!important',
                            '--video-quality', 'high',
                        ])
                        caps_success = r2 and r2.exit_code == 0
                        if r2 and r2.stderr:
                            log(f'pycaps stderr: {r2.stderr[:200]}')
                    except Exception as e:
                        log(f'pycaps invoke error: {e}')
                        caps_success = False
                    finally:
                        _os.chdir(orig_cwd)
                    captions_ok = caps_success and Path(captioned).exists() and Path(captioned).stat().st_size > 1000
                    log(f'Captions OK: {Path(captioned).stat().st_size // 1024 // 1024}MB' if captions_ok else f'Captions ERR')
                    if not captions_ok:
                        # Fallback: copy the latest timestamped video so pipeline can continue
                        fallback_src = video_for_captions
                        log(f'Fallback: copying {fallback_src} to {captioned}')
                        shutil.copy2(fallback_src, captioned)
                        log(f'Fallback complete: {Path(captioned).stat().st_size // 1024 // 1024}MB')

                    # --- Intro card ---
                    intro_mp4 = ''
                    start_caption = cfg.get('startCaption', '')
                    end_caption = cfg.get('endCaption', '')
                    start_dur = int(cfg.get('startDuration', 3))
                    end_dur = int(cfg.get('endDuration', 3))
                    if start_caption:
                        try:
                            intro_png = str(work / 'intro_card.png')
                            intro_anim = str(work / 'intro_card.mp4')
                            run([sys.executable, '/opt/video_pipeline_v3/scripts/branding.py',
                                 '--mode', 'intro', '--text', start_caption,
                                 '--subtext', cfg.get('address', ''),
                                 '--output', intro_png, '--ratio', cfg.get('ratio', '16:9'),
                                 '--duration', str(start_dur)],
                                timeout=30, cwd='/opt/video_pipeline_v3')
                            intro_mp4 = intro_anim
                            log(f'Intro card: {intro_mp4}')
                        except Exception as e:
                            log(f'Intro error: {e}')

                    # --- Outro card ---
                    outro_mp4 = ''
                    if end_caption:
                        try:
                            outro_png = str(work / 'outro_card.png')
                            outro_anim = str(work / 'outro_card.mp4')
                            run([sys.executable, '/opt/video_pipeline_v3/scripts/branding.py',
                                 '--mode', 'outro', '--text', end_caption,
                                 '--subtext', '', '--output', outro_png,
                                 '--ratio', cfg.get('ratio', '16:9'),
                                 '--duration', str(end_dur)],
                                timeout=30, cwd='/opt/video_pipeline_v3')
                            outro_mp4 = outro_anim
                            log(f'Outro card: {outro_mp4}')
                        except Exception as e:
                            log(f'Outro error: {e}')

                    # --- Concatenate intro + slides + outro ---
                    video_with_intro_outro = str(work / 'video_with_intro_outro.mp4')
                    intro_anim = str(work / 'intro_card_anim.mp4')
                    outro_anim = str(work / 'outro_card_anim.mp4')
                    main_slides = str(work / 'video_noaudio.mp4')
                    clip_files = []
                    if os.path.exists(intro_anim):
                        clip_files.append(intro_anim)
                    if os.path.exists(main_slides):
                        clip_files.append(main_slides)
                    if os.path.exists(outro_anim):
                        clip_files.append(outro_anim)
                    log(f'CONCAT clips: {clip_files}')
                    if len(clip_files) > 1:
                        concat_list = str(work / 'concat_list.txt')
                        with open(concat_list, 'w') as f2:
                            for cf in clip_files:
                                f2.write("file '" + cf + "'\n")
                        r_cat = run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                                     '-i', concat_list, '-c', 'copy', video_with_intro_outro],
                                    timeout=120)
                        log(f'Concat intro/outro: exit={r_cat.returncode}')
                    elif clip_files:
                        video_with_intro_outro = clip_files[0]
                    else:
                        video_with_intro_outro = main_slides

                    # --- Remux with audio ---
                    wna_with_intro = str(work / 'video_wna2.mp4')
                    if video_with_intro_outro != str(work / 'video_noaudio.mp4'):
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
                        wna_src = wna_with_intro if r_mux.returncode == 0 else str(work / 'video_wna.mp4')
                    else:
                        wna_src = str(work / 'video_wna.mp4')

                    # --- Logo overlay ---
                    captioned = str(work / 'video_captioned.mp4')
                    final_with_logo = str(work / 'video_final.mp4')
                    logo_cfg = cfg.get('logoPath', '')
                    if logo_cfg and os.path.exists(logo_cfg):
                        write_job_status(work, 'Adding logo...')
                        logo_cmd = ['ffmpeg', '-y', '-i', final_no_music,
                                    '-i', logo_cfg,
                                    '-filter_complex',
                                    f"[1:v]scale=iw*{cfg.get('logoSize', 15)/100.0:-1}[logo];"
                                    f"[0:v][logo]overlay="
                                    + ({'top-left': '10:10', 'top-right': 'W-w-10:10',
                                        'bottom-left': '10:H-h-10',
                                        'bottom-right': 'W-w-10:H-h-10'}.get(
                                           cfg.get('logoPosition', 'bottom-right'), 'W-w-10:H-h-10')),
                                    '-c:a', 'copy', final_with_logo]
                        r_logo = run(logo_cmd, timeout=120)
                        log(f'Logo: exit={r_logo.returncode}')
                    else:
                        shutil.copy2(final_no_music, final_with_logo)

                    # --- Burn in captions (pycaps) ---
                    write_job_status(work, 'Applying captions...')
                    captioned = str(work / 'video_captioned.mp4')
                    srt = work / 'voice.srt'
                    if srt.exists():
                        from typer.testing import CliRunner
                        from pycaps.cli.render_cli import render_app
                        runner = CliRunner()
                        hc = '#' + cfg.get('captionStyle', {}).get('highlightColor', 'FF4444').lstrip('#')
                        fc = cfg.get('captionStyle', {}).get('fontColor', 'FFFFFF').lstrip('#')
                        fs = cfg.get('captionStyle', {}).get('fontSize', 55)
                        result = runner.invoke(render_app, [
                            'render',
                            '--input', final_with_logo,
                            '--output', captioned,
                            '--transcript', str(srt),
                            '--transcript-format', 'srt',
                            '--template', cfg.get('captionTemplate', 'hype'),
                            '--style', f'word-being-narrated.color={hc}',
                            '--style', f'word-already-narrated.color={fc}',
                            '--style', f'word.color={fc}',
                            '--style', f'word.font-size={fs}px',
                            '--video-quality', 'high',
                        ])
                        caps_ok = (result and result.ok and
                                   os.path.exists(captioned) and os.path.getsize(captioned) > 1000)
                        log(f'Captions applied: exit={result.exit_code if result else None}')
                        if not caps_ok:
                            log(f'Caption render failed — using non-captioned video')
                            shutil.copy2(final_with_logo, captioned)
                    else:
                        shutil.copy2(final_with_logo, captioned)
                        log('No SRT found — using non-captioned video')

                    ts_video = datetime.now().strftime('%H%M%S')
                    ts_video = f'video_{ts_video}.mp4'
                    ts_path = work / ts_video
                    if not ts_path.exists() or ts_path.stat().st_size == 0:
                        shutil.copy2(captioned, ts_path)
                    log(f'Final video: {ts_video}')

                    # Maintain videos list in status
                    videos_list = [ts_video]
                    videos_json = work / 'videos.json'
                    if videos_json.exists():
                        with open(videos_json) as vf:
                            videos_list = [ts_video] + json.load(vf).get('videos', [])
                    with open(videos_json, 'w') as vf:
                        json.dump({'videos': videos_list}, vf)
                    with open(work / 'status.json', 'w') as f2:
                        json.dump({'status': 'Complete!', 'done': True, 'video': ts_video,
                                   'videos': videos_list, 'job_id': job_id}, f2)
                    log(f'Build complete: {ts_path}')
                except Exception as e:
                    log(f'Build error: {e}')
                    try:
                        write_job_status(work, f'Error: {e}')
                    except:
                        pass
                finally:
                    release_global_lock()
            threading.Thread(target=do_build, daemon=True).start()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'Building...'}).encode())
            return

        elif p.startswith('/api/caption/'):
            """Standalone caption generation — isolated test endpoint.
            Runs ONLY the pycaps step on an existing job's video + voice.srt."""
            job_id = p.replace('/api/caption/', '').split('/')[0]
            if not job_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing job_id'}).encode())
                return
            work = Path(f"/tmp/rs_uploads/{job_id}")
            cfg_file = work / 'pipeline_config.json'
            if not cfg_file.exists():
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'job not found'}).encode())
                return
            with open(cfg_file) as f:
                cfg = json.load(f)
            voice_srt = work / 'voice.srt'
            if not voice_srt.exists():
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'voice.srt not found — run voice generation first'}).encode())
                return
            # Find input video: prefer video_wna2.mp4 (post-mux, pre-captions) > video_wna.mp4 > timestamped
            if (work / 'video_wna2.mp4').exists():
                video_input = str(work / 'video_wna2.mp4')
                log(f'Caption: using video_wna2.mp4 ({Path(video_input).stat().st_size // 1024 // 1024}MB)')
            elif (work / 'video_wna.mp4').exists():
                video_input = str(work / 'video_wna.mp4')
                log(f'Caption: using video_wna.mp4')
            else:
                ts_videos = sorted(Path(work).glob('video_??????.mp4'), reverse=True)
                if ts_videos:
                    video_input = str(ts_videos[0])
                    log(f'Caption: no wna2/wna, using timestamped: {video_input} ({Path(video_input).stat().st_size // 1024 // 1024}MB)')
                else:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'No video found in job directory'}).encode())
                    return
            captioned = str(work / 'video_captioned.mp4')
            cap = cfg.get('captionStyle', {})
            fs = cap.get('fontSize', 55)
            hc = '#' + cap.get('highlightColor', 'FF69B4').lstrip('#')
            fc = '#' + cap.get('fontColor', 'FFFFFF').lstrip('#')
            write_job_status(work, 'Adding captions...')
            caps_success = False
            try:
                from pycaps.logger import set_logging_level
                from pycaps.template import TemplateLoader, TemplateFactory
                from pycaps.transcriber import TranscriptFormat
                from pycaps.common.types import VideoQuality
                import logging
                set_logging_level(logging.INFO)
                template = TemplateFactory().create('hype')
                builder = TemplateLoader(template).with_input_video(video_input).load(False)
                builder.with_output_video(captioned)
                builder.add_css_content(
                    f'.word {{ font-size: {fs}px; color: {fc}; }}\n'
                    f'.word-being-narrated {{ color: {hc} !important; }}\n'
                    f'.word-already-narrated {{ color: {fc} !important; }}\n'
                )
                builder.with_transcription_file(str(voice_srt), TranscriptFormat.SRT)
                builder.with_video_quality(VideoQuality.HIGH)
                pipeline = builder.build()
                log(f'Running caption pipeline for {job_id}...')
                pipeline.run()
                caps_success = Path(captioned).exists() and Path(captioned).stat().st_size > 1000
                log(f'Caption pipeline done: success={caps_success}')
            except Exception as e:
                log(f'Caption error: {e}')
            captions_ok = caps_success and Path(captioned).exists() and Path(captioned).stat().st_size > 1000
            if captions_ok:
                size_mb = Path(captioned).stat().st_size // 1024 // 1024
                write_job_status(work, f'Captions done ({size_mb}MB)', done=True, video=Path(captioned).name)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                origin = self.headers.get('Origin', ''); allowed = ['https://vybord.com','https://app.vybord.com']; self.send_header('Access-Control-Allow-Origin', origin if origin in allowed else 'https://vybord.com')
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'captioned': captioned, 'size_mb': size_mb}).encode())
            else:
                write_job_status(work, 'Caption failed (in-process API error)')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Caption failed (in-process API error)'}).encode())
            return

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')


def write_job_status(work, text, done=False, video='', videos=None):
    videos = videos or []
    with open(work / 'status.json', 'w') as f:
        json.dump({'status': text, 'done': done, 'video': video, 'videos': videos}, f)


def cleanup_orphan_jobs(max_age_hours=24):
    """Remove job dirs older than max_age_hours to prevent disk bloat. Also expire stale DB records."""
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

def _expire_stale_db_jobs(hours=2):
    """Mark processing jobs older than `hours` as failed."""
    try:
        conn = sqlite3.connect(str(USER_DB), timeout=5)
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        cur = conn.execute("UPDATE videos SET status='failed' WHERE status='processing' AND created_at < ?", (cutoff,))
        conn.commit()
        conn.close()
        if cur.rowcount:
            log(f'Expired {cur.rowcount} stale job record(s)')
    except Exception as e:
        log(f'Expire stale jobs error: {e}')



def _periodic_cleanup():
    """Run stale job expiration every 30 minutes."""
    import threading
    def _run():
        while True:
            time.sleep(1800)  # 30 minutes
            _expire_stale_db_jobs(hours=1)
            cleanup_orphan_jobs(max_age_hours=24)
    threading.Thread(target=_run, daemon=True).start()

if __name__ == '__main__':
    _expire_stale_db_jobs(hours=1)
    cleanup_orphan_jobs(max_age_hours=24)
    _periodic_cleanup()
    import socketserver
    socketserver.TCPServer.allow_reuse_address = True
    Handler.protocol_version = 'HTTP/1.1'
    httpd = socketserver.ThreadingTCPServer(('0.0.0.0', PORT), Handler)
    print(f'Review server running on port {PORT}', flush=True)
    httpd.serve_forever()