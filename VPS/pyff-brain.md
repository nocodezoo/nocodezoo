# pyff-brain — Vybord AI Cognitive Overlay
## Complete System Knowledge Base

---

## OVERVIEW

pyff-brain is the **AI cognitive brain overlay** for Vybord v3. It's a Next.js 16 (React 19) web app that provides:
1. A **neural brain map visualization** (`AIBrainMap.tsx`) — animated SVG showing Python + FFmpeg knowledge nodes
2. A **Vybord-specific brain panel** (`BrainPanel.tsx`) — knowledge nodes for the Vybord video pipeline
3. A **video creation interface** (`CreatePage.tsx` + `/create` route) — the main UI for generating videos

The brain panel is accessible via **Cmd/Ctrl+B** from anywhere in the app and shows Vybord-specific knowledge about the VPS pipeline, API endpoints, and code references.

---

## REPOSITORY

**URL:** https://github.com/nocodezoo/pyff-brain
**Branch:** main
**Stack:** Next.js 16.2.4, React 19.2.4, TypeScript 5, Tailwind CSS v4

### File Structure (pyff-brain repo)
```
pyff-brain/
├── app/
│   ├── page.tsx              → renders <AIBrainMap /> (home page)
│   ├── layout.tsx            → root layout, fonts (DM Sans + Playfair Display), dark bg (#0f1117)
│   ├── globals.css           → dark theme CSS variables, shared component styles
│   └── create/page.tsx       → renders <CreatePage /> + <BrainPanel />
├── components/
│   ├── AIBrainMap.tsx         → neural SVG brain map (Python/FFmpeg nodes, animated)
│   ├── BrainPanel.tsx         → Vybord knowledge overlay (Cmd+B), 8 knowledge nodes
│   └── CreatePage.tsx         → full video creation UI (client component, "use client")
├── public/                   → static assets (svgs)
├── package.json              → next 16.2.4, react 19.2.4
├── tsconfig.json             → path alias @/* → ./*
├── CLAUDE.md                 → @AGENTS.md
└── AGENTS.md                 → Next.js agent rules boilerplate
```

---

## FRONTEND: CreatePage.tsx (app/create)

Full video creation UI. Client component ("use client"). State: `VideoSettings` interface.

### VideoSettings Interface
```typescript
interface VideoSettings {
  voice: string;        // Edge-tts voice ID e.g. "CwhRBWXzGAHq8TQ4Fs17" (Roger)
  template: string;     // "word-focus" | "explosive" | "classic" | "minimalist" | "hype" | "retro-gaming"
  fontSize: number;      // 20-80 (slider)
  textColor: string;     // hex color e.g. "#FF69B4"
  bgColor: string;       // hex color e.g. "#000000"
  effect: string;       // "random" | "zoom" | "slow" | "vintage" | "glow" | "contrast"
  music: string;         // "none" | "upbeat" | "chill" | "cinematic" | "positive"
  musicUrl: string;      // URL string (custom music)
  transition: string;   // "fade" | "slide" | "zoom" | "none" | "blur" | "slideup"
  ratio: string;         // "16:9" | "9:16" | "1:1"
  duration: string;      // "15" | "30" | "45" | "60" seconds
  filter: string;       // image filter
  imagesPerSlide: number;
  motion: string;        // "cinematic" | "zoom" | etc.
  cta: string;          // call-to-action text
}
```

### Voices (12 options)
| ID (Edge TTS) | Display Name |
|---|---|
| CwhRBWXzGAHq8TQ4Fs17 | Roger |
| EXAVITQu4vr4xnSDxMaL | Sarah |
| FGY2WhTYpPnrIDTdsKH5 | Laura |
| SOYHLrjzK2X1ezoPC6cr | Harry |
| cgSgspJ2msm6clMCkdW9 | Jessica |
| IKne3meq5aSn9XLyUdCD | Charlie |
| JBFqnCBsd6RMkjVDRZzb | George |
| hpp4J3VqNfWAUOO0d1Us | Bella |
| TX3LPaxmHKxFdv7VOQHJ | Liam |
| bIHbv24MWmeRgasZH58o | Will |
| onwK4e9ZLuTAKqWW03F9 | Daniel |
| pNInz6obpgDQGcFmaJgB | Adam |

### Music Options (5 + none)
| Value | Label |
|---|---|
| none | 🔇 None |
| upbeat | 🎵 Upbeat |
| chill | 🎵 Chill |
| cinematic | 🎵 Cinematic |
| positive | 🎵 Positive |

**IMPORTANT BUG:** The frontend `music` values (`upbeat`, `chill`, `cinematic`, `positive`) DO NOT MATCH the VPS `MUSIC_MAP` keys (`ambient_piano`, `lofi_hip_hop`, `corporate_cinematic`, etc.). This is a **P0 mismatch** — when the frontend sends `music: "upbeat"`, the VPS `MUSIC_MAP.get("upbeat")` returns `None` and falls back to `ambient_piano.mp3`. The correct mapping would need either the frontend to send VPS-compatible keys or the VPS to map frontend keys to music files.

### Templates
`word-focus`, `explosive`, `classic`, `minimalist`, `hype`, `retro-gaming`

### Effects
`random`, `zoom`, `slow`, `vintage`, `glow`, `contrast`

### Transitions
`fade`, `slide`, `zoom`, `none`, `blur`, `slideup`

### Text Colors (8)
`#FF69B4`, `#FFFFFF`, `#FFFF00`, `#00FF88`, `#FF4444`, `#00CCFF`, `#FF9500`, `transparent`

### BG Colors (6)
`#000000`, `#1a1a2e`, `#2d1b4e`, `#0a1628`, `#1a0a0a`, `transparent`

### Image Handling
- URL paste or HTML paste
- CORS proxy: `/api/image-proxy?url=`
- Max 15 images per video
- Grid selection modal before submission

### Generation Flow
1. User fills form → clicks "Generate"
2. Images uploaded to `/api/upload` (multipart)
3. Job created via `/api/generate` (POST JSON with all settings)
4. Poll `/api/status/{jobId}` every 2s until `status: "completed"`
5. Video URL returned → displayed on page

---

## FRONTEND: BrainPanel.tsx

Toggle: **Cmd+B** or **Ctrl+B** from anywhere in the app.

### Vybord Knowledge Nodes (8 nodes)
| Node ID | Label | Category | CodeRef |
|---|---|---|---|
| vy-create | CREATE PAGE | vybord | components/CreatePage.tsx |
| vy-state | VIDEO STATE | vybord | components/CreatePage.tsx — VideoSettings state |
| vy-images | IMAGE HANDLER | vybord | components/CreatePage.tsx — Image Scan Modal |
| vy-voice | VOICE ENGINE | vybord | components/CreatePage.tsx — voice selection grid |
| vy-captions | CAPTION SYSTEM | vybord | components/CreatePage.tsx — Captions section |
| vy-submit | GENERATE PIPELINE | vybord | components/CreatePage.tsx — handleSubmit + useEffect status polling |
| vy-auth | AUTH HANDLER | vybord | app/auth/page.tsx |
| vy-api | API LAYER | vybord | app/api/*.ts |

Three view modes: `map`, `code`, `trace`

---

## FRONTEND: AIBrainMap.tsx

Neural brain map with animated SVG nodes.

### Python Branch Nodes (8)
`py-syntax`, `py-stdlib`, `py-fileio`, `py-errors`, `py-packages`, `py-subprocess`, `py-ds`, `py-perf`

### FFmpeg Branch Nodes (9)
`ff-cli`, `ff-vcodecs`, `ff-acodecs`, `ff-filters`, `ff-formats`, `ff-stream`, `ff-frames`, `ff-meta`, `ff-pyint`

### Special Nodes (3)
`sp-query` (QUERY INTERCEPTOR, gold), `sp-context` (CONTEXT MATCHER, purple), `sp-answer` (ANSWER SYNTHESIZER, cyan)

Search bar filters nodes in real-time. Click branch nodes to expand/collapse.

---

## VPS: Video Pipeline

**Location:** `/opt/video_pipeline_v3/`
**Server:** `review_server.py` (4132 lines) — runs on port **17073**
**Service:** `review_v3` (systemd)
**Music dir:** `/opt/video_pipeline_v3/music/`

### Key Files on VPS
| File | Lines | Purpose |
|---|---|---|
| review_server.py | 4132 | Main server — API routes, do_build, _mix_music |
| review.html | 969 | Dark-themed review page (v3.vybord.com/review/{jobId}) |
| test.html | 483 | Test/QA page |
| create.html | (large) | Create page (served statically by nginx) |
| app.html | | App page |
| auth.html | | Auth page |
| index.html | | Index/landing page |
| login.html | | Login page |
| music/*.mp3 | | Background music tracks |
| start_v3.sh | | Startup script (has secrets — redacted on GitHub) |

### Music Files (VPS)
```
/opt/video_pipeline_v3/music/
├── ambient_piano.mp3         (~288KB)
├── corporate_cinematic.mp3   (~310KB)
├── downtempo_nu_jazz.mp3    (~310KB)
├── electronic_techno.mp3    (~329KB)
├── lofi_hip_hop.mp3         (~356KB)
└── modern_jazz_lounge.mp3   (~316KB)
```

### Pipeline Flow (full)
```
User → review.html → POST /api/generate (JSON: address, script, voice, music, template, etc.)
     → Job created → returns {jobId}
     
     → POST /api/upload (multipart images)
     
     → Background: do_build(job_id)
         1. Read config from pipeline_config.json
         2. Generate script (AI or pre-written)
         3. Generate voice (edge-tts → voice.m4a)
         4. Transcribe voice → voice.srt (for captions)
         5. Download/process images
         6. Build slides → video_wna.mp4 (slides + voice, no captions)
         7. Burn captions → video_captioned.mp4 (slides + voice + pycaps)
         8. Mix music → video_music_*.mp4 (video_captioned + background music)
         9. Final output → video_final.mp4
         10. Update job status to "completed"
         
     → GET /api/status/{jobId} → {status, video_path, progress}
     
     → GET /review/{jobId} → renders review.html with video player
```

### API Endpoints (review_server.py)

| Method | Path | Purpose |
|---|---|---|
| GET | / | Index |
| GET | /review/{jobId} | Serve review.html with job context |
| GET | /test | Serve test.html |
| POST | /api/generate | Create new video job, returns {job_id} |
| POST | /api/upload | Upload images for a job |
| GET | /api/status/{jobId} | Poll job status + progress |
| POST | /api/build/{jobId} | Trigger rebuild of existing job |
| POST | /api/save | Save job settings |
| POST | /api/save-settings | Save settings (separate handler) |
| GET | /api/me | User auth check |
| POST | /api/auth/logout | Logout |
| POST | /api/script/generate/{jobId} | Generate script via AI |
| GET | /api/image-proxy | Proxy images (CORS workaround) |

### VOICE_MAP (VPS — review_server.py)
```python
VOICE_MAP = {
    # Simple names
    "Roger":    ("en-US-DylanNeural",   "Roger"),
    "Sarah":    ("en-US-JennyNeural",   "Sarah"),
    "Laura":    ("en-US-NancyNeural",   "Laura"),
    "Harry":    ("en-US-AndrewNeural",  "Harry"),
    "Jessica":  ("en-US-SaraNeural",    "Jessica"),
    "Charlie":  ("en-US-BenjaminNeural","Charlie"),
    "George":   ("en-US-ScottNeural",   "George"),
    "Bella":    ("en-US-AriaNeural",    "Bella"),
    "Liam":     ("en-US-BrandonNeural", "Liam"),
    "Will":     ("en-US-WilliamNeural", "Will"),
    "Daniel":   ("en-US-DavisNeural",   "Daniel"),
    "Adam":     ("en-US-JacobNeural",   "Adam"),
    # Plus lang:voicename entries
    ...
}
```

**VOICE BUG:** The frontend (pyff-brain CreatePage.tsx) sends voice IDs like `"CwhRBWXzGAHq8TQ4Fs17"` (Roger), but the VPS VOICE_MAP has keys like `"Roger"`. The `get_edge_voice()` function tries to match `"CwhRBWXzGAHq8TQ4Fs17"` → not found → tries `"en-US-CwhRBWXzGAHq8TQ4Fs17:Neural"` → not found → falls back to default. The frontend and VPS voice ID systems are **completely out of sync**.

### MUSIC_MAP (VPS — review_server.py)
```python
MUSIC_MAP = {
    'ambient_piano':        '/opt/video_pipeline_v3/music/ambient_piano.mp3',
    'corporate_cinematic':  '/opt/video_pipeline_v3/music/corporate_cinematic.mp3',
    'downtempo_nu_jazz':    '/opt/video_pipeline_v3/music/downtempo_nu_jazz.mp3',
    'electronic_techno':    '/opt/video_pipeline_v3/music/electronic_techno.mp3',
    'lofi_hip_hop':         '/opt/video_pipeline_v3/music/lofi_hip_hop.mp3',
    'modern_jazz_lounge':   '/opt/video_pipeline_v3/music/modern_jazz_lounge.mp3',
}
```

**MUSIC BUG:** Frontend sends `music: "upbeat"` | `"chill"` | `"cinematic"` | `"positive"` | `"none"`. VPS MUSIC_MAP has keys `ambient_piano`, `lofi_hip_hop`, etc. Mismatch means `MUSIC_MAP.get("upbeat")` → None → fallback to `ambient_piano`. **P0 priority fix: normalize the music key mapping.**

### Key Functions (review_server.py)

#### `do_build(job_id)` — line ~2364
Main build pipeline. Called asynchronously after job creation.
```python
def do_build(job_id):
    cfg = read_config()          # reads pipeline_config.json
    work = get_job_listing_dir(job_id)
    
    # Step 1: Generate/load script
    # Step 2: Generate voice (edge-tts or gTTS fallback)
    voice_m4a = work / 'voice.m4a'
    edge_voice = get_edge_voice(cfg.get('voice', 'Roger'))
    
    # Step 3: Transcribe for captions
    # Step 4: Build slides
    # Step 5: Burn captions (pycaps)
    captioned = work / 'video_captioned.mp4'
    
    # Step 6: Mix music
    ts_music = f'video_music_{final_ts}.mp4'
    music_out = str(work / ts_music)
    final_path = _mix_music(str(captioned), music_out, work, cfg.get('music', 'ambient_piano'))
```

#### `_mix_music(video_in, video_out, work, music_key)` — line ~693
```python
def _mix_music(video_in, video_out, work, music_key='ambient_piano'):
    music_src = MUSIC_MAP.get(music_key, MUSIC_MAP['ambient_piano'])
    # ffmpeg mix: loop music, trim to video length, fade out last 5s, 
    # mix with video audio at 30% volume → video_music_*.mp4
```

Working ffmpeg command (tested manually):
```bash
ffmpeg -i video_captioned.mp4 -i lofi_hip_hop.mp3 \
  -filter_complex "[1:a]aloop=loop=-1:size=2e+09,atrim=0:59.8,afade=t=out:st=55:d=5,volume=0.3[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k video_music.mp4
```

#### `get_edge_voice(voice_name)` — line ~642
Resolves voice name → Edge TTS voice ID. Tries direct match, then `lang:voicename` construction.

#### `run(cmd, cwd=None, timeout=600)` — line ~675
Wrapper around `subprocess.run()`. Used for all ffmpeg/video generation calls.

#### `log(msg)` — line ~665
Writes to `/dev/tty` (TTY of the running process). **Problem:** when running as systemd service, no TTY exists → logs are lost. Debug logging goes nowhere in daemon mode.

### The do_build Job Directory Structure
```
/tmp/rs_uploads/review_{jobId}/
├── pipeline_config.json      # main config (music, voice, template, etc.)
├── images/                  # downloaded listing images
├── voice.m4a               # generated voice audio
├── voice.srt               # transcribed captions
├── video_wna.mp4           # slides + voice (pre-captions)
├── video_captioned.mp4      # slides + voice + burned-in captions
├── video_music_*.mp4       # captioned + background music MIX
└── video_final.mp4         # final output (may be symlink to music version)
```

---

## ACTIVE BUGS & ISSUES

### P0: Music Not Applied to Generated Videos

**Symptoms:** Generated videos have no background music even when music is selected.

**Root Cause (partial):** The `music` field from frontend is saved to `pipeline_config.json` but:
1. The frontend music keys (`upbeat`, `chill`, `cinematic`, `positive`) **don't match** VPS `MUSIC_MAP` keys (`ambient_piano`, `lofi_hip_hop`, etc.)
2. Even when a matching key is sent, `_mix_music()` may fail silently

**Fixes applied (2026-04-23):**
- review_server.py generate handler (line ~2853): added `music`/`musicUrl` to pipeline_config.json
- review_server.py /api/save-settings/ handler (line ~3470): same
- review_server.py /api/save/ handler (line ~3550): same
- Debug logging added to `_mix_music()` and `run()`
- Service restarted with patches

**Remaining:** Need new test generation (post-restart) to verify music is actually being mixed.

### P0: Voice IDs Mismatch (Frontend vs VPS)

**Symptoms:** Voice selection in pyff-brain doesn't produce the expected voice.

**Root Cause:** Frontend sends `"CwhRBWXzGAHq8TQ4Fs17"` (Roger), but VPS VOICE_MAP has key `"Roger"`. `get_edge_voice()` doesn't recognize the frontend ID format.

### P1: Debug Logs Go to /dev/TTY (Lost in Daemon Mode)

`log()` writes to `/dev/tty`. When running under systemd, this is not captured. Debug logs from `_mix_music` and `run` are invisible.

**Fix needed:** Change `log()` to write to a file (e.g., `/tmp/v3_review.log`) or use Python's `logging` module.

### P1: Disk at 96.6% (74.2GB used)

VPS disk is nearly full. `/tmp/rs_uploads/` may have old job directories.

---

## PYFF-BRAIN GENERATION FLOW

The pyff-brain app (Next.js) does NOT directly generate videos. It:
1. Accepts user settings (voice, music, template, etc.)
2. POSTs to `/api/generate` on the **VPS** (v3.vybord.com)
3. Polls `/api/status/{jobId}` for completion
4. Displays the video URL returned

The actual video generation happens on the VPS in `review_server.py`'s `do_build()`.

---

## ENVIRONMENT & DEPLOYMENT

### VPS Info
- **Hostname:** vybord.com
- **Public IP:** 95.111.236.104
- **SSL domain:** v3.vybord.com (cert issued, Cloudflare proxied)
- **Nginx config:** `/etc/nginx/sites-available/v3.vybord.com`
- **Pipeline dir:** `/opt/video_pipeline_v3/` (NOT a git repo)
- **Review service:** `review_v3` (systemd, PID ~2968967)

### GitHub Upload
- Repo: `/opt/nocodezoo_repo/` (cloned from https://github.com/nocodezoo/nocodezoo)
- VPS pipeline uploaded to: `VPS/video_pipeline_v3/` (commit `744a92e`)
- **NOTE:** `start_v3.sh` has secrets — REDACTED on GitHub (placeholders used)

### Cloudflare
- AAAA records deleted (IPv6 disabled)
- Proxied (orange cloud) after cert issued
- `v3.vybord.com` → `95.111.236.104`

---

## QUICK REFERENCE

**Review page:** https://v3.vybord.com/review/{jobId}
**Test page:** https://v3.vybord.com/test
**Create page (static):** https://vybord.com/create

**Service management:**
```bash
systemctl restart review_v3    # restart review server
journalctl -u review_v3 --no-pager -n 100  # view logs
systemctl status review_v3       # check status
```

**Music test (manual):**
```bash
cd /tmp/rs_uploads/review_XXXXXXX
ffmpeg -i video_captioned.mp4 -i /opt/video_pipeline_v3/music/lofi_hip_hop.mp3 \
  -filter_complex "[1:a]aloop=loop=-1:size=2e+09,atrim=0:59.8,afade=t=out:st=55:d=5,volume=0.3[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k video_music_test.mp4
```

**Check video audio:**
```bash
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,bit_rate -of csv=p=0 video_final.mp4
```

---

## LAST UPDATED

2026-04-23 — Initial comprehensive brain created from live VPS inspection + pyff-brain repo clone.
