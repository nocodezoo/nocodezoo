#!/usr/bin/env python3
"""
3D Ken Burns — Per-pixel depth warp (v4, fixed)
Per-pixel parallax: near pixels shift more than far pixels.
Pure numpy CPU warp — no CUDA needed.

Speed: ~48s for 30s video (1.6x realtime) on 4-vCPU VPS
"""

import argparse
import time
import warnings
warnings.filterwarnings('ignore')

import cv2
import numpy as np
import torch
from pathlib import Path

TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0
MAX_SHIFT_X = 0.10  # max horizontal shift (fraction of width)
MAX_SHIFT_Y = 0.05  # max vertical shift (fraction of height)
ZOOM_SPEED  = 0.003  # zoom-in per frame

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
    pil_img = Image.fromarray(img_rgb)
    result = pipe(pil_img)
    depth = result["predicted_depth"].detach().cpu().numpy().squeeze()
    depth = cv2.resize(depth, (img_bgr.shape[1], img_bgr.shape[0]))
    if depth.max() > depth.min():
        depth = (depth - depth.min()) / (depth.max() - depth.min())
    return depth.astype(np.float32)


def build_camera_path(n_frames, cx, cy, zoom_start, zoom_speed, panx_dir, pany_dir):
    """
    Compute camera path for n_frames.
    Returns zoom_factor and pan_offset arrays.
    """
    zooms  = []
    panxs  = []
    panys  = []
    z = zoom_start
    px = 0.0
    py = 0.0
    for _ in range(n_frames):
        zooms.append(z)
        panxs.append(px)
        panys.append(py)
        z  += zoom_speed
        px += panx_dir
        py += pany_dir
    return np.array(zooms), np.array(panxs), np.array(panys)


def warp_frame(img, depth, cx, cy, zoom_f, panx, pany, out_size):
    """
    Per-pixel depth-based parallax warp for one frame.
    - cx, cy: camera look-at center (0-1 fraction)
    - zoom_f: zoom factor (1.0 = full image, >1 = zoomed in)
    - panx, pany: accumulated pan offset in pixels
    - depth: (H,W) array, 0=far, 1=near
    Returns warped frame at out_size.
    """
    h, w = img.shape[:2]
    tw, th = out_size

    # Camera center in pixel coords
    cam_cx = cx * w
    cam_cy = cy * h

    # Zoom: crop then resize
    crop_w = w / zoom_f
    crop_h = h / zoom_f
    src_x1 = max(0, cam_cx - crop_w / 2 + panx)
    src_y1 = max(0, cam_cy - crop_h / 2 + pany)
    src_x2 = min(w, src_x1 + crop_w)
    src_y2 = min(h, src_y1 + crop_h)

    if src_x2 <= src_x1 or src_y2 <= src_y1:
        return np.zeros((th, tw, 3), dtype=np.uint8)

    # Per-pixel disparity from depth
    # Near (depth≈1) → shift more; Far (depth≈0) → shift less
    disp_x = depth * MAX_SHIFT_X * w   # (H, W)
    disp_y = depth * MAX_SHIFT_Y * h

    # Build coordinate grids at FULL src resolution
    # For each output pixel, where do we sample in the source?
    #out_j, out_i = np.meshgrid(range(th), range(tw), indexing='ij')
    # Map output pixel (i,j) to source
    src_w = src_x2 - src_x1
    src_h = src_y2 - src_y1

    # Output grid in source-crop space
    i_out = np.linspace(0, src_w, tw)  # (tw,)
    j_out = np.linspace(0, src_h, th)  # (th,)
    jj, ii = np.meshgrid(j_out, i_out, indexing='ij')  # (th, tw) each

    # Source crop top-left
    sx0 = src_x1
    sy0 = src_y1

    # Source coords for each output pixel
    src_i = sx0 + ii  # column in source image
    src_j = sy0 + jj  # row in source image

    # Apply depth-based disparity
    # Sample disparity at src coords via bilinear interp
    disp_xi = _bilinear_sample(disp_x, src_j, src_i, h, w)
    disp_yi = _bilinear_sample(disp_y, src_j, src_i, h, w)

    # Shift: near (high depth) gets extra shift = parallax
    # Camera is panning in direction (panx, pany), so near objects
    # appear to move faster in opposite direction
    shift_xi = disp_xi * (panx / (abs(panx) + 1e-8))
    shift_yi = disp_yi * (pany / (abs(pany) + 1e-8))

    warp_i = src_i - shift_xi
    warp_j = src_j - shift_yi

    # Clip to source bounds
    warp_i = np.clip(warp_i, 0, w - 1.001)
    warp_j = np.clip(warp_j, 0, h - 1.001)

    # cv2.remap: map_x (warp_i) and map_y (warp_j)
    warped = cv2.remap(img, warp_i.astype(np.float32), warp_j.astype(np.float32), cv2.INTER_LINEAR)
    return warped


def _bilinear_sample(img, y, x, h, w):
    """Bilinear sample img at coordinates (y, x). img is (H, W)."""
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)

    dx = (x - x0).astype(np.float32)
    dy = (y - y0).astype(np.float32)

    v00 = img[y0, x0].astype(np.float32)
    v10 = img[y0, x1].astype(np.float32)
    v01 = img[y1, x0].astype(np.float32)
    v11 = img[y1, x1].astype(np.float32)

    return (v00 * (1 - dx) * (1 - dy) +
            v10 * dx       * (1 - dy) +
            v01 * (1 - dx) * dy       +
            v11 * dx       * dy)


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

        cx  = np.random.uniform(0.35, 0.65)
        cy  = np.random.uniform(0.35, 0.65)
        pdx = np.random.choice([-1, 1]) * np.random.uniform(0.004, 0.008)
        pdy = np.random.choice([-1, 1]) * np.random.uniform(0.001, 0.004)
        zspd = np.random.uniform(0.0025, 0.004)

        if verbose:
            print(f"  [{i+1}/{len(image_paths)}] {Path(path).name} — depth: {t1-t0:.2f}s")

        slides.append({
            'img': img, 'depth': depth,
            'cx': cx, 'cy': cy,
            'pdx': pdx, 'pdy': pdy,
            'zspd': zspd,
        })

    if not slides:
        print("No images found!")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, FPS, TARGET_SIZE)

    n_frames = int(SLIDE_DURATION * FPS)
    fade_frames = min(15, n_frames // 4)

    for si, slide in enumerate(slides):
        panx = 0.0
        pany = 0.0
        zoom = 1.0

        for fi in range(n_frames):
            # Accumulate camera
            panx += slide['pdx']
            pany += slide['pdy']
            zoom += slide['zspd']

            alpha = 0.0
            if si < len(slides) - 1 and fi >= n_frames - fade_frames:
                alpha = (fi - (n_frames - fade_frames)) / fade_frames

            frame_a = warp_frame(
                slide['img'], slide['depth'],
                slide['cx'], slide['cy'],
                zoom, panx, pany, TARGET_SIZE
            )

            if alpha > 0 and si + 1 < len(slides):
                ns = slides[si + 1]
                frame_b = warp_frame(
                    ns['img'], ns['depth'],
                    ns['cx'], ns['cy'],
                    1.0, 0.0, 0.0, TARGET_SIZE
                )
                frame_a = cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)

            writer.write(frame_a)

        elapsed = time.time() - t_start
        if verbose:
            print(f"  Slide {si+1}/{len(slides)} — {elapsed:.0f}s")

    writer.release()
    total = time.time() - t_start
    if verbose:
        print(f"\n✅ {output_path}")
        print(f"   {len(slides)} slides × {SLIDE_DURATION}s = {len(slides)*SLIDE_DURATION:.0f}s")
        print(f"   Build: {total:.1f}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--slide-duration', type=float, default=SLIDE_DURATION)
    args = parser.parse_args()
    SLIDE_DURATION = args.slide_duration
    build_video(args.images, args.output)
