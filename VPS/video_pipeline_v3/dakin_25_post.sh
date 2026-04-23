#!/bin/bash
set -e
cd /opt/video_pipeline_v3

WORK=/opt/video_pipeline_v3/dakin_25_kb
OUT=/opt/video_pipeline_v3
MUSIC=/opt/video_pipeline_v3/lofi_hip_hop.mp3
SCRIPT="Beautiful vintage two-flat in the heart of Lakeview, just steps from Wrigley Field. This mint-condition property offers stunning woodwork, a spacious owner's duplex-down with three fireplaces, and a fully finished lower level. The second unit provides excellent rental income. Three-car parking pad included."
VOICE="en-US-RogerNeural"
N=25

echo "=== Step 1: Trim each clip to 3 seconds ==="
for i in $(seq -f "%03g" 1 $N); do
  ffmpeg -y -i ${WORK}/out_${i}.mp4 -t 3 -c:v libx264 -preset fast -an ${WORK}/trim_${i}.mp4 2>/dev/null
  echo "Trimmed $i"
done

echo "=== Step 2: Concatenate all clips ==="
cat > ${WORK}/concat.txt << 'CONCAT_EOF'
CONCAT_EOF
for i in $(seq -f "%03g" 1 $N); do
  echo "file '${WORK}/trim_${i}.mp4'" >> ${WORK}/concat.txt
done
ffmpeg -y -f concat -safe 0 -i ${WORK}/concat.txt -c:v libx264 -preset fast ${OUT}/dakin_25_raw.mp4
echo "Concatenated: $(ffprobe -v quiet -show_entries format=duration -of csv=p=0 ${OUT}/dakin_25_raw.mp4)s"

echo "=== Step 3: Generate voiceover SRT + audio ==="
mkdir -p /tmp/kenburns_post
edge-tts --voice "$VOICE" --text "$SCRIPT" --write-media /tmp/kenburns_post/voice.mp3 --write-subtitles /tmp/kenburns_post/voice.srt 2>/dev/null
ffmpeg -y -i /tmp/kenburns_post/voice.mp3 -vn -ar 44100 -ac 2 /tmp/kenburns_post/voice.wav 2>/dev/null

echo "=== Step 4: Loop music to 75s ==="
DURATION=75
ffmpeg -y -streamloop 1 -i $MUSIC -t $DURATION -c:a copy ${OUT}/music_loop.mp3 2>/dev/null

echo "=== Step 5: Mix voice + music ==="
ffmpeg -y -i ${OUT}/music_loop.mp3 -i /tmp/kenburns_post/voice.wav -filter_complex "[0:a]volume=0.25[bg];[1:a]volume=1.0[vo];[bg][vo]amix=inputs=2:duration=first[aout]" -map "[aout]" ${OUT}/audio_mix.mp3 2>/dev/null

echo "=== Step 6: Burn captions via pycaps ==="
/opt/venv/bin/python3 -c "
import asyncio, json, sys
sys.path.insert(0, '/opt/video_pipeline_v3/scripts')
from burn_captions import burn_captions

async def main():
    result = await burn_captions(
        video_path='${OUT}/dakin_25_raw.mp4',
        srt_path='/tmp/kenburns_post/voice.srt',
        output_path='${OUT}/dakin_25_capped.mp4',
        font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        style='hype',
        voice='Roger'
    )
    print(result)

asyncio.run(main())
"
echo "Captions burned"

echo "=== Step 7: Combine video + audio ==="
ffmpeg -y -i ${OUT}/dakin_25_capped.mp4 -i ${OUT}/audio_mix.mp3 -c:v copy -c:a aac -b:a 192k -shortest ${OUT}/dakin_25_final.mp4 2>/dev/null

echo "=== Step 8: Verify ==="
ffprobe -v quiet -show_entries format=duration,size -of csv=p=0 ${OUT}/dakin_25_final.mp4
ls -lh ${OUT}/dakin_25_final.mp4
