"""
quota_checker.py — Quota check + video-complete client.
Imported by vps_api.py to enforce user quotas before/during video builds.
"""

import os
import sys
import urllib.request
import urllib.error
import json
from typing import Optional

USER_API_BASE = os.getenv("USER_API_BASE", "http://127.0.0.1:8001")


class QuotaExceeded(Exception):
    """Raised when user has hit their video generation limit."""
    def __init__(self, remaining: int, limit: int):
        self.remaining = remaining
        self.limit = limit
        super().__init__(f"Quota exceeded: {remaining}/{limit} videos remaining")


def check_quota(user_id: int) -> dict:
    """
    Call /api/internal/check-quota/{user_id} on the user API.
    Returns {"allowed": bool, "remaining": int, "limit": int, "error": str|None}.
    Raises QuotaExceeded if limit is reached.
    """
    url = f"{USER_API_BASE}/api/internal/check-quota/{user_id}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        # Fail open if user API is unreachable — log but don't block jobs
        print(f"[quota_checker] WARN: could not reach user API: {e}", flush=True)
        return {"allowed": True, "remaining": -1, "limit": -1, "error": "user_api_unreachable"}
    except Exception as e:
        print(f"[quota_checker] ERROR: {e}", flush=True)
        return {"allowed": True, "remaining": -1, "limit": -1, "error": str(e)}

    if not data.get("allowed"):
        raise QuotaExceeded(
            remaining=data.get("remaining", 0),
            limit=data.get("limit", 0),
        )
    return data


def notify_video_complete(job_id: str, user_id: int, status: str = "completed") -> bool:
    """
    Call /api/internal/video-complete to increment the user's video count.
    Returns True on success, False on failure.
    """
    url = f"{USER_API_BASE}/api/internal/video-complete"
    payload = json.dumps({"job_id": job_id, "user_id": user_id, "status": status}).encode()
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"[quota_checker] WARN: video-complete failed for job {job_id}: {e}", flush=True)
        return False


if __name__ == "__main__":
    # Quick CLI test
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    result = check_quota(user_id)
    print(f"Quota check for user {user_id}: {result}")
