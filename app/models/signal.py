"""Pydantic schemas used across services, API, and bot layers."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


HORIZONS: List[str] = ["5s", "10s", "30s", "1m"]


class SignalLabel(str, Enum):
    """Discrete signal classes for the classifier output."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class MarketSnapshot(BaseModel):
    """Latest market quote snapshot."""

    pair: str
    bid: float
    ask: float
    mid_price: float
    spread: float
    timestamp: datetime


class FeatureVector(BaseModel):
    """Feature payload passed into the prediction provider."""

    pair: str
    timestamp: datetime
    values: Dict[str, float]


class HorizonSignal(BaseModel):
    """Signal and confidence score for a single horizon."""

    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=1.0)


class SignalResponse(BaseModel):
    """Full response returned to API clients and Telegram users."""

    pair: str
    display_pair: str
    signals: Dict[str, HorizonSignal]
    current_mid_price: float
    spread: float
    timestamp: datetime
    risk_warning: str
    disclaimer: str


class SubscriptionRecord(BaseModel):
    """Tracked alert subscription for a Telegram chat or API client."""

    chat_id: int
    user_id: Optional[int] = None
    pair: str
    interval_seconds: int
    created_at: datetime


class SubscriptionRequest(BaseModel):
    """Request payload for creating a scheduled watch."""

    chat_id: int
    user_id: Optional[int] = None
    pair: str
    interval_seconds: int = Field(default=30, gt=0)


class HealthResponse(BaseModel):
    """Simple health check response."""

    status: str
    app_name: str
    supported_pairs: int
    market_data_provider: str
    prediction_provider: str
    trade_mode: str
    persistence_backend: str


class PairsResponse(BaseModel):
    """List of supported trading pairs."""

    pairs: List[str]


class SubscriptionDeleteResponse(BaseModel):
    """Result of deleting a subscription."""

    removed: bool
    pair: str
