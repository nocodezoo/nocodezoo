#!/usr/bin/env python3
"""
3D Ken Burns Effect — CPU Version (Transformers-based)
Depth-based layer compositing with parallax zoom per layer.
Uses Transformers depth pipeline + OpenCV compositing.

Target: ~5s per image on 4-vCPU VPS → 15 images ≈ 75s total
"""

import argparse
import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

import cv2
import numpy as np
import torch
import torch.nn as nn
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
DEVICE = 'cpu'
TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0       # seconds per image
TRANSITION_FRAMES = 15     # crossfade frames between slides
DEPTH_SIZE = (384, 288)   # depth map output resolution

# Zoom speeds per layer (higher = faster = more zoom in)
ZOOM_NEAR = 0.004    # foreground: fastest
ZOOM_MID  = 0.002    # mid-ground
ZOOM_FAR  = 0.0008   # background: slowest

# ── Depth Model (Transformers) ───────────────────────────────────────────────
_pipe = None

def get_depth_pipeline():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        print("Loading depth model (Intel/dpt-hybrid-midas)...")
        _pipe = pipeline("depth-estimation", model="Intel/dpt-hybrid-midas")
        print("Depth model ready.")
    return _pipe

def estimate_depth(img_bgr):
    """Returns disparity map (H, W) as numpy array, values 0-1, higher=nearer."""
    from PIL import Image
    pipe = get_depth_pipeline()
    # Convert BGR → RGB PIL Image
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    result = pipe(pil_img)
    raw = result["predicted_depth"]
    # Convert torch.Tensor → numpy array, resize to full image size
    depth_np = raw.detach().cpu().numpy()
    if depth_np.ndim == 3:
        depth_np = depth_np.squeeze()
    depth_np = cv2.resize(depth_np, (img_bgr.shape[1], img_bgr.shape[0]))
    # Normalize to 0-1
    if depth_np.max() > depth_np.min():
        depth_np = (depth_np - depth_np.min()) / (depth_np.max() - depth_np.min())
    return depth_np.astype(np.float32)

# ── Layer Segmentation ───────────────────────────────────────────────────────
def segment_layers(depth, n_layers=3):
    """Split depth into n layers. Returns raw depth fractions — caller thresholds."""
    flat = depth.flatten()
    q_bounds = [np.quantile(flat, i / n_layers) for i in range(1, n_layers)]
    masks = []
    prev = 0.0
    for thresh in q_bounds:
        mask = np.clip((depth - prev) / (thresh - prev + 1e-8), 0, 1)
        masks.append(mask)
        prev = thresh
    # Last layer: nearest
    mask = np.clip((depth - prev) / (depth.max() - prev + 1e-8), 0, 1)
    masks.append(mask)
    return masks  # [far, mid, near] — near has highest depth values

# ── Zoom Crop ────────────────────────────────────────────────────────────────
def zoom_crop(img, cx, cy, zoom_factor, target_size):
    """Crop + zoom to target_size from img, centered at (cx, cy) fraction."""
    h, w = img.shape[:2]
    tw, th = target_size
    crop_w = w / zoom_factor
    crop_h = h / zoom_factor
    px = cx * (w - crop_w)
    py = cy * (h - crop_h)
    x1 = int(max(0, px))
    y1 = int(max(0, py))
    x2 = int(min(w, px + crop_w))
    y2 = int(min(h, py + crop_h))
    cropped = img[y1:y2, x1:x2]
    if cropped.size == 0:
        return np.zeros((th, tw, 3), dtype=np.uint8)
    return cv2.resize(cropped, (tw, th))

# ── Build Slide Frame (layer compositing) ───────────────────────────────────
def build_slide_frame(img, depth, layer_masks, cx, cy,
                      zn, zm, zf, target_size):
    """
    Composite a frame: far layer + mid layer + near layer with different zoom.
    Uses HARD occlusion masks — near layer completely covers mid/far.
    No soft blending = no ghosting.
    zn/zm/zf = accumulated zoom factors per layer
    """
    tw, th = target_size

    # Crop each layer at its zoom level
    far_crop  = zoom_crop(img, cx, cy, zf, target_size)
    mid_crop  = zoom_crop(img, cx, cy, zm, target_size)
    near_crop = zoom_crop(img, cx, cy, zn, target_size)

    # Resize depth-based masks to target size
    far_mask  = cv2.resize(layer_masks[0], (tw, th))
    mid_mask  = cv2.resize(layer_masks[1], (tw, th))
    near_mask = cv2.resize(layer_masks[2], (tw, th))

    # Threshold to HARD binary masks — no soft blending
    near_bin = (near_mask > 0.4).astype(np.uint8)   # near = 1 where clearly near
    mid_bin  = (mid_mask  > 0.4).astype(np.uint8)   # mid  = 1 where clearly mid (and not near)
    # Far fills remaining
    far_bin  = np.ones((th, tw), dtype=np.uint8)
    far_bin = far_bin - near_bin - mid_bin
    far_bin = np.clip(far_bin, 0, 1).astype(np.uint8)

    # Composite: each pixel shows exactly ONE layer — no blending
    result = np.zeros((th, tw, 3), dtype=np.uint8)
    for c in range(3):
        result[:, :, c] = (
            far_crop[:, :, c].astype(np.uint16) * far_bin +
            mid_crop[:, :, c].astype(np.uint16)  * mid_bin +
            near_crop[:, :, c].astype(np.uint16) * near_bin
        )
    result = np.clip(result, 0, 255).astype(np.uint8)
    return result

# ── Build Full Video ─────────────────────────────────────────────────────────
def build_video(image_paths, output_path, verbose=True):
    t_start = time.time()

    pipe = get_depth_pipeline()  # preload

    # Pre-compute depth + layers for each image
    slides = []
    for i, path in enumerate(image_paths):
        img = cv2.imread(str(path))
        if img is None:
            if verbose:
                print(f"  ⚠ Could not read {path}, skipping")
            continue
        img = cv2.resize(img, TARGET_SIZE)

        t0 = time.time()
        depth = estimate_depth(img)
        layer_masks = segment_layers(depth, n_layers=3)
        t1 = time.time()

        # Random camera path per image
        cx = np.random.uniform(0.32, 0.68)
        cy = np.random.uniform(0.32, 0.68)
        direction = np.random.choice(['in', 'out'])
        sign = 1 if direction == 'in' else -1

        if verbose:
            print(f"  [{i+1}/{len(image_paths)}] {Path(path).name} — depth: {t1-t0:.2f}s")

        slides.append({
            'img': img,
            'depth': depth,
            'layer_masks': layer_masks,
            'cx': cx, 'cy': cy,
            'zn': 1.0, 'zm': 1.0, 'zf': 1.0,
            'speed_near': sign * ZOOM_NEAR,
            'speed_mid':  sign * ZOOM_MID,
            'speed_far':  sign * ZOOM_FAR,
        })

    if not slides:
        print("No valid images found!")
        return

    # Video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, FPS, TARGET_SIZE)

    total_frames = int(SLIDE_DURATION * FPS)
    tfade = min(TRANSITION_FRAMES, total_frames // 3)

    for slide_idx, slide in enumerate(slides):
        for frame_num in range(total_frames):
            t = frame_num / max(total_frames - 1, 1)

            # Advance zoom per layer
            zn = slide['zn'] + slide['speed_near']
            zm = slide['zm'] + slide['speed_mid']
            zf = slide['zf'] + slide['speed_far']
            slide['zn'] = zn
            slide['zm'] = zm
            slide['zf'] = zf

            # Build frame
            frame = build_slide_frame(
                slide['img'], slide['depth'], slide['layer_masks'],
                slide['cx'], slide['cy'], zn, zm, zf, TARGET_SIZE
            )

            # Crossfade to next slide
            blend_alpha = 0.0
            if frame_num >= total_frames - tfade and slide_idx < len(slides) - 1:
                blend_alpha = (frame_num - (total_frames - tfade)) / tfade

            if blend_alpha > 0 and slide_idx + 1 < len(slides):
                ns = slides[slide_idx + 1]
                nframe = build_slide_frame(
                    ns['img'], ns['depth'], ns['layer_masks'],
                    ns['cx'], ns['cy'], zn, zm, zf, TARGET_SIZE
                )
                frame = cv2.addWeighted(frame, 1 - blend_alpha, nframe, blend_alpha, 0)

            writer.write(frame)

        elapsed = time.time() - t_start
        done = slide_idx + 1
        eta = (elapsed / done) * (len(slides) - done) if done > 0 else 0
        if verbose:
            print(f"  Slide {done}/{len(slides)} done — {elapsed:.0f}s elapsed, ~{eta:.0f}s remaining")

    writer.release()
    total = time.time() - t_start
    if verbose:
        print(f"\n✅ Saved: {output_path}")
        print(f"   {len(slides)} slides × {SLIDE_DURATION}s = {len(slides)*SLIDE_DURATION:.0f}s @ {FPS}fps")
        print(f"   Total build time: {total:.1f}s ({total/(len(slides)*SLIDE_DURATION):.1f}s per second of video)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='3D Ken Burns Effect (depth-based parallax)')
    parser.add_argument('--images', nargs='+', required=True, help='Input image paths')
    parser.add_argument('--output', required=True, help='Output MP4 path')
    parser.add_argument('--slide-duration', type=float, default=SLIDE_DURATION)
    args = parser.parse_args()

    build_video(args.images, args.output)
