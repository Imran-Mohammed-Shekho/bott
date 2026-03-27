"""Schemas for access grants, tokens, and per-user request quotas."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccessTokenRecord(BaseModel):
    """Admin-issued access token for onboarding a user."""

    token: str
    daily_limit: int = Field(gt=0)
    issued_by: int
    issued_at: datetime
    redeemed_by: Optional[int] = None
    redeemed_at: Optional[datetime] = None
    is_active: bool = True


class UserAccessRecord(BaseModel):
    """Granted bot access for a Telegram user."""

    user_id: int
    username: Optional[str] = None
    daily_limit: int = Field(gt=0)
    is_active: bool = True
    granted_at: datetime
    granted_via_token: Optional[str] = None


class UserQuotaStatus(BaseModel):
    """Resolved quota state for a user."""

    user_id: int
    username: Optional[str] = None
    daily_limit: int = Field(ge=0)
    used_today: int = Field(ge=0)
    remaining_today: int = Field(ge=0)
    usage_date: date
    is_active: bool = True
    granted_at: datetime
    granted_via_token: Optional[str] = None
