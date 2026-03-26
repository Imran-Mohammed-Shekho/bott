"""FastAPI routes for the forex signal backend."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.bootstrap import AppContext
from app.models.signal import (
    HealthResponse,
    PairsResponse,
    SignalResponse,
    SubscriptionDeleteResponse,
    SubscriptionRecord,
    SubscriptionRequest,
)
from app.models.trading import (
    AccountSummary,
    ClosePositionRequest,
    ClosePositionResponse,
    MarketOrderRequest,
    MarketOrderResponse,
    PositionSummary,
    TradeRecord,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def get_app_context(request: Request) -> AppContext:
    """Return the application context stored on the FastAPI app."""

    return request.app.state.app_context


def require_admin_key(
    request: Request,
    x_admin_key: Optional[str] = Header(default=None),
) -> None:
    """Protect administrative trading endpoints."""

    settings = get_app_context(request).settings
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key.")


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return a basic health check response."""

    app_context = get_app_context(request)
    return HealthResponse(
        status="ok",
        app_name=app_context.settings.app_name,
        supported_pairs=len(app_context.settings.available_pairs),
        market_data_provider=app_context.settings.market_data_provider,
        prediction_provider=app_context.settings.prediction_provider,
        trade_mode=app_context.settings.trade_mode,
        persistence_backend="supabase" if app_context.persistence is not None else "memory",
    )


@router.get("/pairs", response_model=PairsResponse)
async def pairs(request: Request) -> PairsResponse:
    """Return supported forex pairs."""

    app_context = get_app_context(request)
    return PairsResponse(
        pairs=[
            app_context.signal_service.display_pair(pair)
            for pair in app_context.signal_service.list_pairs()
        ]
    )


@router.get("/signal/{pair}", response_model=SignalResponse)
async def signal(pair: str, request: Request) -> SignalResponse:
    """Return the latest signal response for a pair."""

    app_context = get_app_context(request)
    try:
        return await app_context.signal_service.get_signal(pair)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Signal generation failed for pair %s", pair)
        raise HTTPException(status_code=500, detail="Internal signal generation error.") from exc


@router.post("/subscriptions", response_model=SubscriptionRecord)
async def create_subscription(
    payload: SubscriptionRequest,
    request: Request,
) -> SubscriptionRecord:
    """Register a watch subscription in memory."""

    app_context = get_app_context(request)
    try:
        pair = app_context.signal_service.resolve_pair(payload.pair)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = app_context.settings
    if payload.interval_seconds < settings.min_watch_interval_seconds:
        raise HTTPException(
            status_code=400,
            detail=f"Interval must be at least {settings.min_watch_interval_seconds} seconds.",
        )
    if payload.interval_seconds > settings.max_watch_interval_seconds:
        raise HTTPException(
            status_code=400,
            detail=f"Interval must be at most {settings.max_watch_interval_seconds} seconds.",
        )

    return await app_context.subscription_service.upsert(
        chat_id=payload.chat_id,
        user_id=payload.user_id or payload.chat_id,
        pair=pair,
        interval_seconds=payload.interval_seconds,
    )


@router.get("/subscriptions/{chat_id}", response_model=List[SubscriptionRecord])
async def list_subscriptions(chat_id: int, request: Request) -> List[SubscriptionRecord]:
    """List active subscriptions for a chat ID."""

    app_context = get_app_context(request)
    return await app_context.subscription_service.list_for_chat(chat_id)


@router.delete(
    "/subscriptions/{chat_id}/{pair}",
    response_model=SubscriptionDeleteResponse,
)
async def delete_subscription(
    chat_id: int,
    pair: str,
    request: Request,
) -> SubscriptionDeleteResponse:
    """Delete a watch subscription from memory."""

    app_context = get_app_context(request)
    normalized_pair = app_context.signal_service.normalize_pair(pair)
    removed = await app_context.subscription_service.remove(chat_id, normalized_pair)
    return SubscriptionDeleteResponse(
        removed=removed,
        pair=app_context.signal_service.display_pair(normalized_pair),
    )


@router.get("/account", response_model=AccountSummary, dependencies=[Depends(require_admin_key)])
async def account_summary(request: Request) -> AccountSummary:
    """Return the trading account summary."""

    app_context = get_app_context(request)
    try:
        return await app_context.trading_service.get_account_summary()
    except Exception as exc:
        logger.exception("Account summary failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/positions",
    response_model=List[PositionSummary],
    dependencies=[Depends(require_admin_key)],
)
async def open_positions(request: Request) -> List[PositionSummary]:
    """Return open broker positions."""

    app_context = get_app_context(request)
    try:
        return await app_context.trading_service.list_open_positions()
    except Exception as exc:
        logger.exception("Listing positions failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/orders/market",
    response_model=MarketOrderResponse,
    dependencies=[Depends(require_admin_key)],
)
async def market_order(payload: MarketOrderRequest, request: Request) -> MarketOrderResponse:
    """Create a market order."""

    app_context = get_app_context(request)
    try:
        return await app_context.trading_service.place_market_order(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Market order failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/positions/{pair}/close",
    response_model=ClosePositionResponse,
    dependencies=[Depends(require_admin_key)],
)
async def close_position(
    pair: str,
    payload: ClosePositionRequest,
    request: Request,
) -> ClosePositionResponse:
    """Close an open position."""

    app_context = get_app_context(request)
    try:
        return await app_context.trading_service.close_position(
            pair=pair,
            request=payload,
            request_source="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Close position failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/trades",
    response_model=List[TradeRecord],
    dependencies=[Depends(require_admin_key)],
)
async def recent_trades(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> List[TradeRecord]:
    """Return recent trade log entries."""

    app_context = get_app_context(request)
    return await app_context.trading_service.list_recent_trades(limit=limit)
