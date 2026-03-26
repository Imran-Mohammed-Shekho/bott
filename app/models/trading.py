"""Trading-related schemas for broker execution and persistence."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TradeMode(str, Enum):
    """Application trading mode."""

    PAPER = "paper"
    LIVE = "live"


class OrderSide(str, Enum):
    """Supported market order sides."""

    BUY = "BUY"
    SELL = "SELL"


class PositionCloseSide(str, Enum):
    """Supported position closeout targets."""

    LONG = "long"
    SHORT = "short"
    ALL = "all"


class PositionExposure(BaseModel):
    """One side of an open position."""

    units: float = 0.0
    average_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    trade_ids: List[str] = []


class PositionSummary(BaseModel):
    """Open position snapshot."""

    pair: str
    display_pair: str
    long: PositionExposure
    short: PositionExposure
    margin_used: float = 0.0


class AccountSummary(BaseModel):
    """Broker account summary."""

    account_id: str
    currency: str
    balance: float
    nav: float
    unrealized_pnl: float
    margin_available: float
    margin_used: float
    open_trade_count: int
    open_position_count: int
    pending_order_count: int
    margin_closeout_percent: Optional[float] = None


class MarketOrderRequest(BaseModel):
    """Request payload for opening a market position."""

    pair: str
    side: OrderSide
    units: int = Field(gt=0)
    take_profit_price: Optional[float] = Field(default=None, gt=0.0)
    stop_loss_price: Optional[float] = Field(default=None, gt=0.0)
    request_source: str = "api"
    requested_by: Optional[str] = None


class MarketOrderResponse(BaseModel):
    """Normalized order execution result."""

    mode: TradeMode
    pair: str
    display_pair: str
    side: OrderSide
    units: int
    status: str
    fill_price: Optional[float] = None
    requested_price: Optional[float] = None
    external_order_id: Optional[str] = None
    external_trade_id: Optional[str] = None
    account_id: Optional[str] = None
    message: str
    timestamp: datetime


class ClosePositionRequest(BaseModel):
    """Request payload for closing an open position."""

    side: PositionCloseSide = PositionCloseSide.ALL
    units: Optional[int] = Field(default=None, gt=0)


class ClosePositionResponse(BaseModel):
    """Normalized close-position result."""

    mode: TradeMode
    pair: str
    display_pair: str
    closed_side: PositionCloseSide
    units: str
    status: str
    external_order_id: Optional[str] = None
    realized_pnl: Optional[float] = None
    message: str
    timestamp: datetime


class TradeRecord(BaseModel):
    """Persistent trade log entry."""

    id: str
    mode: TradeMode
    pair: str
    side: Optional[OrderSide] = None
    action: str
    units: str
    status: str
    fill_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    external_order_id: Optional[str] = None
    external_trade_id: Optional[str] = None
    account_id: Optional[str] = None
    request_source: str
    requested_by: Optional[str] = None
    error_message: Optional[str] = None
    request_payload: Dict[str, Any] = {}
    response_payload: Dict[str, Any] = {}
    created_at: datetime
    closed_at: Optional[datetime] = None
