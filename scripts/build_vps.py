#!/usr/bin/env python3
"""build_vps.py -- optimized: pre-scale once, parallel Ken Burns, single-pass, voice verification."""
import subprocess, os, json, argparse, sys, glob, concurrent.futures

parser = argparse.ArgumentParser()
parser.add_argument('--work', required=True)
parser.add_argument('--listing', required=True)
parser.add_argument('--output', default=None)
parser.add_argument('--config', default=None)
parser.add_argument('--duration', type=float, default=30.0)
parser.add_argument('--ratio', default='16:9')
parser.add_argument('--effect', default='random')
parser.add_argument('--transition', default='smoothleft')
parser.add_argument('--images_per_slide', type=int, default=1)
parser.add_argument('--kb', default=None)
parser.add_argument('--music', default=None)
args = parser.parse_args()

WORK = args.work
LISTING = args.listing
OUT = args.output or os.path.join(WORK, 'video_final.mp4')
TOTAL_DUR = args.duration
SILENCE_END = 3.0
VOICE_DUR = TOTAL_DUR - SILENCE_END

os.makedirs(WORK, exist_ok=True)

W, H = (1080, 1920) if args.ratio == '9:16' else (1920, 1080)

images = sorted(
    glob.glob(os.path.join(LISTING, '*.[jp][pn][g]*')) +
    glob.glob(os.path.join(LISTING, '*.[jw][pe][g]*'))
)
images = [f for f in images if os.path.getsize(f) > 5000]
if not images:
    print('No images found in', LISTING)
    sys.exit(1)

try:
    kb = json.load(open('/opt/video_pipeline/kb_patterns.json'))
    PATTERNS = kb.get('patterns', [])
except:
    PATTERNS = []

NUM_SLIDES = max(1, len(images) // args.images_per_slide)
SLIDE_DUR = TOTAL_DUR / NUM_SLIDES
BIG = 2500  # 2x upscale for smooth Ken Burns (balance of quality vs speed)

def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def check_audio(path):
    """Return (has_audio, max_level_db) by running volumedetect."""
    r = run(['ffmpeg', '-i', path, '-af', 'volumedetect', '-f', 'null', '/dev/null'], timeout=30)
    for line in r.stderr.split('\n'):
        if 'max_volume' in line:
            try:
                db = float(line.split('max_volume:')[1].split('dB')[0].strip())
                return True, db
            except:
                pass
    return False, -999

# ── Pre-scale images to BIG resolution ───────────────────────────────────────
prescaled_dir = os.path.join(WORK, 'prescaled')
os.makedirs(prescaled_dir, exist_ok=True)

def prescale(img_path):
    out = os.path.join(prescaled_dir, os.path.basename(img_path))
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    r = run(['ffmpeg', '-y', '-i', img_path,
             '-vf', f'scale={BIG}:-2,setsar=1',
             '-c:v', 'mjpeg', '-q:v', '2',
             out], timeout=60)
    if r.returncode != 0:
        print(f"  prescale ERR: {r.stderr[-100:]}")
        return None
    return out

print(f"Pre-scaling {len(images)} images to {BIG}px...")
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    prescaled = list(ex.map(prescale, images))
prescaled = [p for p in prescaled if p]
print(f"  OK: {len(prescaled)}/{len(images)}")

img_groups = [prescaled[i:i + args.images_per_slide] for i in range(0, len(prescaled), args.images_per_slide)]

# ── Build slides ─────────────────────────────────────────────────────────────
slides = []

def make_vf(direction, zoom_target, n_frames, W, H, BIG):
    zr = abs(zoom_target - 1.0) / max(n_frames, 1) * 2
    zr = max(0.0003, min(zr, 0.001))  # slower = smoother
    if direction == 'zoom_in':
        ze = f"min(zoom+{zr:.4f},{zoom_target})"
        return (f"[0:v]zoompan=z='{ze}':d={n_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}[zp];"
                f"[zp]scale={W}:{H}:force_original_aspect_ratio=increase,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[out]")
    elif direction == 'zoom_out':
        ze = f"max({zoom_target}-zoom*{zr:.4f},1.0)"
        return (f"[0:v]zoompan=z='{ze}':d={n_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}[zp];"
                f"[zp]scale={W}:{H}:force_original_aspect_ratio=increase,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[out]")
    elif direction == 'pan_left':
        return (f"[0:v]zoompan=z=1:d={n_frames}:x='if(lte(x,0),{BIG},x-{BIG}/{n_frames})':y=0:s={W}x{H}[zp];"
                f"[zp]scale={W}:{H}:force_original_aspect_ratio=increase,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[out]")
    elif direction == 'pan_right':
        return (f"[0:v]zoompan=z=1:d={n_frames}:x='if(gte(x,iw-{BIG}),0,x+{BIG}/{n_frames})':y=0:s={W}x{H}[zp];"
                f"[zp]scale={W}:{H}:force_original_aspect_ratio=increase,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[out]")
    else:
        return f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[out]"

def build_slide(args_tuple):
    import random
    gi, group = args_tuple
    out_slide = os.path.join(WORK, f'slide_{gi:03d}.mp4')
    n_frames = max(25, int(SLIDE_DUR * 30))

    p = PATTERNS[gi % len(PATTERNS)] if PATTERNS else {}
    direction = p.get('zoom_dir', 'zoom_in')
    zoom_target = p.get('zoom', 1.0)

    if args.effect == 'random':
        direction = random.choice(['zoom_in', 'zoom_out', 'pan_left', 'pan_right'])
    elif args.effect == 'slow':
        direction = 'zoom_in'
        zoom_target = max(zoom_target, 1.3)

    inputs = []
    for img in group:
        inputs.extend(['-loop', '1', '-i', img])

    vf = make_vf(direction, zoom_target, n_frames, W, H, BIG)
    cmd = (['ffmpeg', '-y'] + inputs +
           ['-filter_complex', vf, '-map', '[out]',
            '-t', str(SLIDE_DUR),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30',
            out_slide])

    r = run(cmd, timeout=120)
    ok = r.returncode == 0 and os.path.exists(out_slide) and os.path.getsize(out_slide) > 5000
    info = f"{os.path.getsize(out_slide)//1024}KB" if ok else f"ERR: {r.stderr[-100:]}"
    return (gi, ok, direction, info)

print(f"Building {len(img_groups)} slides (parallel, 2 workers)...")
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    results = list(ex.map(build_slide, enumerate(img_groups)))

for gi, ok, direction, info in sorted(results):
    print(f"  slide {gi}: {'OK' if ok else 'FAIL'} | {direction} | {info}")
    if ok:
        slides.append(os.path.join(WORK, f'slide_{gi:03d}.mp4'))

slides.sort()
if not slides:
    print('No slides built'); sys.exit(1)
print(f"Built {len(slides)} slides")

# ── Concatenate ─────────────────────────────────────────────────────────────
noaudio = os.path.join(WORK, 'video_noaudio.mp4')
inputs = []
for s in slides:
    inputs.extend(['-i', s])

if len(slides) <= 6:
    TRANS = args.transition.lower().replace('smoothleft', 'hlslice').replace('fade', 'fade').replace('zoom', 'zoom').replace('blur', 'fade')
    XFADE = min(0.5, SLIDE_DUR / 4)
    if len(slides) == 2:
        fc = f'[0:v][1:v]xfade=transition={TRANS}:duration={XFADE}:offset={SLIDE_DUR - XFADE}[v]'
    else:
        fc, prev = '', '[0:v]'
        for i in range(1, len(slides)):
            offset = i * SLIDE_DUR - i * XFADE
            fc += f'{prev}[{i}:v]xfade=transition={TRANS}:duration={XFADE}:offset={offset:.2f}[v{i}];'
            prev = f'[v{i}]'
        fc = fc.rstrip(';') + '[outv]'
    cmd = (['ffmpeg', '-y'] + inputs + ['-filter_complex', fc, '-map', '[outv]',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30', noaudio])
else:
    cmd = (['ffmpeg', '-y'] + inputs +
            ['-filter_complex', f'concat=n={len(slides)}:v=1:a=0[outv]', '-map', '[outv]',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30', noaudio])

r = run(cmd, timeout=300)
sz = os.path.getsize(noaudio) if os.path.exists(noaudio) else 0
print(f"Concatenated: {sz//1024//1024}MB" + (f" ERR: {r.stderr[-100:]}" if r.returncode != 0 else ""))

# ── Verify/re-encode voice if needed ─────────────────────────────────────────
voice = os.path.join(WORK, 'voice.m4a')
has_voice = os.path.exists(voice)

if has_voice:
    has_audio, maxlevel = check_audio(voice)
    print(f"Voice check: has_audio={has_audio}, maxlevel={maxlevel:.1f}dB")
    if not has_audio or maxlevel < -50:
        print("  Voice file is silent/invalid — re-encoding...")
        r = run(['ffmpeg', '-y', '-i', voice,
                 '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                 os.path.join(WORK, 'voice_tmp.m4a')], timeout=30)
        if r.returncode == 0:
            os.replace(os.path.join(WORK, 'voice_tmp.m4a'), voice)
            print(f"  Re-encoded OK: {os.path.getsize(voice)//1024}KB")

# ── Audio mix ────────────────────────────────────────────────────────────────
wna = os.path.join(WORK, 'video_wna.mp4')
has_music = args.music and os.path.exists(args.music)

if has_voice or has_music:
    ac = ['ffmpeg', '-y', '-i', noaudio]
    filter_parts = []
    ai = 1

    if has_voice:
        # volume 3.0 for clear voice presence, apad to full duration
        ac.extend(['-i', voice])
        filter_parts.append(f'[{ai}:a]volume=3.0,apad=whole_dur={TOTAL_DUR}[vcmd]')
        ai += 1
    if has_music:
        ac.extend(['-i', args.music])
        # afade out at the end, moderate volume so voice cuts through
        filter_parts.append(f'[{ai}:a]volume=0.25,atrim=0:{TOTAL_DUR},asetpts=PTS-STARTPTS,afade=t=out:st={TOTAL_DUR-2}:d=2[music]')
        ai += 1

    if has_voice and has_music:
        # Voice dominant, music as background — use amix with voice twice for emphasis
        filter_parts.append('[vcmd][music]amix=inputs=2:duration=first:dropout_transition=2:d=1[audio]')
    elif has_voice:
        filter_parts.append('[vcmd]anull[audio]')
    elif has_music:
        filter_parts.append('[music]anull[audio]')

    filter_str = ';'.join(filter_parts)
    print(f"Audio mix: {filter_str[:80]}...")
    ac_cmd = ac + ['-filter_complex', filter_str,
                    '-map', '0:v', '-map', '[audio]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-t', str(TOTAL_DUR), wna]
    r = run(ac_cmd, timeout=120)
    if r.returncode == 0:
        print(f"Audio OK: {os.path.getsize(wna)//1024//1024}MB")
    else:
        print(f"Audio ERR: {r.stderr[-300:]}")
else:
    run(['ffmpeg', '-y', '-i', noaudio, '-c:v', 'copy', '-c:a', 'copy', '-movflags', '+faststart', wna])

print(f'Done: {OUT} ({os.path.getsize(OUT if os.path.exists(OUT) else wna)//1024//1024}MB)')
