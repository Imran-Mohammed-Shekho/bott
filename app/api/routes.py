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
    RemoteBrowserLoginRequest,
    RemoteBrowserScrollRequest,
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
      body {{ font-family: sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; line-height: 1.45; }}
      h1, h2 {{ margin-bottom: 8px; }}
      p, li {{ color: #333; }}
      input, select {{ width: 100%; margin-top: 8px; margin-bottom: 16px; font-size: 16px; padding: 12px; box-sizing: border-box; }}
      .screen-wrap {{ border: 1px solid #ccc; border-radius: 12px; overflow: hidden; background: #111; }}
      #screen {{ width: 100%; display: block; touch-action: manipulation; }}
      .row {{ display: flex; gap: 12px; }}
      .row > * {{ flex: 1; }}
      button {{ padding: 12px 18px; cursor: pointer; font-size: 16px; }}
      .status {{ margin-top: 16px; white-space: pre-wrap; padding: 12px; border-radius: 8px; background: #f4f4f4; }}
      .hint {{ font-size: 14px; color: #666; margin-top: -8px; margin-bottom: 16px; }}
      .steps {{ background: #f9f9ff; border: 1px solid #dfe4ff; border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; }}
      .panel {{ background: #fcfcfc; border: 1px solid #e5e5e5; border-radius: 12px; padding: 14px; margin-top: 16px; }}
      .panel h2 {{ margin-top: 0; }}
      .screen-box {{ position: relative; }}
      .tap-marker {{
        position: absolute;
        width: 22px;
        height: 22px;
        border-radius: 999px;
        background: rgba(255, 64, 64, 0.85);
        border: 2px solid white;
        transform: translate(-50%, -50%);
        pointer-events: none;
        display: none;
      }}
      .toolbar {{ margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
      .big-button {{ min-width: 180px; font-weight: 600; }}
    </style>
  </head>
  <body>
    <h1>Connect Pocket Option Session</h1>
    <div class="steps">
      <h2>How To Use This Page</h2>
      <ol>
        <li>Tap the exact field or button you want inside the remote browser image.</li>
        <li>Use the text boxes below to type into the selected field.</li>
        <li>Use Tab / Enter / Backspace if the site needs keyboard navigation.</li>
        <li>Use Scroll Down if the login button is lower on the page.</li>
        <li>When Pocket Option is fully logged in and the trading page is visible, press Save Session.</li>
      </ol>
    </div>
    <p><strong>Current target:</strong> <span id="target_label">No field selected yet</span></p>
    <p><strong>Last tap:</strong> <span id="tap_label">none</span></p>
    <div class="screen-wrap screen-box">
      <img id="screen" alt="Remote browser screen" />
      <div id="tap_marker" class="tap-marker"></div>
    </div>
    <div class="panel">
      <h2>Fast Login</h2>
      <p>Type the account credentials here, then press <strong>Login To Website</strong>. The server will try to fill the login form for you.</p>
      <div class="row">
        <div>
          <label>Email / Username</label>
          <input id="type_text" type="text" placeholder="Type email or username here" />
          <div class="hint">This is for the Pocket Option login screen.</div>
        </div>
        <div style="display:flex;align-items:end;">
          <button id="login_button" class="big-button">Login To Website</button>
        </div>
      </div>
      <div class="row">
        <div>
          <label>Password</label>
          <input id="password_text" type="password" placeholder="Type password here" />
          <div class="hint">If automatic login fails, use the fallback manual controls below.</div>
        </div>
        <div style="display:flex;align-items:end;">
          <button id="refresh_button" class="big-button">Refresh Screen</button>
        </div>
      </div>
      <p><strong>If the page changes after login, wait 2-3 seconds and check the screenshot.</strong></p>
    </div>
    <div class="panel">
      <h2>Fallback Manual Controls</h2>
      <p>If automatic login does not work on the current Pocket Option screen, use these manual controls.</p>
      <div class="toolbar">
        <button id="type_button" class="big-button">Send Text To Focused Field</button>
        <button id="tab_to_password" class="big-button">Go To Next Field</button>
        <button id="password_button" class="big-button">Send Password To Focused Field</button>
        <button id="submit_login" class="big-button">Press Enter / Submit</button>
        <button id="backspace_button">Delete Last Character</button>
      </div>
      <div class="toolbar">
        <button id="scroll_down">Scroll Down</button>
        <button id="scroll_up">Scroll Up</button>
        <button data-key="Tab">Tab</button>
        <button data-key="Enter">Enter</button>
        <button data-key="Backspace">Backspace</button>
      </div>
    </div>
    <div class="panel">
      <h2>Autotrade Settings After Login</h2>
    <label>Trade amount</label>
    <input id="trade_amount" type="number" min="1" value="1" />
    <div class="hint">This is the amount the bot will use later when executing orders for this user.</div>
    <label>Expiration label</label>
    <input id="expiration_label" type="text" value="M5" />
    <div class="hint">Example: M1, M5, M15. It should match Pocket Option labels.</div>
    <label>Signal horizon</label>
    <select id="signal_horizon">
      <option value="5s">5s</option>
      <option value="10s">10s</option>
      <option value="30s">30s</option>
      <option value="1m" selected>1m</option>
    </select>
    <div class="hint">This tells the bot which signal horizon to use for automatic execution.</div>
    <label><input id="autotrade_enabled" type="checkbox" /> Enable autotrade after saving this session</label>
    </div>
    <div>
      <button id="submit">Save Session</button>
      <button id="cancel">Close Session</button>
    </div>
    <div id="status" class="status"></div>
    <script>
      const screen = document.getElementById("screen");
      const status = document.getElementById("status");
      const targetLabel = document.getElementById("target_label");
      const tapLabel = document.getElementById("tap_label");
      const tapMarker = document.getElementById("tap_marker");
      let lastTapX = null;
      let lastTapY = null;
      async function refreshScreen() {{
        await fetch("/api/v1/connect/{token}/start", {{ method: "POST" }});
        screen.src = "/api/v1/connect/{token}/screenshot?ts=" + Date.now();
      }}
      screen.addEventListener("click", async (event) => {{
        const rect = screen.getBoundingClientRect();
        lastTapX = event.clientX - rect.left;
        lastTapY = event.clientY - rect.top;
        tapLabel.textContent = "x=" + Math.round(lastTapX) + ", y=" + Math.round(lastTapY);
        targetLabel.textContent = "Focused the area you tapped";
        tapMarker.style.left = lastTapX + "px";
        tapMarker.style.top = lastTapY + "px";
        tapMarker.style.display = "block";
        const payload = {{
          x: lastTapX,
          y: lastTapY,
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
      document.getElementById("login_button").addEventListener("click", async () => {{
        status.textContent = "Trying automatic login...";
        const response = await fetch("/api/v1/connect/{token}/login", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            username: document.getElementById("type_text").value,
            password: document.getElementById("password_text").value
          }}),
        }});
        status.textContent = await response.text();
        setTimeout(refreshScreen, 1200);
      }});
      document.getElementById("type_button").addEventListener("click", async () => {{
        const text = document.getElementById("type_text").value;
        await fetch("/api/v1/connect/{token}/type", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ text }}),
        }});
        targetLabel.textContent = "Sent email / username to the focused field";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("tab_to_password").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/key", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ key: "Tab" }}),
        }});
        targetLabel.textContent = "Moved focus to the next field, usually password";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("password_button").addEventListener("click", async () => {{
        const text = document.getElementById("password_text").value;
        await fetch("/api/v1/connect/{token}/type", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ text }}),
        }});
        targetLabel.textContent = "Sent password to the focused field";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("submit_login").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/key", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ key: "Enter" }}),
        }});
        targetLabel.textContent = "Submitted login form with Enter";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("backspace_button").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/key", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ key: "Backspace" }}),
        }});
        targetLabel.textContent = "Deleted one character from the focused field";
        setTimeout(refreshScreen, 400);
      }});
      document.querySelectorAll("[data-key]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          await fetch("/api/v1/connect/{token}/key", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ key: button.dataset.key }}),
          }});
          targetLabel.textContent = "Pressed key: " + button.dataset.key;
          setTimeout(refreshScreen, 400);
        }});
      }});
      document.getElementById("scroll_down").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/scroll", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ delta_y: 600 }}),
        }});
        targetLabel.textContent = "Scrolled down";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("scroll_up").addEventListener("click", async () => {{
        await fetch("/api/v1/connect/{token}/scroll", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ delta_y: -600 }}),
        }});
        targetLabel.textContent = "Scrolled up";
        setTimeout(refreshScreen, 400);
      }});
      document.getElementById("refresh_button").addEventListener("click", refreshScreen);
      document.getElementById("submit").addEventListener("click", async () => {{
        status.textContent = "Saving encrypted session...";
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


@router.post("/connect/{token}/scroll", include_in_schema=False)
async def remote_connect_scroll(
    token: str,
    payload: RemoteBrowserScrollRequest,
    request: Request,
) -> dict:
    """Scroll the hosted remote browser."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.scroll(token, payload.delta_y)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "scrolled"}


@router.post("/connect/{token}/login", include_in_schema=False)
async def remote_connect_login(
    token: str,
    payload: RemoteBrowserLoginRequest,
    request: Request,
) -> dict:
    """Attempt to log into the target website using typed credentials."""

    app_context = get_app_context(request)
    try:
        await app_context.remote_browser_connect_service.attempt_login(
            token=token,
            username=payload.username,
            password=payload.password,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "login_submitted"}


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
