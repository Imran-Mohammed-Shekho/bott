"""Schemas for user-managed execution profiles and one-time connect tokens."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


VALID_SIGNAL_HORIZONS = {"5s", "10s", "30s", "1m"}


class ExecutionConnectToken(BaseModel):
    """One-time token used to open a secure session-connect page."""

    token: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    is_active: bool = True


class UserExecutionProfile(BaseModel):
    """Stored execution settings and encrypted session for a Telegram user."""

    user_id: int
    provider: str = "pocket_option_browser"
    encrypted_session: str
    autotrade_enabled: bool = False
    trade_amount: int = Field(gt=0)
    expiration_label: str = "M5"
    signal_horizon: str = "1m"
    created_at: datetime
    updated_at: datetime

    @validator("signal_horizon")
    def validate_signal_horizon(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_SIGNAL_HORIZONS:
            raise ValueError("Signal horizon must be one of 5s, 10s, 30s, 1m.")
        return normalized


class ExecutionProfileStatus(BaseModel):
    """User-facing view of the stored execution profile."""

    user_id: int
    provider: str
    has_session: bool
    autotrade_enabled: bool
    trade_amount: int
    expiration_label: str
    signal_horizon: str
    created_at: datetime
    updated_at: datetime


class ConnectExecutionRequest(BaseModel):
    """Payload submitted from the secure connect page."""

    storage_state: str
    autotrade_enabled: bool = False
    trade_amount: int = Field(default=1, gt=0)
    expiration_label: str = "M5"
    signal_horizon: str = "1m"

    @validator("signal_horizon")
    def validate_connect_horizon(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_SIGNAL_HORIZONS:
            raise ValueError("Signal horizon must be one of 5s, 10s, 30s, 1m.")
        return normalized
