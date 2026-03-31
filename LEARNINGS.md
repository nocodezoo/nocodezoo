# LEARNINGS.md — Vybord User Management System

## Lesson 1: Can't SSH interactively — need a deployment strategy

**Problem:** SSH with password auth can't be done via `exec` tool (no TTY for password prompt).

**Solution found:** Used `sshpass` (available on the Mac) to pass password non-interactively in the `scp` and remote command pipeline. Alternatively: `python3 -c "import paramiko; ..."` via exec — but sshpass is simpler.

**Lesson:** For future VPS work, consider: (a) setting up SSH key-based auth ahead of time, or (b) using a web-deploy pattern where the file is written locally and a PHP script on Hostinger accepts base64-encoded file content via HTTP POST.

**Better approach for next time:** Set up SSH keys in the boot session so all future VPS work is key-based and seamless.

---

## Lesson 2: Quota enforcement must be atomic

**Problem:** A user at 1 video remaining could send 3 concurrent requests and slip through all 3 if the check and increment aren't atomic.

**Initial flawed pattern:**
```
if check_quota(user_id) → allowed (1 remaining):
    # 3 concurrent requests pass this check
    process_job()
    increment_count()  # all 3 increment — user got 3 free videos
```

**Correct pattern:** Use a DB transaction with `UPDATE ... WHERE videos_generated < monthly_limit` — the DB row lock makes it atomic. The `check_quota()` in database.py already does this via SQLite's sequential execution. For Postgres (future scale): use `SELECT ... FOR UPDATE`.

---

## Lesson 3: Fail-open vs fail-closed on quota service

**Problem:** If user_api goes down, do we block all video generation (fail-closed, secure but no revenue) or allow it through (fail-open, revenue but free videos slip through)?

**Chosen:** Fail-open for now. A background reconciliation job should run nightly to catch any missed counts.

**Better:** Add a `video_reservations` table — when a job starts, reserve a slot (`UPDATE users SET videos_reserved = videos_reserved + 1 WHERE ... AND videos_reserved < limit`). Reconciliation then reconciles reservations vs. completions.

---

## Lesson 4: Stripe webhook delivery is not guaranteed

**Problem:** Stripe webhooks can miss, retry, or arrive late. If `checkout.session.completed` is missed, user pays but plan doesn't upgrade.

**Solution in place:** `stripe_events` table with idempotency guard — event ID stored, duplicates skipped. But the event still needs to arrive.

**Better:** Add a nightly Stripe reconciliation job that fetches all active subscriptions and syncs user plans. Would catch missed webhooks.

---

## Lesson 5: Planning the data model before code would have saved time

**Initial approach:** Started with API routes, then realized user_id wasn't in GenReq.

**What should have happened:** The GenReq model update (adding user_id) is a cross-system contract change — needs coordination with the browser-side code in send.php AND the vps_api.py. This is a multi-system interface, not just a backend change.

**Lesson:** When building multi-system integrations, define the interface contracts first (in CODING_PLAN.md Phase 2), document them, and get sign-off before implementing.
