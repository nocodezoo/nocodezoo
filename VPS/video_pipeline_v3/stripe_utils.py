"""
stripe_utils.py — Stripe Checkout + webhook handlers (test mode by default).
"""

import os
import hmac
import hashlib
import json
from datetime import datetime
from typing import Optional

import stripe
from stripe import StripeClient

# Stripe test mode by default — set STRIPE_LIVE=true env var for production
IS_LIVE = os.getenv("STRIPE_LIVE", "false").lower() == "true"
STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_IDS = {
    # plan_name → Stripe Price ID (created in Stripe dashboard per environment)
    # These are set after creating products in Stripe dashboard
}

if STRIPE_SECRET:
    stripe.api_key = STRIPE_SECRET

APP_URL = os.getenv("APP_URL", "https://app.vybord.com")
SUCCESS_URL = f"{APP_URL}/dashboard?session=ok"
CANCEL_URL = f"{APP_URL}/dashboard?session=cancelled"

# ── Helpers ─────────────────────────────────────────────────────────────────

def get_price_id_for_plan(plan_name: str, price_cents: int) -> Optional[str]:
    """
    Return Stripe Price ID from local map.
    Price IDs are environment-specific — set in STRIPE_PRICE_IDS env JSON.
    """
    import json as _json

    price_map = os.getenv("STRIPE_PRICE_IDS", "{}")
    try:
        price_map = _json.loads(price_map)
    except Exception:
        price_map = {}

    # Fallback: if not in env map, return None (user must create in Stripe dashboard)
    return price_map.get(plan_name)


def create_checkout_session(
    customer_id: Optional[str],
    price_id: str,
    user_id: int,
    user_email: str,
) -> str:
    """
    Create a Stripe Checkout session and return the URL.
    Returns the hosted checkout URL.
    """
    import stripe as stripe_lib

    stripe_lib.api_key = STRIPE_SECRET

    kwargs = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
        "subscription_data": {
            "metadata": {"user_id": str(user_id)},
        },
        "allow_promotion_codes": True,
        "billing_address_collection": "required",
    }

    if customer_id:
        kwargs["customer"] = customer_id
    else:
        kwargs["customer_email"] = user_email

    session = stripe_lib.checkout.Session.create(**kwargs)
    return session.url  # e.g. https://checkout.stripe.com/c/pay/xxx


def create_customer(email: str, user_id: int) -> str:
    """Create a Stripe customer and return customer ID."""
    import stripe as stripe_lib

    stripe_lib.api_key = STRIPE_SECRET
    customer = stripe_lib.customer.create(
        email=email,
        metadata={"user_id": str(user_id)},
    )
    return customer.id


def cancel_subscription(subscription_id: str) -> dict:
    """Cancel a Stripe subscription (at period end)."""
    import stripe as stripe_lib

    stripe_lib.api_key = STRIPE_SECRET
    sub = stripe_lib.subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
    )
    return {"subscription_id": sub.id, "cancels_at": sub.cancel_at}


def get_subscription_status(subscription_id: str) -> str:
    """Return current subscription status from Stripe."""
    import stripe as stripe_lib

    stripe_lib.api_key = STRIPE_SECRET
    sub = stripe_lib.subscription.retrieve(subscription_id)
    return sub.status  # active, trialing, past_due, canceled, etc.


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """
    Verify Stripe webhook and return the event dict.
    Raises ValueError if signature is invalid.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return event
    except stripe.SignatureVerificationError:
        raise ValueError("Invalid Stripe webhook signature")


def handle_checkout_completed(conn, event) -> Optional[int]:
    """
    Handle checkout.session.completed.
    Upgrades user to paid plan.
    Returns user_id if found.
    """
    session = event["data"]["object"]
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    user_id_str = session.get("metadata", {}).get("user_id")

    if not user_id_str:
        # Try to look up user by Stripe customer ID
        user_row = conn.execute(
            "SELECT id FROM users WHERE stripe_customer_id = ?",
            (customer_id,),
        ).fetchone()
        if not user_row:
            return None
        user_id = user_row["id"]
    else:
        user_id = int(user_id_str)

    # Get the subscription's price ID to determine plan
    if subscription_id:
        import stripe as stripe_lib
        stripe_lib.api_key = STRIPE_SECRET
        sub = stripe_lib.subscription.retrieve(subscription_id)
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_row = conn.execute(
            "SELECT id FROM plans WHERE stripe_price_id = ?", (price_id,)
        ).fetchone()
        if plan_row:
            plan_id = plan_row["id"]
        else:
            plan_id = 2  # default to Pro if unknown
    else:
        plan_id = 2

    conn.execute(
        """
        UPDATE users
        SET stripe_customer_id = ?, stripe_subscription_id = ?, plan_id = ?, is_active = 1
        WHERE id = ?
        """,
        (customer_id, subscription_id, plan_id, user_id),
    )
    conn.execute(
        """
        INSERT INTO payments (user_id, stripe_payment_intent_id, stripe_subscription_id,
                             amount_cents, status)
        VALUES (?, ?, ?, ?, 'succeeded')
        """,
        (user_id, session.get("payment_intent"), subscription_id, session.get("amount_total", 0)),
    )
    conn.commit()
    return user_id


def handle_subscription_updated(conn, event) -> Optional[int]:
    """Handle customer.subscription.updated — sync plan changes."""
    sub = event["data"]["object"]
    customer_id = sub.get("customer")
    status = sub.get("status")
    subscription_id = sub.get("id")

    user_row = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,)
    ).fetchone()
    if not user_row:
        return None
    user_id = user_row["id"]

    if status == "active":
        # Sync plan
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_row = conn.execute(
            "SELECT id FROM plans WHERE stripe_price_id = ?", (price_id,)
        ).fetchone()
        plan_id = plan_row["id"] if plan_row else 1
        conn.execute(
            "UPDATE users SET plan_id = ?, is_active = 1 WHERE id = ?",
            (plan_id, user_id),
        )
    elif status in ("past_due", "unpaid"):
        conn.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?", (user_id,)
        )
    elif status == "canceled":
        conn.execute(
            "UPDATE users SET plan_id = 1, is_active = 1, stripe_subscription_id = NULL WHERE id = ?",
            (user_id,),
        )
    conn.commit()
    return user_id


def handle_payment_failed(conn, event) -> Optional[int]:
    """Handle invoice.payment_failed — mark user at risk."""
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer")

    user_row = conn.execute(
        "SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,)
    ).fetchone()
    if not user_row:
        return None

    user_id = user_row["id"]
    conn.execute(
        "UPDATE users SET is_active = 0 WHERE id = ?", (user_id,)
    )
    conn.commit()
    return user_id
