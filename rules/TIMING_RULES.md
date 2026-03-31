# Video Timing Rules

## Duration
- **Always 60 seconds total**
- Voiceover: **55 seconds**
- Music-only ending: **5 seconds** (no voice, just music)
- Music fades out during the final 5 seconds

## Slide Timing (15 images)
- 15 images × ~4.5s per slide = 64.5s → with 7 crossfades (0.5s each) = **60s exactly**
- Regular slides: 4.5s each
- Last slide: extended to fill remaining time to hit exactly 60s
- 0.5s crossfade transitions between consecutive slides

## Audio Timing
- Voice: exactly 55s
- Music: starts at 0s alongside voice, continues through, fades out in final 5s
- Music fade: `afade=t=out:st=55:d=5` (fade from 55s to 60s)
- Voice volume: 150%, Music volume: 50%

## Narration Rules
- Script must fit within 55 seconds of speech
- Warm CTA closing **always appended** (part of the 55s)
- End the script on a positive, happy note — no abrupt endings
- Avoid trailing "...", ellipses, or incomplete thoughts at the end

## Happy Ending Rule
The final sentence of every script must be a warm, inviting closing that feels like a complete tour send-off. Example:
*"We'd love to tell you more about this beautiful property. Reach out anytime — we're here to help."*

## KB Patterns
- Slides 01-14: 4.5s each
- Slide 15: extended to 9.5s (fills the 60s total)
- All 15 slides: unique Ken Burns per slide from kb_patterns.json
