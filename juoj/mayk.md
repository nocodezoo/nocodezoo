1. System goal

Build a local-first real-estate photo-to-cinematic-video engine for Apple Silicon Macs with 8 GB unified memory. The system takes one or more listing photos and produces short, polished video clips that simulate premium camera motion such as push-ins, pans, drift, slight orbit, and shallow fly-through effects.

The system should not be designed as a full end-to-end text-to-video generator. It should instead be built as a hybrid geometry + generative refinement pipeline. That is the only version that is likely to be controllable, memory-feasible, and commercially reliable on the target hardware.

The design below is intended so that a separate engineering team can implement it without needing to invent the overall architecture.

2. Product scope

2.1 Primary use cases

The system should support:

Single-photo motion clips** for interiors and exteriors
Multi-photo enhanced clips** for stronger motion and better occlusion recovery
Preset-driven cinematic motion** for real-estate use
Local generation** on Apple Silicon
Export-ready clips** for web, social, and listing platforms

2.2 Explicit non-goals for v1

The system should not promise:

unrestricted free-camera navigation from a single still
true 3D reconstruction of a whole house from one image
long continuous room-to-room fly-throughs from one frame
fully generative 1080p video diffusion at full frame count on-device
open-ended text prompting as the primary control surface

3. Design principles

The architecture should follow these principles:

Constrain motion more than generation.** Stable shallow motion looks premium; aggressive hallucinated motion looks fake.
Use geometry first.** Depth, planes, masks, and layout are cheaper and more controllable than full generative video.
Generate only where needed.** Use inpainting and refinement only for newly exposed regions, temporal cleanup, and realism enhancement.
Separate perception from rendering from refinement.** This makes the system debuggable and replaceable.
Keep peak memory low through staged execution.** Only a subset of models should be resident at once.
Use structured shot controls, not free-form prompts.** Real-estate users want predictable output, not creative ambiguity.
Optimize for perceived quality, not native generation purity.** Interpolation, upscaling, grading, and stabilization matter more than raw model sophistication.

4. High-level architecture

The system should be organized into eight sequential stages:

Ingest and normalization
Scene analysis
Scene representation
Shot planning
Geometry-based render synthesis
Occlusion repair and image completion
Temporal refinement and frame synthesis
Upscale, finishing, and export

A simple flow looks like this:

Input Photo(s)
   ↓
Ingest / Normalize
   ↓
Depth + Segmentation + Planes + Layout
   ↓
Scene Graph / Layered 2.5D Representation
   ↓
Shot Preset + Camera Path + Motion Constraints
   ↓
Depth Warp / Layered Render / Novel View Approximation
   ↓
Hole Masking + Local Inpainting + Texture Completion
   ↓
Temporal Refinement + Flicker Cleanup + Frame Interpolation
   ↓
Upscale + Color Grade + Export

5. System modules

5.1 Module A: Input ingest and normalization

This module prepares user assets and metadata.

Responsibilities

import JPEG, PNG, HEIC
auto-rotate using EXIF orientation
detect and preserve color profile
normalize to internal working color space
detect image type: interior, exterior, bathroom, kitchen, bedroom, aerial-like exterior, twilight exterior
optionally group multiple images by room / scene similarity

Inputs

one or more images
optional user-selected shot preset
optional branding package
optional output format settings

Outputs

{
  "scene_id": "uuid",
  "images": [
    {
      "image_id": "uuid",
      "path": "local/path",
      "width": 4032,
      "height": 3024,
      "orientation": "landscape",
      "exif": {...},
      "room_type_hint": "living_room"
    }
  ],
  "project_settings": {
    "target_aspect_ratio": "16:9",
    "output_resolution": "1920x1080",
    "quality_mode": "balanced"
  }
}

Implementation notes

Normalize input to a master image and a lower-resolution working copy.
Create pyramids at full, medium, and working resolution.
Working resolution for v1 should usually be one of:
  384x640
  448x768
  512x896

5.2 Module B: Scene analysis

This module performs the perception stack.

Responsibilities

estimate monocular depth
detect semantic classes
detect planar surfaces
infer room layout and vanishing direction
identify mirrors/windows/TV screens as risky reflective surfaces
estimate object salience and foreground anchors
optionally estimate sky mask and outdoor depth confidence

Subcomponents

B1. Depth estimation

Use a lightweight but high-quality monocular depth model.

Recommended options:

Depth Anything V2 Small / Base** as default candidate
alternate swappable interface for other lightweight depth estimators

Output:

{
  "depth_map": "float16 tensor or 16-bit image",
  "depth_confidence": "float map",
  "depth_scale_mode": "relative"
}

B2. Semantic segmentation

Classes should include at minimum:

wall
floor
ceiling
window
mirror
door
cabinet
countertop
furniture
bed
sofa
table
rug
plant
pool
sky
grass
driveway
facade
roof
water
glass

Output:

{
  "segmentation_map": "uint16 class map",
  "instance_masks": [
    {"class": "sofa", "mask": "...", "score": 0.98}
  ]
}

B3. Plane and layout estimation

Estimate dominant planes:

floor plane
back wall
side walls
facade plane for exteriors
major horizontal surfaces

This is critical because planar surfaces warp much better than raw dense depth alone.

Output:

{
  "planes": [
    {
      "plane_id": "floor",
      "normal": [0.0, 1.0, 0.0],
      "mask": "...",
      "fit_error": 0.08
    }
  ],
  "vanishing_points": [[x1,y1],[x2,y2],[x3,y3]],
  "camera_intrinsics_estimate": {
    "fov_deg": 71.0,
    "principal_point": [0.5, 0.5]
  }
}

B4. Reflection / transparency risk detection

Flag surfaces where depth warp will look bad:

mirrors
large windows
TV screens
glossy stone / polished floors
pool water
glass railings

This should influence the camera planner later.

Implementation notes

All outputs should be cached to disk per scene.
Analysis should be run once per input image and reused across presets.
If multi-photo mode is enabled, this module should also compute image correspondences.

5.3 Module C: Scene representation

This is the core internal format. Build a layered 2.5D scene graph rather than a full mesh reconstruction.

Responsibilities

convert raw analysis into a renderable scene representation
create depth layers and foreground/background separation
define protected regions and risky regions
build occlusion likelihood maps
define anchor points for motion stabilization

Recommended representation

Use a Layered Depth Image + Plane Pack:

base RGB image
dense depth map
semantic segmentation map
set of dominant planes
list of foreground objects with masks
disocclusion risk mask
camera intrinsics estimate
horizon / vanishing geometry

Internal structure

{
  "scene_graph": {
    "background": {
      "rgb": "path",
      "depth": "path",
      "planes": ["back_wall", "left_wall", "floor"]
    },
    "foreground_layers": [
      {
        "id": "sofa_01",
        "class": "sofa",
        "mask": "path",
        "depth_stats": {"near": 0.22, "far": 0.37},
        "motion_sensitivity": "high"
      }
    ],
    "risk_regions": [
      {"type": "mirror", "mask": "path"},
      {"type": "window", "mask": "path"}
    ],
    "anchors": [
      {"type": "room_center", "xy": [0.52, 0.55]},
      {"type": "dominant_subject", "xy": [0.61, 0.58]}
    ]
  }
}

Why this matters

This representation allows:

cheap parallax rendering
controlled foreground separation
selective inpainting only where exposure occurs
better temporal consistency than dense warp alone

5.4 Module D: Shot planner

This module decides what motion is safe and desirable for a given scene.

Responsibilities

choose a shot preset
parameterize camera motion
reject unsafe aggressive moves
adapt motion to room type, depth confidence, and risk regions

Inputs

scene graph
user preset selection or auto mode
desired clip length
aspect ratio and delivery format

Outputs

A structured shot plan such as:

{
  "shot_plan": {
    "preset": "luxury_push_in",
    "duration_sec": 5.0,
    "fps_base": 12,
    "fps_output": 24,
    "camera_path": {
      "tx": [0.00, 0.03],
      "ty": [0.00, -0.01],
      "tz": [0.00, 0.08],
      "yaw_deg": [0.0, 1.5],
      "pitch_deg": [0.0, -0.5],
      "roll_deg": [0.0, 0.0],
      "fov_deg": [71.0, 68.5],
      "easing": "ease_in_out"
    },
    "constraints": {
      "max_disocclusion_ratio": 0.11,
      "protect_masks": ["mirror_01", "window_02"],
      "max_foreground_edge_shift_px": 18
    }
  }
}

Required presets for v1

For interiors:

Luxury push-in
Slow lateral drift
Kitchen island reveal
Bedroom window drift
Bathroom vanity slide
Subtle dolly with parallax

For exteriors:

Front elevation push-in
Facade drift
Poolside glide
Patio sunset drift
Orbit-lite
Driveway reveal

Planning heuristics

The planner should apply rules like:

if depth confidence low, reduce tz motion
if mirror coverage high, avoid lateral drift
if foreground occupancy high, use zoom + micro-parallax rather than translation
if hallway scene, allow slightly stronger forward dolly
if exterior sky large, permit mild orbit-lite
if window dominates frame, keep motion subtle

Strong recommendation

Do not use text prompts as the primary interface here. Use a preset + parameters model:

{
  "preset": "kitchen_drift",
  "intensity": 0.6,
  "mood": "bright_luxury",
  "duration_sec": 6,
  "stabilization": "high"
}

5.5 Module E: Geometry-based render synthesis

This module generates the initial frame sequence using depth warping, layered compositing, and plane-aware reprojection.

Responsibilities

synthesize camera motion from a still
render novel views for each target frame
separate foreground and background motion where needed
create hole masks for newly exposed regions

Rendering approach

Use a 2.5D renderer with these capabilities:

depth-based reprojection
plane-based reprojection for dominant surfaces
per-layer warp for segmented foreground objects
edge-aware hole detection
z-buffer compositing
conservative occlusion expansion to reduce tearing

Frame generation loop

For each target frame:

evaluate camera pose on path
reproject background using depth and planes
warp foreground layers separately
composite with visibility ordering
produce:
   provisional RGB frame
   hole/disocclusion mask
   edge instability mask
   warp confidence map

Output per frame

{
  "frame_idx": 12,
  "rgb_provisional": "path",
  "hole_mask": "path",
  "confidence_map": "path",
  "render_metadata": {
    "disocclusion_ratio": 0.084,
    "foreground_shift_px_max": 11.2
  }
}

Implementation notes

Planar surfaces should be reprojected with plane homographies where possible.
Dense depth should fill the rest.
Object masks should be dilated slightly before warp to reduce haloing.
Use temporal pose smoothing to avoid jerk.

5.6 Module F: Occlusion repair and image completion

This module repairs newly visible areas and broken edges.

Responsibilities

fill holes created by camera motion
repair broken object boundaries
continue textures on walls/floors/ceilings
restore window and reflective regions conservatively

Design

This should be local inpainting, not full-frame regeneration.

F1. Region classifier

For each hole region, classify it as one of:

wall continuation
floor continuation
ceiling continuation
outdoor foliage continuation
sky continuation
pool/water continuation
furniture edge repair
window/reflection repair
uncertain

F2. Repair strategy selector

Choose one of:

deterministic texture synthesis / diffusion fill
plane-aware patch synthesis
lightweight latent inpainting model
fallback blur/feather for tiny uncertain regions

F3. Small inpainting model

Use a compact image inpainting model optimized for:

walls
floors
windows
cabinetry
lawn/sky
facade textures

It is better to fine-tune a small domain inpainting model for real estate than to rely on a general giant image model.

Repair constraints

do not alter protected objects unless necessary
preserve straight architectural edges
preserve window frames and facade lines
avoid inventing new objects
maintain color and lighting continuity with source frame

Output

{
  "frame_idx": 12,
  "rgb_repaired": "path",
  "repair_report": {
    "filled_area_ratio": 0.037,
    "methods_used": ["plane_patch", "latent_inpaint"],
    "uncertain_regions": 2
  }
}

5.7 Module G: Temporal refinement

This module removes the “cutout and warp” look and produces temporal coherence.

Responsibilities

reduce flicker
smooth object edges
stabilize texture continuity
enforce temporal consistency in repaired regions
add subtle realism cues like shadow continuity and micro-light response

Architecture recommendation

Use a small latent video refiner rather than a full video generator.

Input sequence:

repaired frame sequence at working resolution
hole masks
confidence maps
optical flow between frames
segmentation priors

Output sequence:

temporally coherent refined frames

Model characteristics

small UNet or DiT-style latent refiner
short temporal window, such as 3–7 frames at a time
conditioned on previous and next frames
optimized for cleanup, not invention

Practical behavior

This module should do things like:

soften minor warp inconsistencies
stabilize cabinet edges and wall lines
correct shimmer in foliage and fabrics
improve temporal continuity in windows and floor reflections
blend repaired regions into motion

Memory strategy

This module should operate in short chunks:

4 to 8 frames at working resolution
sliding window inference
overlap and blend at boundaries

This is essential on 8 GB Macs.

5.8 Module H: Frame interpolation

This module increases motion smoothness and output frame rate.

Responsibilities

convert a low-base-fps refined sequence into 24 or 30 fps
smooth motion trajectories
reduce stutter from sparse base synthesis

Recommended strategy

Generate base frames at:

8–12 fps** for long clips
12–15 fps** for short premium clips

Then interpolate to final output using a lightweight interpolation model.

Why this is important

It is much cheaper to create fewer good frames and interpolate than to fully synthesize every output frame.

Output

{
  "base_fps": 12,
  "output_fps": 24,
  "interpolated_frames": ["..."]
}

5.9 Module I: Super-resolution and finishing

This module converts the working sequence into a polished deliverable.

Responsibilities

upscale to target resolution
apply denoise/sharpening carefully
add cinematic grading
maintain white balance consistency
optionally add subtle grain
generate letterboxed or vertical derivatives

Output targets

1920×1080, 24 or 30 fps
1080×1920 vertical social export
1280×720 fast export
muted or branded MP4 / MOV

Finishing stack

Order should be:

temporal refined frames
upscaling
anti-flicker luminance smoothing
mild local contrast
white balance harmonization
cinematic LUT / style curve
grain if enabled
text/logo end card if enabled
encode

6. Multi-photo mode

This should be a first-class extension, not an afterthought.

6.1 Why it matters

Multi-photo mode makes the system significantly stronger because it provides:

better geometric consistency
actual hidden-region evidence
stronger camera motion options
less inpainting burden
better transitions between viewpoints

6.2 Behavior

When 2 to 8 images of the same room/area are provided:

match keypoints across images
estimate coarse relative camera poses
fuse depth estimates
create a more robust layered scene representation
allow stronger moves such as:
  wider drift
  shallow orbit
  reveal around foreground furniture
  stronger hallway dolly

6.3 Architecture changes in multi-photo mode

Add a correspondence fusion stage between analysis and scene representation:

Per-image analysis
   ↓
Cross-image feature matching
   ↓
Pose graph estimation
   ↓
Depth and plane fusion
   ↓
Unified room scene graph

If correspondences are too poor, gracefully fall back to single-photo mode.

7. Memory architecture for 8 GB Apple Silicon

This section is critical if someone else is actually building it.

7.1 Operating assumptions

Peak unified memory must be controlled by:

low working resolution
short temporal chunks
one major model resident at a time
aggressive release of intermediate tensors
disk-backed caching for scene artifacts

7.2 Recommended working modes

Fast mode

working resolution: 384x640
base fps: 8
output fps: 24
duration: 4–6 sec
minimal temporal refinement

Balanced mode

working resolution: 448x768
base fps: 10–12
output fps: 24
duration: 4–8 sec

Quality mode

working resolution: 512x896
base fps: 12
output fps: 24
duration: 4–6 sec
stronger temporal refinement
may be slow on 8 GB devices

7.3 Approximate residency strategy

Only keep these groups resident at once:

Stage group 1: perception

depth model
segmentation model
plane/layout estimator

Then unload them.

Stage group 2: repair

inpainting model only
one or a few frames in memory

Then unload it.

Stage group 3: temporal refinement

small temporal refiner
chunked frame windows

Then unload it.

Stage group 4: interpolation / upscale

interpolation model
upscaler

Then unload.

7.4 Disk cache layout

Use a project cache structure like:

project/
  inputs/
  analysis/
    depth/
    seg/
    planes/
    masks/
  render/
    provisional_frames/
    hole_masks/
    confidence_maps/
  repair/
  refine/
  interp/
  export/
  metadata/

All large intermediates should be cached to avoid recomputation and to support resume/retry.

8. Control plane and data contracts

A clean build requires stable interfaces between modules.

8.1 Core entities

Project

{
  "project_id": "uuid",
  "created_at": "...",
  "images": [...],
  "settings": {...}
}

Scene

{
  "scene_id": "uuid",
  "source_images": ["uuid1", "uuid2"],
  "mode": "single_photo | multi_photo",
  "analysis_paths": {...},
  "scene_graph_path": "..."
}

Shot plan

{
  "shot_id": "uuid",
  "scene_id": "uuid",
  "preset": "luxury_push_in",
  "params": {...},
  "status": "planned | rendered | repaired | refined | exported"
}

Render job

{
  "job_id": "uuid",
  "shot_id": "uuid",
  "quality_mode": "balanced",
  "target_output": {
    "width": 1920,
    "height": 1080,
    "fps": 24,
    "duration_sec": 5
  }
}

8.2 Module interface contract

Each module should expose:

input schema
output schema
config schema
cache key
resume policy
failure codes

This is essential for a resumable desktop production app.

9. Recommended software architecture

9.1 App-level stack

For a desktop product on macOS:

UI:** SwiftUI
System integration:** Swift
Core orchestration:** Swift or Rust
Model runtime:** Python prototype first, then migrate hot paths to native/optimized stack
Inference backend:** Core ML / Metal / MLX depending on component maturity
Video I/O:** AVFoundation + ffmpeg where needed
Cache / metadata:** SQLite + local file system

Practical recommendation

Use a two-layer architecture:

Product layer

SwiftUI macOS app
project management
preset editing
preview player
export management

Engine layer

native service or local worker process
model inference orchestration
frame cache management
render pipeline execution

This separation makes the system easier to evolve.

9.2 Service decomposition

The engine can be split into these internal services:

asset-service
analysis-service
scene-service
planner-service
render-service
repair-service
refine-service
export-service

These do not need to be separate OS processes initially. They can be modules with clean interfaces.

10. Detailed build pipeline

10.1 Pipeline sequence

Step 1: Import

user imports 1–N images
system validates orientation, resolution, and scene suitability

Step 2: Analyze

run depth estimation
run segmentation
detect planes and vanishing structure
detect risky reflective/translucent regions

Step 3: Build scene graph

create layered representation
identify foreground objects
build disocclusion risk map
estimate camera intrinsics

Step 4: Plan shot

choose preset
generate camera path
validate motion against scene risks
adjust to safe bounds

Step 5: Render provisional frames

render base frames at working resolution and base fps
save hole masks and confidence maps

Step 6: Repair

fill disoccluded regions
repair edges and reflective issues
save repaired frames

Step 7: Refine temporally

run chunked temporal cleanup
blend chunk overlaps

Step 8: Interpolate

raise fps to output fps

Step 9: Upscale and finish

upscale sequence
grade and stabilize luminance
add branding

Step 10: Encode and export

encode MP4/MOV
produce previews and derivatives

11. Camera model and motion parameterization

This is important because it replaces vague prompting.

11.1 Camera parameters

Represent each shot with:

tx, ty, tz for translation
yaw, pitch, roll
fov
focus_anchor
motion_curve
parallax_strength
foreground_lock_strength

11.2 Safe motion ranges for single-photo mode

For v1, keep motion conservative.

Interior recommendations

tz push-in: 0.03 to 0.10 scene-relative
lateral tx: 0.01 to 0.04
yaw: 0.5° to 2.0°
pitch: -1.0° to 1.0°
FOV change: 2° to 5°

Exterior recommendations

tz: 0.02 to 0.08
tx: 0.02 to 0.06
orbit-lite yaw: 1.0° to 4.0°
avoid large pitch shifts unless sky coverage is high

11.3 Shot validation rules

Reject or clamp motions when:

predicted disocclusion exceeds threshold
reflective surface coverage is high
foreground object edge shift is too large
hallway narrowing induces severe stretch
window boundaries become unstable

12. Training and fine-tuning strategy

The build can start with off-the-shelf models, but a real product will improve significantly with domain adaptation.

12.1 Models worth training or fine-tuning

Most valuable to fine-tune

localized real-estate inpainting model
temporal refinement model
shot quality scoring model
scene suitability classifier

Less urgent to train from scratch

depth model
segmentation model
frame interpolation model
general upscaler

12.2 Dataset requirements

Create a real-estate dataset with:

interiors and exteriors
luxury and standard listings
day, dusk, twilight, artificial lighting
wide-angle listing photos
known room categories
reflective and glossy scenes
matching short camera-motion clips where possible

Annotation targets

semantic masks
planar masks
reflection/window masks
scene type
shot suitability tags
preferred preset labels
quality ranking labels

12.3 Temporal refiner training target

Train the refiner to map:

warped/repaired frame sequences

to:

temporally coherent visually stable frame sequences

Training supervision can use:

real short-motion video clips from actual camera movement
synthetic warps of still images paired with original video
consistency losses across flow and segmentation boundaries

13. Quality assurance architecture

13.1 Automated quality checks

Before export, run checks for:

flicker score
edge wobble score
straight-line distortion
face/object deformation if humans appear
mirror/window artifact score
clipped highlights after grading
hole-fill artifact score

13.2 Shot rejection or fallback

If a shot fails quality thresholds:

reduce motion intensity and rerun
switch to safer preset
reduce orbit to drift
reduce forward dolly to zoom+micro-parallax
mark frame regions for conservative repair

This fallback system should be built in from day one.

14. Output products and modes

14.1 Core outputs

The engine should support:

single clip export
batch export from a folder of room images
sequence assembly into a short listing reel
vertical and horizontal variants

14.2 Delivery modes

Local mode

Everything runs on-device.

Hybrid mode

Default local render, optional cloud enhancement for:

stronger motion
longer clips
premium multi-image reconstruction
twilight relighting

API / SDK mode

Later, expose the engine to third parties via:

local SDK
desktop automation hooks
cloud API for premium jobs

15. Recommended repository structure

A team will build faster with a clean repo shape.

estate-cine/
  apps/
    macos-app/
  engine/
    core/
      project/
      cache/
      orchestration/
      schemas/
    analysis/
      depth/
      segmentation/
      planes/
      reflections/
    scene/
      layered_representation/
      fusion/
    planning/
      presets/
      camera_paths/
      validators/
    render/
      reprojection/
      compositing/
      masks/
    repair/
      region_classifier/
      inpainter/
      texture_fill/
    refine/
      temporal_refiner/
      anti_flicker/
    interpolate/
    upscale/
    finishing/
    export/
  models/
    manifests/
    converters/
  tests/
    integration/
    scene_fixtures/
    regression/
  docs/
    architecture/
    module-contracts/
    build-guides/

16. Suggested implementation phases

Phase 1: deterministic MVP

Build this first:

input import
depth estimation
segmentation
layered scene graph
preset-driven camera path
depth warp renderer
hole mask generation
simple patch / plane repair
frame interpolation
export

This version alone can already beat standard Ken Burns if tuned well.

Phase 2: product-grade v1

Add:

localized inpainting
better plane handling
reflection risk detection
temporal anti-flicker cleanup
grading
branding/export presets
batch mode

Phase 3: premium quality

Add:

temporal latent refiner
multi-photo fusion mode
shot quality scorer
auto-preset selection
cloud enhancement option

Phase 4: advanced modes

Add:

stronger exteriors
premium orbit-lite
room-to-room transitions from multiple photos
LiDAR-assisted iPhone capture mode
listing reel auto-editor

17. What a concrete v1 implementation should look like

If I were handing this to a build team, I would instruct them to target this exact v1:

v1 input

one image per shot
optional batch folder

v1 motion styles

6 interior presets
4 exterior presets

v1 generation strategy

working resolution 448x768
base fps 10–12
duration 4–6 sec
output 1920x1080 @ 24 fps
interpolation-based final fps

v1 AI components

monocular depth
semantic segmentation
plane/layout detector
small hole inpainting model
interpolation model
upscaler

v1 non-AI components

camera planner
depth reprojection renderer
mask logic
grading and export pipeline

That v1 is practical and can ship.

18. Key technical risks and mitigations

Risk 1: depth map instability

This causes warped walls, strange floor behavior, and object stretching.

Mitigation:

plane fitting and plane override
semantic-aware depth smoothing
edge-preserving post-processing of depth
shot planner clamping

Risk 2: cutout foreground look

This happens when object layers move unnaturally against the background.

Mitigation:

use foreground lock strength
reduce lateral shift
blend zoom with small translation
temporal refinement near mask edges

Risk 3: mirrors and windows break realism

These areas often expose false geometry.

Mitigation:

detect and protect them early
use conservative motion in those scenes
prefer luminance and reflection smoothing over hard reconstruction

Risk 4: 8 GB memory pressure

Mitigation:

chunked frame processing
one model family resident at a time
cached intermediates on disk
lower working resolution presets
native optimized inference paths

Risk 5: output looks too synthetic

Mitigation:

conservative motion
strong finishing stack
real-estate-specific grading
subtle grain and temporal luminance smoothing
shot presets tuned for luxury marketing aesthetics

19. Example end-to-end shot specification

This is the kind of payload your engine should accept internally.

{
  "project_id": "p123",
  "scene_id": "s456",
  "shot_id": "sh789",
  "preset": "luxury_push_in",
  "input_image_id": "img001",
  "quality_mode": "balanced",
  "working_resolution": [448, 768],
  "duration_sec": 5.0,
  "base_fps": 12,
  "output_fps": 24,
  "camera": {
    "tx_start": 0.00,
    "tx_end": 0.02,
    "ty_start": 0.00,
    "ty_end": -0.01,
    "tz_start": 0.00,
    "tz_end": 0.07,
    "yaw_start_deg": 0.0,
    "yaw_end_deg": 1.2,
    "pitch_start_deg": 0.0,
    "pitch_end_deg": -0.3,
    "fov_start_deg": 72.0,
    "fov_end_deg": 68.0,
    "easing": "ease_in_out"
  },
  "constraints": {
    "max_disocclusion_ratio": 0.10,
    "max_edge_shift_px": 16,
    "protect_reflections": true,
    "foreground_lock_strength": 0.75
  },
  "finishing": {
    "style": "bright_luxury",
    "grain": 0.08,
    "sharpen": 0.15,
    "letterbox": false
  }
}

20. Final recommended build doctrine

If someone else is building this, the most important instruction is this:

Do not start by training a tiny end-to-end video model. Start by building the deterministic geometry pipeline first.

The correct order is:

Perception
Scene graph
Camera planner
Warp renderer
Hole repair
Temporal cleanup
Interpolation
Upscale and export

Only after this baseline is stable should the team invest in:

temporal latent refinement
domain-specific inpainting fine-tuning
multi-photo fusion
premium cloud-assisted modes

21. Summary

The full buildable architecture is:

a local-first macOS engine
built around a layered 2.5D scene representation
controlled by structured real-estate shot presets
rendered with depth/plane reprojection
repaired by localized inpainting
improved with temporal refinement
smoothed through frame interpolation
polished using upscale and cinematic finishing

That is the version that is technically credible, memory-aware, and actually buildable by another team.

If you want, I can next turn this into either:

a module-by-module engineering spec with function signatures and input/output contracts, or
a 90-day implementation roadmap with exact milestones for a small team.