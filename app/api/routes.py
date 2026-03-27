"""FastAPI routes for the forex signal backend."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from app.bootstrap import AppContext
from app.models.execution import (
    ConnectExecutionRequest,
    ExecutionProfileStatus,
    RemoteBrowserClickRequest,
    RemoteBrowserKeyRequest,
    RemoteBrowserTypeRequest,
)
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


@router.get("/execution/profile/{user_id}", response_model=ExecutionProfileStatus, dependencies=[Depends(require_admin_key)])
async def execution_profile(user_id: int, request: Request) -> ExecutionProfileStatus:
    """Return the stored execution profile status for a user."""

    app_context = get_app_context(request)
    profile = await app_context.execution_profile_service.get_profile_status(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Execution profile not found.")
    return profile


@router.get("/connect/{token}", response_class=HTMLResponse, include_in_schema=False)
async def connect_page(token: str, request: Request) -> HTMLResponse:
    """Serve a minimal secure session-connect page."""

    app_context = get_app_context(request)
    connect_token = await app_context.execution_profile_service.get_connect_token(token)
    if connect_token is None or not connect_token.is_active or connect_token.used_at is not None:
        raise HTTPException(status_code=404, detail="Connect link is invalid or expired.")

    html = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Connect Pocket Option Session</title>
    <style>
      body {{ font-family: sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; }}
      input, select {{ width: 100%; margin-top: 8px; margin-bottom: 16px; }}
      .screen-wrap {{ border: 1px solid #ccc; border-radius: 12px; overflow: hidden; background: #111; }}
      #screen {{ width: 100%; display: block; touch-action: manipulation; }}
      .row {{ display: flex; gap: 12px; }}
      .row > * {{ flex: 1; }}
      button {{ padding: 12px 18px; cursor: pointer; }}
      .status {{ margin-top: 16px; white-space: pre-wrap; }}
    </style>
  </head>
  <body>
    <h1>Connect Pocket Option Session</h1>
    <p>Use the live remote browser below to log in. When you reach the trading screen, press Save Session.</p>
    <div class="screen-wrap">
      <img id="screen" alt="Remote browser screen" />
    </div>
    <div class="row">
      <div>
        <label>Type into focused field</label>
        <input id="type_text" type="text" />
      </div>
      <div style="display:flex;align-items:end;">
        <button id="type_button">Type Text</button>
      </div>
    </div>
    <div class="row">
      <button data-key="Tab">Tab</button>
      <button data-key="Enter">Enter</button>
      <button data-key="Backspace">Backspace</button>
      <button id="refresh_button">Refresh Screen</button>
    </div>
    <label>Trade amount</label>
    <input id="trade_amount" type="number" min="1" value="1" />
    <label>Expiration label</label>
    <input id="expiration_label" type="text" value="M5" />
    <label>Signal horizon</label>
    <select id="signal_horizon">
      <option value="5s">5s</option>
      <option value="10s">10s</option>
      <option value="30s">30s</option>
      <option value="1m" selected>1m</option>
    </select>
    <label><input id="autotrade_enabled" type="checkbox" /> Enable autotrade</label>
    <div>
      <button id="submit">Save Session</button>
      <button id="cancel">Close Session</button>
    </div>
    <div id="status" class="status"></div>
    <script>
      const screen = document.getElementById("screen");
      const status = document.getElementById("status");
      async function refreshScreen() {{
        await fetch("/api/v1/connect/{token}/start", {{ method: "POST" }});
        screen.src = "/api/v1/connect/{token}/screenshot?ts=" + Date.now();
      }}
      screen.addEventListener("click", async (event) => {{
        const rect = screen.getBoundingClientRect();
        const payload = {{
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          rendered_width: Math.round(rect.width),
          rendered_height: Math.round(rect.height),
        }};
        await fetch("/api/v1/connect/{token}/click", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("type_button").addEventListener("click", async () => {{
        const text = document.getElementById("type_text").value;
        await fetch("/api/v1/connect/{token}/type", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ text }}),
        }});
        setTimeout(refreshScreen, 400);
      }});
      document.querySelectorAll("[data-key]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          await fetch("/api/v1/connect/{token}/key", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ key: button.dataset.key }}),
          }});
          setTimeout(refreshScreen, 400);
        }});
      }});
      document.getElementById("refresh_button").addEventListener("click", refreshScreen);
      document.getElementById("submit").addEventListener("click", async () => {{
        const payload = {{
          trade_amount: Number(document.getElementById("trade_amount").value || "1"),
          expiration_label: document.getElementById("expiration_label").value,
          signal_horizon: document.getElementById("signal_horizon").value,
          autotrade_enabled: document.getElementById("autotrade_enabled").checked,
          storage_state: "{{}}",
        }};
        const response = await fetch("/api/v1/connect/{token}/save", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        status.textContent = await response.text();
      }});
      document.getElementById("cancel").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/close", {{ method: "POST" }});
        status.textContent = "Remote session closed.";
      }});
      refreshScreen();
      setInterval(refreshScreen, 2500);
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)


@router.post("/connect/{token}", response_model=ExecutionProfileStatus, include_in_schema=False)
async def connect_session(
    token: str,
    payload: ConnectExecutionRequest,
    request: Request,
) -> ExecutionProfileStatus:
    """Consume a connect token and store the encrypted execution profile."""

    app_context = get_app_context(request)
    try:
        return await app_context.execution_profile_service.connect_user(
            token=token,
            storage_state_json=payload.storage_state,
            autotrade_enabled=payload.autotrade_enabled,
            trade_amount=payload.trade_amount,
            expiration_label=payload.expiration_label,
            signal_horizon=payload.signal_horizon,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connect/{token}/start", include_in_schema=False)
async def start_remote_connect(token: str, request: Request) -> dict:
    """Launch or reuse the hosted remote browser for this connect token."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.ensure_session(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ready"}


@router.get("/connect/{token}/screenshot", include_in_schema=False)
async def remote_connect_screenshot(token: str, request: Request) -> Response:
    """Return the current browser screenshot for the connect session."""

    app_context = get_app_context(request)
    try:
        screenshot = await app_context.remote_browser_connect_service.get_screenshot(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=screenshot, media_type="image/png")


@router.post("/connect/{token}/click", include_in_schema=False)
async def remote_connect_click(
    token: str,
    payload: RemoteBrowserClickRequest,
    request: Request,
) -> dict:
    """Send a tap/click into the hosted remote browser."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.click(
            token=token,
            x=payload.x,
            y=payload.y,
            rendered_width=payload.rendered_width,
            rendered_height=payload.rendered_height,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "clicked"}


@router.post("/connect/{token}/type", include_in_schema=False)
async def remote_connect_type(
    token: str,
    payload: RemoteBrowserTypeRequest,
    request: Request,
) -> dict:
    """Type text into the focused field of the hosted remote browser."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.type_text(token, payload.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "typed"}


@router.post("/connect/{token}/key", include_in_schema=False)
async def remote_connect_key(
    token: str,
    payload: RemoteBrowserKeyRequest,
    request: Request,
) -> dict:
    """Press a keyboard key in the hosted remote browser."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.press_key(token, payload.key)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "pressed"}


@router.post("/connect/{token}/save", response_model=ExecutionProfileStatus, include_in_schema=False)
async def remote_connect_save(
    token: str,
    payload: ConnectExecutionRequest,
    request: Request,
) -> ExecutionProfileStatus:
    """Capture the hosted browser storage state and store it encrypted."""

    app_context = get_app_context(request)
    try:
        return await app_context.remote_browser_connect_service.save_session(
            token=token,
            autotrade_enabled=payload.autotrade_enabled,
            trade_amount=payload.trade_amount,
            expiration_label=payload.expiration_label,
            signal_horizon=payload.signal_horizon,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connect/{token}/close", include_in_schema=False)
async def remote_connect_close(token: str, request: Request) -> dict:
    """Close and discard the hosted remote browser session."""

    app_context = get_app_context(request)
    await app_context.remote_browser_connect_service.close_session(token)
    return {"status": "closed"}
