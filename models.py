"""
models.py — Pydantic schemas for all API entities.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailRequest(BaseModel):
    token: str


# ── User / Profile ─────────────────────────────────────────────────────────

class UserPublic(BaseModel):
    id: int
    email: str
    plan_id: int
    plan_name: str
    videos_generated: int
    monthly_limit: int
    is_admin: bool
    email_verified: bool
    created_at: str

    class Config:
        from_attributes = True


class UserDetail(BaseModel):
    id: int
    email: str
    plan_id: int
    plan_name: str
    videos_generated: int
    monthly_limit: int
    is_admin: bool
    email_verified: bool
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]
    is_active: bool
    created_at: str
    last_login: Optional[str]


class UpdateProfile(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)


# ── Plan ───────────────────────────────────────────────────────────────────

class PlanResponse(BaseModel):
    id: int
    name: str
    monthly_limit: int
    price_monthly_cents: int

    class Config:
        from_attributes = True


class QuotaResponse(BaseModel):
    allowed: bool
    remaining: int
    limit: int  # -1 = unlimited
    videos_generated: int


# ── Video ──────────────────────────────────────────────────────────────────

class VideoRecord(BaseModel):
    id: int
    job_id: str
    status: str
    created_at: str
    completed_at: Optional[str]

    class Config:
        from_attributes = True


class VideoCompletePayload(BaseModel):
    job_id: str
    user_id: int
    status: str = "completed"  # completed | failed


# ── Stripe ─────────────────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    plan_id: int


class StripeCheckoutResponse(BaseModel):
    checkout_url: str


class StripeWebhookPayload(BaseModel):
    raw: dict


# ── Admin ──────────────────────────────────────────────────────────────────

class AdminUserList(BaseModel):
    users: list[UserDetail]
    total: int


class AdminPlanUpdate(BaseModel):
    name: str
    monthly_limit: int = -1
    price_monthly_cents: int


class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    plan_id: Optional[int] = None


# ── Internal ───────────────────────────────────────────────────────────────

class GenerateCheckResponse(BaseModel):
    allowed: bool
    remaining: int
    limit: int
    error: Optional[str] = None
