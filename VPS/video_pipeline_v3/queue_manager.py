"""
Queue Manager — persistent SQLite-backed job queue for review_server.
Replaces the single-global-lock model with a configurable worker pool.

Every job enters the queue as 'pending'. The dispatcher thread assigns jobs to
concurrent worker slots (MAX_CONCURRENT) as they free up.
"""
import os, sqlite3, threading, time, json, subprocess, shutil, asyncio, edge_tts
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ── Tunables ────────────────────────────────────────────────────────────────
MAX_CONCURRENT = 2   # ffMpeg slide build is RAM/CPU-bound; keep low
POLL_INTERVAL  = 2   # seconds between dispatch checks when idle
STALE_TIMEOUT  = 600 # seconds before a 'processing' job is considered stuck → auto-failed
# ────────────────────────────────────────────────────────────────────────────

USER_DB  = Path("/opt/video_pipeline_v3/user_api.db")
WORK_DIR = Path("/tmp/rs_uploads")
VENV     = "/opt/venv/bin/python"
PIPELINE_V3 = Path("/opt/video_pipeline_v3")

_queue_cond     = threading.Condition()   # dispatcher waits on this
_running_jobs    = {}                    # job_id -> Future
_dispatch_thread = None
_pool            = None
_pool_lock       = threading.Lock()

# ── Public API ──────────────────────────────────────────────────────────────

def init_dispatcher():
    """Start the background dispatcher thread. Idempotent — safe to call multiple times."""
    global _dispatch_thread
    with _pool_lock:
        if _dispatch_thread is None:
            _clean_orphans()
            _dispatch_thread = threading.Thread(target=_dispatch_loop, daemon=True, name="QueueDispatcher")
            _dispatch_thread.start()


def enqueue(job_id, user_id=None):
    """
    Add a job to the queue. Returns (position, total_pending).
    The job's status is set to 'pending' in SQLite.
    """
    conn = sqlite3.connect(str(USER_DB), timeout=5)
    try:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position),0) FROM videos WHERE status='pending'").fetchone()[0]
    except Exception:
        max_pos = 0
    new_pos = max_pos + 1

    # Upsert — insert or update if already exists; 0 = anonymous
    conn.execute("""INSERT OR REPLACE INTO videos
                    (user_id, job_id, status, created_at, position)
                    VALUES (?, ?, 'pending', ?, ?)""",
                 (user_id if user_id else 0, job_id, datetime.now().isoformat(), new_pos))
    conn.commit()
    conn.close()

    _wake_dispatcher()
    return new_pos


def get_queue_position(job_id):
    """Return {'status': str, 'position': int} or None if job not found."""
    try:
        conn = sqlite3.connect(str(USER_DB), timeout=5)
        row = conn.execute(
            "SELECT status, position FROM videos WHERE job_id=?", (job_id,)).fetchone()
        conn.close()
        if row:
            return {"status": row[0], "position": row[1]}
    except Exception:
        pass
    return None


# ── Internal ────────────────────────────────────────────────────────────────

def _clean_orphans():
    """Kill stale Whisper/ffmpeg/build_vps processes orphaned by a crashed server restart."""
    for proc_name in ("whisper", "ffmpeg", "build_vps"):
        try:
            for line in subprocess.check_output(["pgrep", "-f", proc_name], text=True).splitlines():
                pid = int(line.strip())
                try:
                    os.kill(pid, 0)  # check if alive
                except ProcessLookupError:
                    continue
                # Orphaned — kill it
                os.kill(pid, 9)
                print(f"[orphan cleanup] Killed stale {proc_name} pid={pid}")
        except Exception:
            pass
    # Also mark stuck 'processing' jobs as failed so queue can drain
    try:
        conn = sqlite3.connect(str(USER_DB), timeout=5)
        cutoff = (datetime.now() - timedelta(seconds=STALE_TIMEOUT)).isoformat()
        cur = conn.execute(
            "UPDATE videos SET status='failed' WHERE status='processing' AND created_at < ?",
            (cutoff,))
        conn.commit()
        conn.close()
        if cur.rowcount:
            print(f"[orphan cleanup] Marked {cur.rowcount} stale processing jobs as failed")
    except Exception:
        pass

def _wake_dispatcher():
    with _queue_cond:
        _queue_cond.notify_all()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="BuildWorker")
        return _pool


def _dispatch_loop():
    """
    Background loop: waits for a free slot, picks the oldest pending job,
    marks it 'processing', and submits it to the worker pool.
    """
    while True:
        time.sleep(POLL_INTERVAL)
        with _queue_cond:
            # Count how many workers are still active
            active = sum(1 for f in _running_jobs.values() if not f.done())
            if active >= MAX_CONCURRENT:
                _queue_cond.wait(timeout=POLL_INTERVAL * 2)
                continue

            # Claim the next pending job
            conn = sqlite3.connect(str(USER_DB), timeout=5)
            row = conn.execute("""SELECT job_id, position FROM videos
                                  WHERE status='pending'
                                  ORDER BY position ASC LIMIT 1""").fetchone()
            conn.close()

            if not row:
                _queue_cond.wait(timeout=POLL_INTERVAL * 2)
                continue

            job_id, pos = row
            _mark_processing(job_id)

        # Submit outside the lock — pool.submit may block briefly
        _submit_worker(job_id)


def _mark_processing(job_id):
    conn = sqlite3.connect(str(USER_DB), timeout=5)
    conn.execute("UPDATE videos SET status='processing' WHERE job_id=?", (job_id,))
    conn.commit()
    conn.close()


def _submit_worker(job_id):
    global _running_jobs
    pool = _get_pool()
    future = pool.submit(_worker, job_id)
    future.add_done_callback(lambda f: _on_job_done(job_id, f))
    with _queue_cond:
        _running_jobs[job_id] = future


def _on_job_done(job_id, future):
    global _running_jobs
    exc = future.exception()
    status = "failed" if exc else "completed"
    completed = datetime.now().isoformat()

    conn = sqlite3.connect(str(USER_DB), timeout=5)
    conn.execute("UPDATE videos SET status=?, completed_at=? WHERE job_id=?",
                 (status, completed, job_id))
    conn.commit()
    conn.close()

    with _queue_cond:
        _running_jobs.pop(job_id, None)

    _wake_dispatcher()


# ── The Worker ─────────────────────────────────────────────────────────────
# This is the full build pipeline, extracted from do_build().
# No lock acquisition — the pool enforces MAX_CONCURRENT.

def _worker(job_id):
    """
    Full video build pipeline for job_id.
    Reads pipeline_config.json, runs voice→whisper→slides→captions→piano→logo,
    writes status.json at each step, updates DB on completion/failure.
    """
    work     = WORK_DIR / job_id
    img_dir  = work / "listing_src"
    cfg_file = work / "pipeline_config.json"
    log_file = Path("/var/log/review_server.log")

    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [Worker:{job_id}] {msg}"
        try:
            with open(log_file, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass
        print(line)

    def write_status(msg, done=False, video_path="", progress=0, **extra):
        try:
            vp = work / "videos.json"
            videos = []
            if vp.exists():
                with open(vp) as vf:
                    videos = json.load(vf).get("videos", [])
            existing = {}
            st_path = work / "status.json"
            if st_path.exists():
                try:
                    with open(st_path) as sf:
                        existing = json.load(sf)
                except Exception:
                    pass
            data = {
                "status": msg, "done": done, "video": video_path,
                "videos": videos, "job_id": job_id, "progress": progress,
            }
            for k in ("address", "price", "beds", "baths", "sqft", "images",
                      "model_name", "style_tags", "persona_core", "audience_hook",
                      "source_url", "voice", "script", "music"):
                if k in existing:
                    data[k] = existing[k]
            for k, v in extra.items():
                if k in ("address", "price", "beds", "baths", "sqft", "images",
                         "model_name", "style_tags", "persona_core", "audience_hook",
                         "source_url", "voice", "script", "music") and v:
                    data[k] = v
            with open(st_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log(f"write_status error: {e}")

    def run(cmd, timeout=300, cwd=None):
        """Like subprocess.run but with timeout."""
        return subprocess.run(cmd, timeout=timeout, cwd=cwd,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # ── ModelVideo bootstrap: model_url.txt present but no pipeline_config yet ──
    model_url_file = work / "model_url.txt"
    if model_url_file.exists() and not cfg_file.exists():
        log("ModelVideo job detected — running pipeline bootstrap")
        write_status("Bootstrapping ModelVideo pipeline...", progress=2)
        result = subprocess.run(
            [VENV, str(PIPELINE_V3 / "model_video" / "run_pipeline.py"),
             model_url_file.read_text().strip(),
             "--job-id", job_id, "--bootstrap-only"],
            timeout=300, cwd=str(WORK_DIR)
        )
        if result.returncode != 0:
            log(f"ModelVideo bootstrap failed: {result.stderr[:500]}")
            return
        # Remove the signal file so bootstrap only runs once
        try:
            model_url_file.unlink()
        except Exception:
            pass
        # Reload config after bootstrap
        try:
            cfg = json.loads(cfg_file.read_text())
        except Exception as e:
            log(f"ModelVideo bootstrap: pipeline_config.json still missing: {e}")
            return

        # Write ModelVideo extracted fields to status.json so the frontend can
        # start showing model name / script / tags / persona before the video is done.
        # These are read from pipeline_config.json which run_pipeline.py wrote.
        try:
            brief_path = work / "pipeline_brief.json"
            if brief_path.exists():
                brief = json.loads(brief_path.read_text())
                subject = brief.get("subject_snapshot", {})
                research = brief.get("research_summary", {})
                persona  = brief.get("persona_model", {})
            else:
                subject = {}
                research = {}
                persona  = {}

            write_status(
                "ModelVideo ready — building video...",
                progress=5,
                # Map pipeline_config fields to the names model_video.html expects
                address      = cfg.get("address", ""),
                script       = cfg.get("script", ""),
                music        = cfg.get("music", ""),
                voice        = cfg.get("voice", ""),
                # Extra fields from the brief (not in pipeline_config.json)
                model_name   = subject.get("primary_name", cfg.get("address", "")),
                style_tags   = research.get("style_tags", []),
                persona_core = persona.get("persona_core", ""),
                audience_hook= persona.get("audience_hook", ""),
                source_url   = research.get("source_url", ""),
            )
            log(f"ModelVideo status updated with extracted fields")
        except Exception as e:
            log(f"ModelVideo status update failed (non-fatal): {e}")

    try:
        if not cfg_file.exists():
            log(f"pipeline_config.json missing — cannot build")
            return

        cfg = json.loads(cfg_file.read_text())
    except Exception as e:
        log(f"Failed to load config: {e}")
        return

    # Extract config
    script        = cfg.get("script", "")
    voice         = cfg.get("voice", "Bella")
    music         = cfg.get("music", "none")
    addr          = cfg.get("address", "Listing")
    price         = cfg.get("price", "")
    beds          = cfg.get("beds", "")
    baths         = cfg.get("baths", "")
    sqft          = cfg.get("sqft", "")
    duration      = int(cfg.get("duration", 60) or 60)
    ratio         = cfg.get("ratio", "9:16")
    sel_indices   = cfg.get("selectedIndices", list(range(15)))
    cap_style     = cfg.get("captionStyle", {})
    logo_cfg      = cfg.get("logoPath", "")
    logo_size     = int(cfg.get("logoSize", 15))
    logo_position = cfg.get("logoPosition", "bottom-right")
    start_caption = cfg.get("startCaption", "")
    start_dur     = float(cfg.get("startDuration", 3))
    end_caption   = cfg.get("endCaption", "")
    end_dur       = float(cfg.get("endDuration", 4))
    source_job_id = cfg.get("sourceJobId", "")
    music_url = cfg.get("musicUrl", "").strip()
    motion_val = cfg.get("motion", "none")

    VOICE_MAP = {
        # edge-tts name, ElevenLabs voice ID
        "Bella":    ("en-US-JennyNeural",  "hpp4J3VqNfWAUOO0d1Us"),
        "Sarah":    ("en-US-AriaNeural",   "EXAVITQu4vr4xnSDxMaL"),
        "Roger":    ("en-US-RogerNeural",  "CwhRBWXzGAHq8TQ4Fs17"),
        "George":   ("en-US-AndrewNeural", "JBFqnCBsd6RMkjVDRZzb"),
        "Jessica":  ("en-US-AvaNeural",    "cgSgspJ2msm6clMCkdW9"),
        "Charlie":  ("en-US-BrianNeural",  "IKne3meq5aSn9XLyUdCD"),
        "Laura":    ("en-US-EmmaNeural",   "FGY2WhTYpPnrIDTdsKH5"),
        "Liam":     ("en-US-GuyNeural",    "TX3LPaxmHKxFdv7VOQHJ"),
        # legacy / fallback entries
        "Jenny":    ("en-US-JennyNeural",  "hpp4J3VqNfWAUOO0d1Us"),
        "Guy":      ("en-US-GuyNeural",    "TX3LPaxmHKxFdv7VOQHJ"),
        # Extra frontend voices
        "Harry":    ("en-GB-RyanNeural",    "SOYHLrjzK2X1ezoPC6cr"),
        "Will":     ("en-GB-ThomasNeural",  "bIHbv24MWmeRgasZH58o"),
        "Daniel":   ("en-GB-SoniaNeural",   "onwK4e9ZLuTAKqWW03F9"),
        "Adam":     ("en-US-ChristopherNeural","pNInz6obpgDQGcFmaJgB"),
    }
    edge_voice, elevenlabs_id = VOICE_MAP.get(voice, ("en-US-JennyNeural", "hpp4J3VqNfWAUOO0d1Us"))

    # Clean stale outputs
    for stale in ["video_final.mp4", "video_captioned.mp4", "video_wna.mp4",
                  "video_wna2.mp4", "video_with_audio.mp4", "video_with_intro_outro.mp4",
                  "intro_card_anim.mp4", "outro_card_anim.mp4", "video_logo.mp4"]:
        p = work / stale
        if p.exists():
            try:
                os.unlink(p)
                log(f"Cleaned stale: {stale}")
            except Exception as e:
                log(f"Could not clean {stale}: {e}")

    voice_m4a = work / "voice.m4a"
    try:
        # ── Voice generation ──────────────────────────────────────────────
        write_status("Generating voice...", progress=5,
                     address=addr, price=price, beds=beds, baths=baths, sqft=sqft,
                     images=len(list(img_dir.iterdir())) if img_dir.exists() else 0)
        log(f"Generating voice: {voice}")
        try:
            asyncio.run(edge_tts.Communicate(script, edge_voice).save(str(voice_m4a)))
            if voice_m4a.stat().st_size == 0:
                raise ValueError("empty file")
            log(f"Voice generated (edge_tts): {voice_m4a.stat().st_size} bytes")
        except Exception as e:
            log(f"edge_tts error ({e}), falling back to gTTS...")
            import gtts
            tmp_mp3 = str(voice_m4a).replace(".m4a", ".mp3")
            gtts.gTTS(script, lang="en").save(tmp_mp3)
            run(["ffmpeg", "-y", "-i", tmp_mp3, "-c:a", "aac", "-b:a", "192k", str(voice_m4a)],
                timeout=30, cwd=str(PIPELINE_V3))
            os.unlink(tmp_mp3)
            log(f"Voice generated (gTTS): {voice_m4a.stat().st_size} bytes")

        # ── Whisper transcription ─────────────────────────────────────────
        log(f"Transcribing {voice_m4a}")
        wj = work / "voice.json"
        try:
            r = run(
                [VENV, "-m", "whisper", str(voice_m4a),
                 "--model", "base", "--language", "English",
                 "--word_timestamps", "True", "--output_dir", str(work)],
                timeout=300, cwd=str(PIPELINE_V3))
            log(f"Whisper done: rc={r.returncode}")
        except Exception as e:
            log(f"Whisper error: {e}")
            r = None

        wdata = {}
        if wj.exists():
            try:
                with open(wj) as f:
                    wdata = json.load(f)
            except Exception:
                pass

        num_segs = len(wdata.get("segments", []))
        log(f"Whisper segments: {num_segs}")

        # Build SRT
        srt_path = work / "voice.srt"
        def _fmt(t):
            h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        with open(srt_path, "w") as f:
            word_id = 0
            for seg in wdata.get("segments", []):
                words = seg.get("words", [])
                if words:
                    for w in words:
                        wt = w["word"].strip()
                        if not wt:
                            continue
                        word_id += 1
                        w_start, w_end = float(w["start"]), float(w["end"])
                        f.write(f"{word_id}\n{_fmt(w_start)} --> {_fmt(w_end)}\n{wt}\n\n")
                else:
                    seg_id  = seg["id"] + 1
                    start_e = float(seg["start"])
                    end_e   = float(seg["end"])
                    text    = seg.get("text", "").strip()
                    f.write(f"{seg_id}\n{_fmt(start_e)} --> {_fmt(end_e)}\n{text}\n\n")

        # voice_transcript.json (used elsewhere)
        with open(work / "voice_transcript.json", "w") as f:
            json.dump({"segments": [{
                "structure_tags": [],
                "max_layout": {"width": 1920, "height": 1080, "left": 0, "top": 0},
                "time": {"start": seg["start"], "end": seg["end"]},
                "words": [{"word": w["word"].strip(), "start": w["start"], "end": w["end"]}
                          for w in seg.get("words", [])],
                "text": seg.get("text", "").strip()
            } for seg in wdata.get("segments", [])]}, f)

    except Exception as e:
        log(f"Voice/whisper error: {e}")

    try:
        # ── Intro card ─────────────────────────────────────────────────────
        intro_mp4 = ""
        if start_caption:
            try:
                intro_png  = str(work / "intro_card.png")
                intro_anim = str(work / "intro_card.mp4")
                run(["python3", "/opt/video_pipeline_v3/scripts/branding.py",
                     "--mode", "intro", "--text", start_caption, "--subtext", addr,
                     "--output", intro_png, "--ratio", ratio,
                     "--duration", str(start_dur)],
                    timeout=30, cwd="/opt/video_pipeline_v3")
                intro_mp4 = intro_anim
                log(f"Intro card: {intro_mp4}")
            except Exception as e:
                log(f"Intro error: {e}")

        # ── Outro card ─────────────────────────────────────────────────────
        outro_mp4 = ""
        if end_caption:
            try:
                outro_png  = str(work / "outro_card.png")
                outro_anim = str(work / "outro_card.mp4")
                run(["python3", "/opt/video_pipeline_v3/scripts/branding.py",
                     "--mode", "outro", "--text", end_caption, "--subtext", "",
                     "--output", outro_png, "--ratio", ratio,
                     "--duration", str(end_dur)],
                    timeout=30, cwd="/opt/video_pipeline_v3")
                outro_mp4 = outro_anim
                log(f"Outro card: {outro_mp4}")
            except Exception as e:
                log(f"Outro error: {e}")

        # ── Slides ─────────────────────────────────────────────────────────
        write_status("Building slides...", progress=25)
        r = run(
            [VENV, "/opt/video_pipeline_v3/scripts/build_vps.py",
             "--work", str(work), "--listing", str(img_dir),
             "--duration", str(duration), "--motion", motion_val, "--ratio", ratio],
            timeout=300, cwd="/opt/video_pipeline_v3")
        log(f"Slides built: exit={r.returncode}")
        if r.returncode != 0:
            write_status(f"Slides build failed (exit {r.returncode})", done=False, video_path="")
            log(f"Build aborted: build_vps.py failed: {r.stderr[-300:]}")
            _update_db(job_id, "failed")
            return

        # ── Concat intro + slides + outro ──────────────────────────────────
        video_with_intro_outro = str(work / "video_with_intro_outro.mp4")
        intro_anim = str(work / "intro_card_anim.mp4")
        outro_anim = str(work / "outro_card_anim.mp4")
        main_slides = str(work / "video_noaudio.mp4")

        clip_files = []
        if os.path.exists(intro_anim):
            clip_files.append(intro_anim)
        if os.path.exists(main_slides):
            clip_files.append(main_slides)
        if os.path.exists(outro_anim):
            clip_files.append(outro_anim)

        log(f"Concat: {len(clip_files)} clips")
        if len(clip_files) > 1:
            concat_list = str(work / "concat_list.txt")
            with open(concat_list, "w") as f:
                for cf in clip_files:
                    f.write(f"file '{cf}'\n")
            r_cat = run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                 "-c", "copy", video_with_intro_outro],
                timeout=120)
            log(f"Concat: exit={r_cat.returncode}")
        elif clip_files:
            video_with_intro_outro = clip_files[0]

        # ── Remux with audio ───────────────────────────────────────────────
        wna_with_intro = str(work / "video_wna2.mp4")
        if video_with_intro_outro != str(work / "video_wna.mp4"):
            dur_r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_with_intro_outro],
                capture_output=True, text=True)
            target_dur = float(dur_r.stdout.strip() or 0)
            r_mux = run(
                ["ffmpeg", "-y", "-i", video_with_intro_outro,
                 "-stream_loop", "-1", "-i", str(work / "video_wna.mp4"),
                 "-map", "0:v:0", "-map", "1:a", "-c:v", "copy",
                 "-af", f"apad=whole_dur={target_dur}", "-t", str(target_dur),
                 wna_with_intro],
                timeout=120)
            wna_with_intro_use = wna_with_intro if r_mux.returncode == 0 else str(work / "video_wna.mp4")
        else:
            wna_with_intro_use = str(work / "video_wna.mp4")

        # ── Captions (pycaps) ───────────────────────────────────────────────
        voice_srt = work / "voice.srt"
        captioned = str(work / "video_captioned.mp4")
        fs = cap_style.get("fontSize", 55)
        hc = "#" + cap_style.get("highlightColor", "FFFF00").lstrip("#")
        fc = cap_style.get("fontColor", "#FFFFFF")

        if not voice_srt.exists():
            log("WARNING: voice.srt missing — generating empty SRT")
            with open(voice_srt, "w") as f:
                f.write("1\n00:00:00,000 --> 00:00:00,001\n\n")

        # Guard: save prior final
        prior_final = work / "video_final.mp4"
        if prior_final.exists() and prior_final.stat().st_size > 1000:
            ts = datetime.now().strftime("%H%M%S")
            ts_video = f"video_{ts}.mp4"
            try:
                shutil.copy2(str(prior_final), work / ts_video)
                vp = work / "videos.json"
                vl = [ts_video]
                if vp.exists():
                    with open(vp) as vf:
                        vl = [ts_video] + json.load(vf).get("videos", [])
                with open(vp, "w") as vf:
                    json.dump({"videos": vl}, vf)
            except Exception as e:
                log(f"Could not store prior video: {e}")

        # Remove stale captioned/final
        for stale in [work / "video_captioned.mp4", work / "video_final.mp4",
                      work / "video_with_audio.mp4"]:
            if stale.exists():
                try:
                    os.unlink(stale)
                except Exception:
                    pass

        # pycaps render
        orig_cwd = os.getcwd()
        try:
            os.chdir(str(PIPELINE_V3))
            from typer.testing import CliRunner
            from pycaps.cli.render_cli import render_app
            r2 = CliRunner(mix_stderr=False).invoke(render_app, [
                "--input", str(wna_with_intro_use), "--output", str(captioned),
                "--template", "hype", "--transcript", str(voice_srt),
                "--transcript-format", "srt",
                "--style", f"word.font-size={fs}px",
                "--style", f"word-being-narrated.color={hc}!important",
                "--style", f"word-already-narrated.color={fc}!important",
                "--style", f"word.color={fc}!important",
                "--video-quality", "high",
            ])
            log(f"pycaps: exit={r2.exit_code if r2 else 1}")
        finally:
            os.chdir(orig_cwd)

        captions_ok = Path(captioned).exists() and Path(captioned).stat().st_size > 1000
        if not captions_ok:
            log("Caption fallback: copying wna_with_intro")
            shutil.copy2(wna_with_intro_use, captioned)

        # ── Logo overlay ───────────────────────────────────────────────────
        final_with_logo = str(work / "video_final.mp4")
        if logo_cfg and os.path.exists(logo_cfg):
            write_status("Adding logo...", progress=75)
            logo_pos_map = {
                "top-left":     "10:10",
                "top-right":    "W-w-10:10",
                "bottom-left":  "10:H-h-10",
                "bottom-right": "W-w-10:H-h-10",
            }
            r_logo = run(
                ["ffmpeg", "-y", "-i", captioned, "-i", logo_cfg,
                 "-filter_complex",
                 f"[1:v]scale=iw*{logo_size/100.0}:-1[logo];"
                 f"[0:v][logo]overlay={logo_pos_map.get(logo_position, 'W-w-10:H-h-10')}",
                 "-c:a", "copy", final_with_logo],
                timeout=120)
            log(f"Logo: exit={r_logo.returncode}")
            _save_history(work, captioned, "video_final.mp4")
        else:
            shutil.copy2(captioned, final_with_logo)

        # ── Piano / music background ─────────────────────────────────────────
        piano_keys = {
            "01_Relaxing_Piano_2min","02_Soothing_Melody_3min","03_Sound_Healing_3min",
            "04_Peaceful_Piano_3min","05_Calm_Relaxing_2min","06_Dawn_Scandinavianz_2min",
            "07_Calm_Vibes_3min","08_BatchBug_Wind_4min","09_Steffen_Daum_2min",
            "10_Lucjo_LucidDream_2min"
        }
        piano_mp3 = None
        if music_url:
            if 'youtube.com' in music_url or 'youtu.be' in music_url:
                yt_mp3 = str(work / "music.mp3")
                r_yt = subprocess.run(
                    ['/usr/local/bin/yt-dlp',
                     '--proxy', 'http://45.153.231.229:8080',
                     '-x', '--audio-format', 'mp3', '-o', yt_mp3, music_url],
                    capture_output=True, text=True, timeout=120
                )
                if r_yt.returncode == 0 and Path(yt_mp3).exists():
                    piano_mp3 = yt_mp3
                    log(f'YouTube audio extracted: {yt_mp3}')
                else:
                    log(f'YouTube download failed: {r_yt.stderr[-300:]}')
            elif music_url.startswith('http'):
                ext_mp3 = str(work / "music.mp3")
                r_ext = subprocess.run(
                    ['curl', '-L', '-o', ext_mp3, '--max-time', '60', music_url],
                    capture_output=True, text=True, timeout=70
                )
                if r_ext.returncode == 0 and Path(ext_mp3).exists():
                    piano_mp3 = ext_mp3
                    log(f'External audio downloaded: {ext_mp3}')
        if not piano_mp3:
            if music in piano_keys:
                piano_mp3 = f"/opt/video_pipeline_v3/music/{music}.mp3"
            else:
                piano_mp3 = ''  # unknown music key = no music

        ts_piano = datetime.now().strftime("%H%M%S")
        if Path(piano_mp3).exists():
            piano_video = f"video_piano_{job_id}_{ts_piano}.mp4"
            piano_out   = str(work / piano_video)
            r_piano = run(
                ["ffmpeg", "-y", "-i", piano_mp3, "-i", captioned,
                 "-filter_complex",
                 f"[0:a]volume=0.30,atrim=0:{duration},asetpts=PTS-STARTPTS[piano];"
                 f"[1:a][piano]amix=inputs=2:duration=first[aout]",
                 "-map", "1:v", "-map", "[aout]",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", piano_out],
                timeout=120)
            if r_piano.returncode == 0:
                ts_video = piano_video
                log(f"Piano added: {piano_video}")
            else:
                log(f"Piano error: {r_piano.stderr[-200:]}")
                ts_video = f"video_{ts_piano}.mp4"
                shutil.copy2(captioned, work / ts_video)
        else:
            ts_video = f"video_{ts_piano}.mp4"
            shutil.copy2(captioned, work / ts_video)

        _save_history(work, captioned, ts_video)

        # ── Done ───────────────────────────────────────────────────────────
        vp = work / "videos.json"
        videos_list = [ts_video]
        if vp.exists():
            with open(vp) as vf:
                videos_list = [ts_video] + json.load(vf).get("videos", [])
        with open(vp, "w") as vf:
            json.dump({"videos": videos_list}, vf)

        write_status("Complete!", done=True, video_path=ts_video, videos=videos_list, progress=100)
        _update_db(job_id, "completed")
        log(f"BUILD COMPLETE: {ts_video}")

    except Exception as e:
        import traceback
        log(f"BUILD ERROR: {e}\n{traceback.format_exc()}")
        try:
            write_status(f"Error: {e}", done=False, video_path="")
        except Exception:
            pass
        _update_db(job_id, "failed")


def _update_db(job_id, status, completed_at=None):
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
        print(f"[DB] update failed for {job_id}: {e}")


def _save_history(work, captioned, fallback_name):
    """Save a timestamped history copy of the video."""
    try:
        ts = datetime.now().strftime("%H%M%S")
        ts_video = f"video_{ts}.mp4"
        target = work / ts_video
        src = work / captioned if (work / captioned).exists() else work / fallback_name
        if src.exists() and src.stat().st_size > 1000:
            shutil.copy2(str(src), str(target))
        vp = work / "videos.json"
        vl = [ts_video]
        if vp.exists():
            with open(vp) as vf:
                vl = [ts_video] + json.load(vf).get("videos", [])
        with open(vp, "w") as vf:
            json.dump({"videos": vl}, vf)
    except Exception as e:
        print(f"[History] save failed: {e}")
