#!/usr/bin/env python3
"""
3D Ken Burns v6 — Clean PyTorch grid_sample warp
zoom = crop/resize in pixel space
parallax = per-pixel offset in normalized grid space via grid_sample
"""

import argparse, time, warnings
warnings.filterwarnings('ignore')
import cv2, numpy as np, torch, torch.nn.functional as F
from pathlib import Path

TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0
MAX_DISP = 0.08   # max normalized disparity (near pixels shift ±0.08 in [-1,1])

_pipe = None

def get_pipe():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        print("Loading depth model...")
        _pipe = pipeline("depth-estimation", model="Intel/dpt-hybrid-midas")
        print("Depth model ready.")
    return _pipe

def estimate_depth(img_bgr):
    from PIL import Image
    pipe = get_pipe()
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    result = pipe(Image.fromarray(img_rgb))
    d = result["predicted_depth"].detach().cpu().numpy().squeeze()
    d = cv2.resize(d, (img_bgr.shape[1], img_bgr.shape[0]))
    if d.max() > d.min():
        d = (d - d.min()) / (d.max() - d.min() + 1e-8)
    return d.astype(np.float32)


def warp_frame(img_np, depth, cx, cy, zoom, panx, pany, out_size):
    """
    img_np: (H, W, 3) uint8
    depth: (H, W) float32, 0=far, 1=near
    cx, cy: camera look-at center (0-1)
    zoom: zoom factor (1.0 = full view, >1 = zoomed in)
    panx, pany: camera pan in normalized [-1,1] coords
    Returns: (out_size) uint8 frame
    """
    h, w = img_np.shape[:2]
    tw, th = out_size

    # Clamp zoom safely
    zoom = max(1.0, min(zoom, 1.6))

    # ── Zoom via crop+resize (pixel space) ──────────────────────────────
    zoomed_h = max(1, int(h / zoom))
    zoomed_w = max(1, int(w / zoom))
    cx_px = int(cx * w)
    cy_px = int(cy * h)
    x1 = max(0, min(cx_px - zoomed_w // 2, w - 1))
    y1 = max(0, min(cy_px - zoomed_h // 2, h - 1))
    x2 = max(x1 + 1, min(w, x1 + zoomed_w))
    y2 = max(y1 + 1, min(h, y1 + zoomed_h))

    img_crop = img_np[y1:y2, x1:x2].copy()

    # Convert to tensor and resize to output size
    img_t = torch.from_numpy(img_crop).permute(2, 0, 1).float().unsqueeze(0) / 255.0
    img_out = F.interpolate(img_t, size=(th, tw), mode='bilinear', align_corners=False).squeeze(0)

    # ── Build grid for parallax warp ───────────────────────────────────
    # grid coords in [-1, 1]: x rightward, y downward
    x = torch.linspace(-1, 1, tw)
    y = torch.linspace(-1, 1, th)
    yy, xx = torch.meshgrid(y, x, indexing='ij')  # both (th, tw)

    # Apply pan: shift the view
    gx = xx + panx
    gy = yy + pany

    # Apply depth-based disparity (parallax)
    # Near objects (depth≈1) shift opposite to pan direction more than far
    depth_small = cv2.resize(depth[y1:y2, x1:x2], (tw, th))
    depth_t = torch.from_numpy(depth_small).float()  # (th, tw)

    # Disparity direction: opposite to pan direction
    sign_x = 1.0 if panx >= 0 else -1.0
    sign_y = 1.0 if pany >= 0 else -1.0

    gx = gx + depth_t * MAX_DISP * sign_x
    gy = gy + depth_t * MAX_DISP * sign_y

    # Clip to valid grid range
    gx = gx.clamp(-1, 1)
    gy = gy.clamp(-1, 1)

    # Stack into (1, H, W, 2)
    grid = torch.stack([gx, gy], dim=2).unsqueeze(0)

    # Apply warp via grid_sample
    warped = F.grid_sample(
        img_out.unsqueeze(0),
        grid,
        mode='bilinear',
        padding_mode='border',
        align_corners=False
    ).squeeze(0).permute(1, 2, 0)

    result = (warped.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    return result


def build_video(image_paths, output_path, verbose=True):
    t_start = time.time()
    pipe = get_pipe()

    slides = []
    for i, path in enumerate(image_paths):
        img = cv2.imread(str(path))
        if img is None:
            continue
        img = cv2.resize(img, TARGET_SIZE)
        t0 = time.time()
        depth = estimate_depth(img)
        t1 = time.time()

        cx  = np.random.uniform(0.36, 0.64)
        cy  = np.random.uniform(0.36, 0.64)
        pdx = np.random.choice([-1, 1]) * np.random.uniform(0.003, 0.006)
        pdy = np.random.choice([-1, 1]) * np.random.uniform(0.001, 0.003)
        zspd = np.random.uniform(0.002, 0.004)

        if verbose:
            print(f"  [{i+1}/{len(image_paths)}] {Path(path).name} — depth: {t1-t0:.2f}s")

        slides.append({'img': img, 'depth': depth, 'cx': cx, 'cy': cy,
                       'pdx': pdx, 'pdy': pdy, 'zspd': zspd})

    if not slides:
        print("No images found!")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, FPS, TARGET_SIZE)

    n_frames = int(SLIDE_DURATION * FPS)
    fade = min(15, n_frames // 4)

    for si, slide in enumerate(slides):
        panx, pany, zoom = 0.0, 0.0, 1.0

        for fi in range(n_frames):
            panx += slide['pdx']
            pany += slide['pdy']
            zoom = min(zoom + slide['zspd'], 1.6)

            alpha = 0.0
            if si < len(slides) - 1 and fi >= n_frames - fade:
                alpha = (fi - (n_frames - fade)) / fade

            frame_a = warp_frame(slide['img'], slide['depth'],
                                  slide['cx'], slide['cy'],
                                  zoom, panx, pany, TARGET_SIZE)

            if alpha > 0 and si + 1 < len(slides):
                ns = slides[si + 1]
                frame_b = warp_frame(ns['img'], ns['depth'],
                                      ns['cx'], ns['cy'],
                                      1.0, 0.0, 0.0, TARGET_SIZE)
                frame_a = cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)

            writer.write(frame_a)

        elapsed = time.time() - t_start
        if verbose:
            print(f"  Slide {si+1}/{len(slides)} — {elapsed:.0f}s")

    writer.release()
    total = time.time() - t_start
    if verbose:
        print(f"\n✅ {output_path}  ({total:.1f}s, {len(slides)*SLIDE_DURATION:.0f}s video)")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--images', nargs='+', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--slide-duration', type=float, default=SLIDE_DURATION)
    args = p.parse_args()
    SLIDE_DURATION = args.slide_duration
    build_video(args.images, args.output)
