#!/usr/bin/env python3
"""
3D Ken Burns v3 — Per-pixel depth-based warp
Uses Intel/dpt-hybrid-midas for depth, then applies per-pixel
disparity shift to create genuine parallax without layer seams.

Each pixel shifts by: shift = depth_value * max_shift * direction
Near objects shift more than far objects → natural parallax.
"""

import argparse
import time
import warnings
warnings.filterwarnings('ignore')

import cv2
import numpy as np
import torch
from pathlib import Path

DEVICE = 'cpu'
TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0
OUTPUT_FPS = 30
MAX_DISPARITY = 0.18  # max pixel shift as fraction of width (near objects)


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
    """Returns disparity map (H, W) as numpy array, 0-1, higher=nearer."""
    pipe = get_pipe()
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    from PIL import Image
    pil_img = Image.fromarray(img_rgb)
    result = pipe(pil_img)
    depth = result["predicted_depth"].detach().cpu().numpy()
    if depth.ndim == 3:
        depth = depth.squeeze()
    # Resize to full image size
    depth = cv2.resize(depth, (img_bgr.shape[1], img_bgr.shape[0]))
    # Normalize to 0-1
    if depth.max() > depth.min():
        depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
    return depth.astype(np.float32)

def compute_frame(img, depth, cx, cy, zoom_acc, panx, pany, out_size):
    """
    Per-pixel depth-based warp for one frame.
    - zoom_acc: current zoom factor (1.0 = no zoom, 1.5 = 50% zoom in)
    - panx, pany: accumulated pan offsets (fraction of image size)
    - Disparity: near (depth≈1) shifts more than far (depth≈0)
    Returns warped frame at out_size.
    """
    h, w = img.shape[:2]
    tw, th = out_size

    # Accumulate zoom: dolly-in over the slide duration
    zoom = zoom_acc
    crop_w = w / zoom
    crop_h = h / zoom

    # Camera center in original image coords
    cam_x = cx * w + panx * w
    cam_y = cy * h + pany * h

    # Source crop bounds
    src_x1 = max(0, cam_x - crop_w / 2)
    src_y1 = max(0, cam_y - crop_h / 2)
    src_x2 = min(w, cam_x + crop_w / 2)
    src_y2 = min(h, cam_y + crop_h / 2)
    src_w = src_x2 - src_x1
    src_h = src_y2 - src_y1

    if src_w < 10 or src_h < 10:
        return np.zeros((th, tw, 3), dtype=np.uint8)

    # Build output meshgrid (in source crop coordinates)
    out_y, out_x = np.meshgrid(
        np.linspace(src_y1, src_y2, th),
        np.linspace(src_x1, src_x2, tw),
        indexing='ij'
    )
    # out_x, out_y are both (th, tw)

    # Per-pixel disparity: depth * max_shift * direction
    # depth is (h, w), we need it at (th, tw)
    depth_s = cv2.resize(depth, (tw, th))
    disparity_map = depth_s * MAX_DISPARITY * w

    # Horizontal and vertical shift (opposite to camera pan direction)
    shift_x = -panx * w * 0.5  # counter-pan for parallax
    shift_y = -pany * h * 0.5

    # Apply disparity to source coordinates
    # Near objects (high depth) get extra shift → parallax
    warp_x = out_x - shift_x - disparity_map * (panx + 0.001)
    warp_y = out_y - shift_y - disparity_map * (pany + 0.001)

    # Clip to source bounds
    warp_x = np.clip(warp_x, 0, w - 1)
    warp_y = np.clip(warp_y, 0, h - 1)

    # Remap (bilinear via OpenCV)
    map_x = warp_x.astype(np.float32)
    map_y = warp_y.astype(np.float32)
    warped = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR)

    return warped.astype(np.uint8)


def build_video(image_paths, output_path, verbose=True):
    t_start = time.time()
    pipe = get_pipe()

    # Pre-load images and compute depth
    slides = []
    for i, path in enumerate(image_paths):
        img = cv2.imread(str(path))
        if img is None:
            continue
        img = cv2.resize(img, TARGET_SIZE)

        t0 = time.time()
        depth = estimate_depth(img)
        t1 = time.time()

        # Random camera path
        cx  = np.random.uniform(0.35, 0.65)
        cy  = np.random.uniform(0.35, 0.65)
        pan_dir_x = np.random.choice([-1, 1]) * np.random.uniform(0.01, 0.03)
        pan_dir_y = np.random.choice([-1, 1]) * np.random.uniform(0.005, 0.015)
        zoom_speed = np.random.uniform(0.002, 0.004)

        if verbose:
            print(f"  [{i+1}/{len(image_paths)}] {Path(path).name} — depth: {t1-t0:.2f}s")

        slides.append({
            'img': img, 'depth': depth,
            'cx': cx, 'cy': cy,
            'panx': 0.0, 'pany': 0.0,
            'zoom': 1.0,
            'pan_dir_x': pan_dir_x, 'pan_dir_y': pan_dir_y,
            'zoom_speed': zoom_speed,
        })

    if not slides:
        print("No images found!")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, OUTPUT_FPS, TARGET_SIZE)

    total_frames = int(SLIDE_DURATION * OUTPUT_FPS)

    for si, slide in enumerate(slides):
        panx, pany = 0.0, 0.0
        zoom = 1.0

        for frame in range(total_frames):
            t = frame / max(total_frames - 1, 1)

            # Accumulate camera motion
            panx += slide['pan_dir_x']
            pany += slide['pan_dir_y']
            zoom += slide['zoom_speed']

            # Crossfade to next slide
            alpha = 0.0
            if si < len(slides) - 1 and frame >= total_frames - 15:
                alpha = (frame - (total_frames - 15)) / 15.0

            frame_a = compute_frame(
                slide['img'], slide['depth'],
                slide['cx'], slide['cy'],
                zoom, panx, pany, TARGET_SIZE
            )

            if alpha > 0 and si + 1 < len(slides):
                ns = slides[si + 1]
                frame_b = compute_frame(
                    ns['img'], ns['depth'],
                    ns['cx'], ns['cy'],
                    1.0, 0.0, 0.0, TARGET_SIZE
                )
                frame_a = cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)

            writer.write(frame_a)

        elapsed = time.time() - t_start
        remaining = (elapsed / (si + 1)) * (len(slides) - si - 1)
        if verbose:
            print(f"  Slide {si+1}/{len(slides)} — {elapsed:.0f}s elapsed, ~{remaining:.0f}s left")

    writer.release()
    total = time.time() - t_start
    if verbose:
        print(f"\n✅ Saved: {output_path}")
        print(f"   {len(slides)} slides × {SLIDE_DURATION}s = {len(slides)*SLIDE_DURATION:.0f}s")
        print(f"   Build time: {total:.1f}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--slide-duration', type=float, default=SLIDE_DURATION)
    args = parser.parse_args()

    SLIDE_DURATION = args.slide_duration
    build_video(args.images, args.output)
