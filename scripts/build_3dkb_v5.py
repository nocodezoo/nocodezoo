#!/usr/bin/env python3
"""
3D Ken Burns v5 — PyTorch grid_sample warp (CPU, MKL-accelerated)
Replicates the sniklaus/3d-ken-burns warping approach using PyTorch's
bilinear grid_sample instead of CuPy.

Speed target: <30s for 30s video on 4-vCPU VPS
"""

import argparse
import time
import warnings
warnings.filterwarnings('ignore')

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from pathlib import Path

TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0
MAX_DISPARITY = 0.12  # normalized [-1,1] coords — near/far shift

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
        depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
    return depth.astype(np.float32)


def depth_to_disparity(depth, max_disp):
    """
    Convert depth (0=far, 1=near) to disparity shift.
    Near objects (depth=1) get max_disp shift.
    Returns (H, W) disparity in normalized coords.
    """
    disp = depth * max_disp  # near=MAX_DISPARITY, far=0
    return disp.astype(np.float32)


def make_grid(h, w, cx, cy, zoom, panx, pany, disparity):
    """
    Build a flow/grid tensor for grid_sample.
    sniklaus-style: generate meshgrid, offset by disparity * pan_direction.
    Returns grid tensor of shape (1, H, W, 2) in normalized [-1, 1] coords.
    """
    # Normalized coords: [-1, 1] range
    # x: -1=left, 1=right  |  y: -1=top, 1=bottom
    x = torch.linspace(-1, 1, w)
    y = torch.linspace(-1, 1, h)
    yy, xx = torch.meshgrid(y, x, indexing='ij')  # (H, W)

    # Camera look-at offset
    offset_x = (cx - 0.5) * 2  # cx 0-1 → -1 to 1
    offset_y = (cy - 0.5) * 2

    # Zoom crop: scale coordinates
    scale = 1.0 / zoom
    # Clip to zoomed view
    half_w = (w * scale) / 2
    half_h = (h * scale) / 2

    # Normalized coords after zoom (still [-1,1] range)
    gx = (xx + offset_x) * scale + panx * 2  # pan in normalized space
    gy = (yy + offset_y) * scale + pany * 2

    # Apply depth-based disparity offset (parallax)
    # Disparity: near (depth≈1) shifts more than far
    # Shift direction: opposite to pan direction for parallax effect
    gx = gx + disparity * torch.sign(torch.tensor(panx + 1e-8)).float()
    gy = gy + disparity * torch.sign(torch.tensor(pany + 1e-8)).float()

    # Clip to [-1, 1]
    gx = torch.clamp(gx, -1, 1)
    gy = torch.clamp(gy, -1, 1)

    # Stack: (H, W, 2)
    grid = torch.stack([gx, gy], dim=2).unsqueeze(0)  # (1, H, W, 2)
    return grid


def warp_frame_torch(img_np, depth, cx, cy, zoom, panx, pany, out_size):
    """
    Warp img_np using depth-based parallax via PyTorch grid_sample.
    img_np: (H, W, 3) uint8
    Returns warped frame at out_size.
    """
    h, w = img_np.shape[:2]
    tw, th = out_size

    # Convert to PyTorch tensor (C, H, W)
    img_t = torch.from_numpy(img_np).permute(2, 0, 1).float() / 255.0  # (3, H, W)

    # Compute disparity
    disparity = depth_to_disparity(depth, MAX_DISPARITY)

    # Build flow grid
    grid = make_grid(h, w, cx, cy, zoom, panx, pany, torch.from_numpy(disparity))
    grid = grid.float()

    # Resize depth to match image
    depth_t = torch.from_numpy(cv2.resize(depth, (w, h))).float().unsqueeze(0).unsqueeze(0)

    # Apply zoom via crop+resize BEFORE warp (camera zoom)
    zoom_factor = zoom
    zoomed_h = int(h / zoom_factor)
    zoomed_w = int(w / zoom_factor)

    # Crop from camera center
    cx_px = int(cx * w)
    cy_px = int(cy * h)
    x1 = max(0, cx_px - zoomed_w // 2)
    y1 = max(0, cy_px - zoomed_h // 2)
    x2 = min(w, x1 + zoomed_w)
    y2 = min(h, y1 + zoomed_h)

    img_cropped = img_t[:, y1:y2, x1:x2]
    depth_cropped = depth_t[:, y1:y2, x1:x2]

    # Resize cropped to output size
    img_resized = F.interpolate(
        img_cropped.unsqueeze(0), size=(th, tw), mode='bilinear', align_corners=False
    ).squeeze(0)
    depth_resized = F.interpolate(
        depth_cropped, size=(th, tw), mode='nearest'
    ).squeeze()

    # Rebuild grid for resized image (output resolution)
    disparity_resized = depth_resized.numpy() * MAX_DISPARITY
    grid_out = make_grid(th, tw, 0.5, 0.5, 1.0, panx * (tw/w), pany * (th/h),
                         torch.from_numpy(disparity_resized.astype(np.float32)))

    # Apply grid_sample warp
    warped = F.grid_sample(
        img_resized.unsqueeze(0),
        grid_out,
        mode='bilinear',
        padding_mode='border',
        align_corners=False
    ).squeeze(0).permute(1, 2, 0)  # (H, W, 3)

    return (warped.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)


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
        pdx = np.random.choice([-1, 1]) * np.random.uniform(0.003, 0.007)
        pdy = np.random.choice([-1, 1]) * np.random.uniform(0.001, 0.003)
        zspd = np.random.uniform(0.002, 0.004)

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
            panx += slide['pdx']
            pany += slide['pdy']
            zoom += slide['zspd']

            alpha = 0.0
            if si < len(slides) - 1 and fi >= n_frames - fade_frames:
                alpha = (fi - (n_frames - fade_frames)) / fade_frames

            frame_a = warp_frame_torch(
                slide['img'], slide['depth'],
                slide['cx'], slide['cy'],
                zoom, panx, pany, TARGET_SIZE
            )

            if alpha > 0 and si + 1 < len(slides):
                ns = slides[si + 1]
                frame_b = warp_frame_torch(
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
