#!/usr/bin/env python3
"""
branding.py — Generate styled intro/outro text cards and overlay logos.
Uses PIL for image generation, ffmpeg for animations.
"""
import os, sys, subprocess, json
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_PATH = '/opt/video_pipeline/hype-yellow/komika.ttf'
FONT_FALLBACK = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT = FONT_PATH if os.path.exists(FONT_PATH) else FONT_FALLBACK

def get_font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except:
        return ImageFont.load_default()

def generate_text_card(text, subtext='', bg_color=(10, 10, 30), text_color=(255, 240, 80),
                       glow_color=(255, 200, 0), fname_out='/tmp/card.png',
                       w=1080, h=1920, font_size=85):
    """Generate a styled text card image with glow effect."""
    img = Image.new('RGB', (w, h), bg_color)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2

    font = get_font(font_size)
    sub_font = get_font(font_size // 2)

    # Compute text position
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    tx, ty = cx - tw//2, cy - th//2 - (30 if subtext else 0)

    # Glow (multiple blur passes for soft glow)
    for radius in [20, 12, 6]:
        glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for bx in range(-20, 21, 4):
            for by in range(-20, 21, 4):
                dist = (bx**2 + by**2) ** 0.5
                if dist <= 20:
                    alpha = int(80 * (1 - dist/20))
                    gd.text((tx + bx, ty + by), text, font=font, fill=(*glow_color, alpha))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=radius))
        img_rgba = img.convert('RGBA')
        img_rgba = Image.alpha_composite(img_rgba, glow)
        img = img_rgba.convert('RGB')
        d = ImageDraw.Draw(img)

    # Black stroke
    for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(-4,0),(4,0),(0,-4),(0,4)]:
        d.text((tx + dx, ty + dy), text, font=font, fill=(0, 0, 0))
    # Main text
    d.text((tx, ty), text, font=font, fill=text_color)

    # Subtext
    if subtext:
        bbox2 = d.textbbox((0, 0), subtext, font=sub_font)
        tw2 = bbox2[2]-bbox2[0]
        sy = ty + th + 20
        d.text((cx - tw2//2, sy), subtext, font=sub_font, fill=(160, 160, 160))

    img.save(fname_out)
    return fname_out


def animate_card(card_png, output_mp4, duration=3.0, fade_start=0.3, fade_end=0.5):
    """Convert a still image to a short video with fade in/out using ffmpeg."""
    fade_out_start = duration - fade_end
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', card_png,
        '-vf', f'fade=in:st=0:d={fade_start},fade=out:st={fade_out_start}:d={fade_end}',
        '-t', str(duration), '-r', '30',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-an', output_mp4
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR animating card: {r.stderr[-200:]}")
        return None
    return output_mp4


LOGO_POSITIONS = {
    'top-left':      '10:10',
    'top-right':     'W-w-10:10',
    'bottom-left':   '10:H-h-10',
    'bottom-right':  'W-w-10:H-h-10',
}

def overlay_logo(video_in, logo_path, position='bottom-right', logo_size_pct=15, video_out=None):
    """Overlay a PNG logo onto a video at the specified corner."""
    if not os.path.exists(logo_path):
        print(f"Logo not found: {logo_path}")
        return None

    if video_out is None:
        video_out = video_in.replace('.mp4', '_logo.mp4')

    scale = logo_size_pct / 100.0
    pos_str = LOGO_POSITIONS.get(position, LOGO_POSITIONS['bottom-right'])

    cmd = [
        'ffmpeg', '-y',
        '-i', video_in,
        '-i', logo_path,
        '-filter_complex',
        f'[1:v]scale=iw*{scale}:-1[logo];[0:v][logo]overlay={pos_str}',
        '-c:a', 'copy',
        video_out
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR overlaying logo: {r.stderr[-300:]}")
        return None
    print(f"Logo overlay done: {video_out}")
    return video_out


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['intro', 'outro', 'logo-overlay'], required=True)
    p.add_argument('--text', default='')
    p.add_argument('--subtext', default='')
    p.add_argument('--output', default='/tmp/card.png')
    p.add_argument('--video-in', default='')
    p.add_argument('--video-out', default='')
    p.add_argument('--logo', default='')
    p.add_argument('--logo-position', default='bottom-right')
    p.add_argument('--logo-size', type=int, default=15)
    p.add_argument('--duration', type=float, default=3.0)
    p.add_argument('--ratio', default='9:16')
    args = p.parse_args()

    w, h = (1080, 1920) if args.ratio == '9:16' else (1920, 1080)

    if args.mode == 'intro':
        generate_text_card(args.text, args.subtext, fname_out=args.output, w=w, h=h)
        animate_card(args.output, args.output.replace('.png', '_anim.mp4'), duration=args.duration)
        print(f"Intro card: {args.output}")

    elif args.mode == 'outro':
        generate_text_card(args.text, args.subtext, fname_out=args.output, w=w, h=h)
        animate_card(args.output, args.output.replace('.png', '_anim.mp4'), duration=args.duration)
        print(f"Outro card: {args.output}")

    elif args.mode == 'logo-overlay':
        result = overlay_logo(args.video_in, args.logo, args.logo_position, args.logo_size, args.video_out)
        print(f"Logo overlay: {result}")
