#!/usr/bin/env python3
"""
Text-to-Speech Generator
Priority: edge-tts (free, default) → 11 Labs (paid backup)
Always re-transcribes generated audio with Whisper for accurate caption sync.
Output: voice.m4a + voice_transcript.json (PyCaps-compatible)
"""
import asyncio, edge_tts, json, os, sys, shutil, hashlib, subprocess

VIDDIR = '/Users/meesha/openclaw/workspace/videos'
WORK = f'{VIDDIR}/corcoran_work'
OUT_FILE = f'{VIDDIR}/voice.m4a'
OUT_TRANSCRIPT = f'{VIDDIR}/voice_transcript.json'
PIPELINE_CFG = '/Users/meesha/openclaw/workspace/pipeline_config.json'

ELEVEN_API_KEY = 'sk_8fc024b5406b1e3ac437db283f36bb69a40a13b5e72c6041'
ELEVEN_URL = 'https://api.elevenlabs.io/v1/text-to-speech'

VOICE_MAP = {
    # edge-tts name, 11 Labs voice ID
    'Bella':    ('en-US-JennyNeural',    'hpp4J3VqNfWAUOO0d1Us'),
    'Sarah':    ('en-US-AriaNeural',     'EXAVITQu4vr4xnSDxMaL'),
    'Roger':    ('en-US-RogerNeural',    'CwhRBWXzGAHq8TQ4Fs17'),
    'George':   ('en-US-AndrewNeural',  'JBFqnCBsd6RMkjVDRZzb'),
    'Jessica':  ('en-US-AvaNeural',     'cgSgspJ2msm6clMCkdW9'),
    'Charlie':  ('en-US-BrianNeural',   'IKne3meq5aSn9XLyUdCD'),
    'Laura':    ('en-US-EmmaNeural',    'FGY2WhTYpPnrIDTdsKH5'),
    'Liam':     ('en-US-GuyNeural',     'TX3LPaxmHKxFdv7VOQHJ'),
}

def get_script_and_voice():
    voice_name = sys.argv[1] if len(sys.argv) > 1 else None
    script = sys.argv[2] if len(sys.argv) > 2 else None
    if not script:
        if os.path.exists(PIPELINE_CFG):
            cfg = json.load(open(PIPELINE_CFG))
            script = cfg.get('script', '')
        else:
            print("No script found. Provide as arg or ensure pipeline_config.json exists.")
            sys.exit(1)
    if not voice_name:
        voice_name = 'Bella'
        if os.path.exists(PIPELINE_CFG):
            voice_name = json.load(open(PIPELINE_CFG)).get('voice', 'Bella')
    return script, voice_name

def check_existing(script, voice_name):
    script_hash = hashlib.md5((script + voice_name).encode()).hexdigest()[:8]
    for fname in os.listdir(VIDDIR):
        if script_hash in fname and fname.endswith('.m4a'):
            return os.path.join(VIDDIR, fname)
    return None

def cache_copy(src, dst):
    if src != dst and os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"Cached voice: {dst}")

async def generate_edge_tts(script, edge_voice, out_file):
    print(f"[TTS] edge-tts: {edge_voice}")
    await edge_tts.Communicate(script, edge_voice).save(out_file)
    size = os.path.getsize(out_file)
    print(f"[TTS] Done: {size} bytes")

def generate_elevenlabs(script, eleven_id, out_file):
    import urllib.request
    print(f"[TTS] 11 Labs: {eleven_id}")
    data = json.dumps({
        'text': script,
        'model_id': 'eleven_flash_v2_5',
        'voice_settings': {'stability': 0.5, 'similarity_boost': 0.8}
    }).encode()
    req = urllib.request.Request(
        f'{ELEVEN_URL}/{eleven_id}',
        data=data,
        headers={'xi-api-key': ELEVEN_API_KEY, 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        with open(out_file, 'wb') as f:
            f.write(r.read())
    size = os.path.getsize(out_file)
    print(f"[TTS] Done: {size} bytes")

def run_whisper(audio_path, out_json):
    print(f"[WHISPER] Transcribing...")
    result = subprocess.run(
        ['whisper', audio_path,
         '--model', 'small',
         '--output_dir', WORK,
         '--output_format', 'json',
         '--word_timestamps', 'True',
         '--language', 'en'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[WHISPER] Warning: {result.stderr.strip()[-200:]}")
        return False
    whisper_json = f'{WORK}/voice.json'
    if not os.path.exists(whisper_json):
        print("[WHISPER] Output not found")
        return False
    # Use Whisper native JSON as-is (compatible with PyCaps --transcript-format whisper_json)
    shutil.copy2(whisper_json, out_json)
    wd = json.load(open(whisper_json))
    n_segs = len(wd.get('segments', []))
    n_words = sum(len(s.get('words', [])) for s in wd.get('segments', []))
    print(f"[WHISPER] Transcript: {out_json} ({n_segs} segments, {n_words} words)")
    return True

def main():
    script, voice_name = get_script_and_voice()
    if not script:
        sys.exit(1)

    os.makedirs(WORK, exist_ok=True)

    # Check cache
    cached = check_existing(script, voice_name)
    if cached and os.path.exists(cached):
        cache_copy(cached, OUT_FILE)
        cached_transcript = cached.replace('.m4a', '_transcript.json')
        if os.path.exists(cached_transcript):
            shutil.copy2(cached_transcript, OUT_TRANSCRIPT)
            print(f"[TTS] Cached transcript: {OUT_TRANSCRIPT}")
        else:
            run_whisper(OUT_FILE, OUT_TRANSCRIPT)
        return

    edge_voice, eleven_id = VOICE_MAP.get(voice_name, ('en-US-JennyNeural', 'hpp4J3VqNfWAUOO0d1Us'))
    print(f"[TTS] Generating: {voice_name} ({edge_voice})")

    generated = False
    try:
        asyncio.run(generate_edge_tts(script, edge_voice, OUT_FILE))
        generated = True
    except Exception as e:
        print(f"[TTS] edge-tts failed: {e}")
        try:
            generate_elevenlabs(script, eleven_id, OUT_FILE)
            generated = True
        except Exception as e2:
            print(f"[TTS] 11 Labs failed: {e2}")
            sys.exit(1)

    if generated:
        run_whisper(OUT_FILE, OUT_TRANSCRIPT)

if __name__ == '__main__':
    main()
