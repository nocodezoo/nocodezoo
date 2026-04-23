# vps_api.py Patch — Quota Integration

Apply these changes to `/opt/video_pipeline/scripts/vps_api.py` on the VPS.

---

## Change 1 — Add imports (near top of file)

```python
import sys
sys.path.insert(0, '/opt/video_pipeline')
from quota_checker import check_quota, notify_video_complete
```

---

## Change 2 — Before starting a job (job submission handler)

Find the function that handles new job submissions and add before the build starts:

```python
async def submit_job(req: GenReq):
    # ── QUOTA CHECK ──────────────────────────────────────────────────
    user_id = req.user_id  # Add user_id field to GenReq if not present
    if not user_id:
        return {"error": "user_id required"}

    try:
        quota = check_quota(user_id)
        if not quota.get("allowed"):
            return {
                "error": "quota_exceeded",
                "remaining": quota.get("remaining"),
                "limit": quota.get("limit"),
            }
    except Exception as e:
        # Fail open on quota service error — log but don't block
        print(f"[vps_api] WARN: quota check failed: {e}")
    # ── END QUOTA CHECK ──────────────────────────────────────────────

    # ... rest of existing job submission code ...
```

---

## Change 3 — On job completion (completion callback)

Find where the job result is returned/stored and add the video-complete call:

```python
    # After job completes successfully
    notify_video_complete(
        job_id=job_id,
        user_id=user_id,
        status="completed"
    )

    # If job failed:
    notify_video_complete(
        job_id=job_id,
        user_id=user_id,
        status="failed"
    )
```

---

## GenReq Update (in vps_api.py)

Add `user_id` to the GenReq model:

```python
class GenReq(BaseModel):
    url: Optional[str] = None
    voice: str = "Sarah"
    max_images: int = 10
    email: Optional[str] = None
    duration: float = 30.0
    ratio: str = "16:9"
    effect: str = "random"
    template: str = "word-focus"
    font_size: int = 55
    text_color: str = "#FFFFFF"
    bg_color: str = "#000000"
    music_url: Optional[str] = None
    music: str = "none"
    cta: Optional[str] = None
    transition: str = "smoothleft"
    images_per_slide: int = 1
    images: Optional[list[str]] = None
    user_id: Optional[int] = None  # ← ADD THIS FIELD
```

---

## Notes

- The quota check is **fail-open**: if the user API is unreachable, jobs still process. This prevents a service dependency from blocking revenue-generating work. But it also means a user could slip through without counting — a background reconciliation job should handle this.
- `notify_video_complete` is **fire-and-forget**: it logs errors but doesn't block the job result.
- The `user_id` field must be added to `GenReq` — it should come from the JWT token in the original request (so it's trusted, not user-supplied).
