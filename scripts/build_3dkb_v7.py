#!/usr/bin/env python3
"""
3D Ken Burns v7 — Edge-aware layer compositing
Use GrabCut + depth edges to get clean object masks that follow
actual image edges (not noisy depth boundaries).
Ghost-free parallax via layer zoom separation.
"""

import argparse, time, warnings, gc
warnings.filterwarnings('ignore')
import cv2, numpy as np, torch
from pathlib import Path

TARGET_SIZE = (1920, 1080)
FPS = 30
SLIDE_DURATION = 5.0
N_LAYERS = 3        # near / mid / far
ZOOM_NEAR = 0.004  # fastest zoom (foreground)
ZOOM_MID  = 0.002
ZOOM_FAR  = 0.0006

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


def get_depth_edge_mask(depth, lower=0.05, upper=0.3):
    """Find edges where depth changes sharply — potential object boundaries."""
    # Sobel on depth
    depth_u8 = (depth * 255).astype(np.uint8)
    sobel_x = cv2.Sobel(depth_u8, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(depth_u8, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = np.sqrt(sobel_x**2 + sobel_y**2)
    magnitude = cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    edges = cv2.Canny(magnitude, lower * 255, upper * 255)
    return edges  # 255 = depth edge


def grabcut_segment(img, rect=None, n_iters=3):
    """
    Run GrabCut on image.
    Returns foreground mask (255 = fg, 0 = bg).
    """
    if rect is None:
        h, w = img.shape[:2]
        rect = (int(w * 0.05), int(h * 0.05), int(w * 0.9), int(h * 0.9))

    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    cv2.grabCut(img, mask, rect, bgd_model, fgd_model, n_iters, cv2.GC_INIT_WITH_RECT)

    # Probable foreground + definite foreground
    fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    # Clean up with morphology
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
    return fg_mask


def build_edge_aware_masks(img, depth):
    """
    Build N clean layer masks using depth edges + GrabCut.
    Returns list of masks [(name, mask)], where mask is uint8 0-255.
    """
    h, w = img.shape[:2]

    # ── Step 1: Get depth edge regions ──────────────────────────────────
    depth_edges = get_depth_edge_mask(depth)
    # Dilate edges slightly
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    depth_edges_dilated = cv2.dilate(depth_edges, kernel, iterations=2)

    # ── Step 2: Quantize depth into N bands ──────────────────────────────
    flat_d = depth.flatten()
    quantiles = np.linspace(0, 1, N_LAYERS + 1)
    thresholds = [np.quantile(flat_d, q) for q in quantiles[1:-1]]

    # Build hard depth band masks
    band_masks = []
    prev = 0.0
    for j, t in enumerate(thresholds):
        band = np.zeros((h, w), dtype=np.float32)
        band[(depth >= prev) & (depth < t)] = 1.0
        band_masks.append(band)
        prev = t
    band_masks.append(np.zeros((h, w), dtype=np.float32))
    band_masks[-1][depth >= prev] = 1.0  # near = last

    layer_names = ['far', 'mid', 'near'][::-1]  # near = highest depth

    # ── Step 3: For each band, run GrabCut to get clean edges ──────────
    clean_masks = []
    for k, (name, band) in enumerate(zip(layer_names, band_masks)):
        # Get the region pixels for this depth band
        band_u8 = (band * 255).astype(np.uint8)

        # Find bounding rect of non-zero area
        pts = np.where(band_u8 > 127)
        if len(pts[0]) < 100:
            clean_masks.append((name, np.zeros((h, w), dtype=np.uint8)))
            continue

        y_min, y_max = pts[0].min(), pts[0].max()
        x_min, x_max = pts[1].min(), pts[1].max()

        # Shrink rect slightly to avoid edge artifacts
        pad = 5
        x_min = max(0, x_min - pad)
        y_min = max(0, y_min - pad)
        x_max = min(w, x_max + pad)
        y_max = min(h, y_max + pad)

        # Run GrabCut on the band region
        roi = img[y_min:y_max, x_min:x_max]
        if roi.size == 0 or roi.shape[0] < 10 or roi.shape[1] < 10:
            clean_masks.append((name, np.zeros((h, w), dtype=np.uint8)))
            continue

        try:
            gc_mask = grabcut_segment(roi, n_iters=2)
        except Exception:
            gc_mask = cv2.threshold(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 0, 255, cv2.THRESH_BINARY)[1]

        # Place back in full-size mask
        full_mask = np.zeros((h, w), dtype=np.uint8)
        gm_h, gm_w = gc_mask.shape
        full_mask[y_min:y_min+gm_h, x_min:x_min+gm_w] = gc_mask

        # Multiply by depth band to ensure only this band's pixels
        full_mask = cv2.bitwise_and(full_mask, full_mask, mask=band_u8)

        # Refine: keep only largest connected component
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(full_mask, connectivity=8)
        if num_labels > 1:
            largest = np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1
            full_mask = (labels == largest).astype(np.uint8) * 255

        clean_masks.append((name, full_mask))
        del roi, gc_mask, full_mask
        gc.collect()

    return clean_masks  # [(name, mask_0to255), ...]


def zoom_crop_layer(img, cx, cy, zoom_factor, target_size):
    """Crop + resize img to target_size centered at (cx, cy)."""
    h, w = img.shape[:2]
    tw, th = target_size
    crop_w = max(1, int(w / zoom_factor))
    crop_h = max(1, int(h / zoom_factor))
    px = max(0, min(cx * w - crop_w / 2, w - crop_w))
    py = max(0, min(cy * h - crop_h / 2, h - crop_h))
    x2 = min(w, int(px) + crop_w)
    y2 = min(h, int(py) + crop_h)
    cropped = img[int(py):y2, int(px):x2]
    if cropped.size == 0:
        return np.zeros((th, tw, 3), dtype=np.uint8)
    return cv2.resize(cropped, (tw, th))


def composite_frame(img, masks, cx, cy, zn, zm, zf, target_size):
    """
    Composite layers with different zoom speeds.
    bg = far (slowest zoom) rendered first.
    fg = near (fastest zoom) rendered LAST (on top).
    Hard masks — no blending, no ghosting.
    masks order: [far_mask, mid_mask, near_mask]
    """
    tw, th = target_size

    # Accumulate zoom per layer
    # z_layers: [far_zoom, mid_zoom, near_zoom]
    z_layers = [zf, zm, zn]

    # Build each layer crop + mask
    layer_crops = []
    for j, (name, mask) in enumerate(masks):
        z = max(1.0, min(z_layers[j], 2.0))
        crop = zoom_crop_layer(img, cx, cy, z, target_size)
        resized_mask = cv2.resize(mask, (tw, th))
        # Hard binary mask
        binary_mask = (resized_mask > 127).astype(np.uint8)
        layer_crops.append((binary_mask, crop))

    # Composite: render far first, overlay mid, then near on top
    result = np.zeros((th, tw, 3), dtype=np.uint8)
    for binary_mask, crop in layer_crops:
        # Dilate mask slightly to fill hairline gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary_mask = cv2.dilate(binary_mask, kernel, iterations=1)
        binary_mask_3ch = np.stack([binary_mask] * 3, axis=2)
        result = np.where(binary_mask_3ch == 1, crop, result)

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
        masks = build_edge_aware_masks(img, depth)
        t1 = time.time()

        cx = np.random.uniform(0.36, 0.64)
        cy = np.random.uniform(0.36, 0.64)
        direction = np.random.choice(['in', 'out'])
        sign = 1 if direction == 'in' else -1

        if verbose:
            n_fg = sum(1 for _, m in masks if m.sum() > 0)
            print(f"  [{i+1}/{len(image_paths)}] {Path(path).name} — depth+maps: {t1-t0:.1f}s, {n_fg} layers")

        slides.append({
            'img': img, 'depth': depth, 'masks': masks,
            'cx': cx, 'cy': cy,
            'zn': 1.0, 'zm': 1.0, 'zf': 1.0,
            'speed_near': sign * ZOOM_NEAR,
            'speed_mid':  sign * ZOOM_MID,
            'speed_far':  sign * ZOOM_FAR,
        })

    if not slides:
        print("No images found!")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, FPS, TARGET_SIZE)

    n_frames = int(SLIDE_DURATION * FPS)
    fade = min(15, n_frames // 4)

    for si, slide in enumerate(slides):
        zn, zm, zf = slide['zn'], slide['zm'], slide['zf']

        for fi in range(n_frames):
            zn = min(zn + slide['speed_near'], 1.8)
            zm = min(zm + slide['speed_mid'],   1.8)
            zf = min(zf + slide['speed_far'],   1.8)

            alpha = 0.0
            if si < len(slides) - 1 and fi >= n_frames - fade:
                alpha = (fi - (n_frames - fade)) / fade

            frame_a = composite_frame(
                slide['img'], slide['masks'],
                slide['cx'], slide['cy'], zn, zm, zf, TARGET_SIZE
            )

            if alpha > 0 and si + 1 < len(slides):
                ns = slides[si + 1]
                frame_b = composite_frame(
                    ns['img'], ns['masks'],
                    ns['cx'], ns['cy'], 1.0, 1.0, 1.0, TARGET_SIZE
                )
                frame_a = cv2.addWeighted(frame_a, 1 - alpha, frame_b, alpha, 0)

            writer.write(frame_a)

        elapsed = time.time() - t_start
        if verbose:
            print(f"  Slide {si+1}/{len(slides)} — {elapsed:.0f}s")

    writer.release()
    total = time.time() - t_start
    if verbose:
        print(f"\n✅ {output_path}  ({total:.0f}s, {len(slides)*SLIDE_DURATION:.0f}s video)")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--images', nargs='+', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--slide-duration', type=float, default=SLIDE_DURATION)
    args = p.parse_args()
    SLIDE_DURATION = args.slide_duration
    build_video(args.images, args.output)
