"""Playwright-backed browser automation for Pocket Option execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from app.config.settings import Settings
from app.models.interfaces import AbstractExecutionProvider
from app.models.trading import (
    AccountSummary,
    ClosePositionRequest,
    ClosePositionResponse,
    MarketOrderRequest,
    MarketOrderResponse,
    OrderSide,
    PositionSummary,
    TradeMode,
)
from app.services.execution_profiles import ExecutionProfileService
from app.services.signal_service import SignalService


class PocketOptionBrowserProvider(AbstractExecutionProvider):
    """Execute trades by driving an authenticated Pocket Option browser session."""

    def __init__(self, settings: Settings, execution_profile_service: ExecutionProfileService):
        self._settings = settings
        self._execution_profile_service = execution_profile_service
        self._lock = None

    async def get_account_summary(self) -> AccountSummary:
        raise RuntimeError("Pocket Option browser execution does not expose account summary.")

    async def list_open_positions(self) -> List[PositionSummary]:
        raise RuntimeError("Pocket Option browser execution does not expose open positions.")

    async def place_market_order(self, request: MarketOrderRequest) -> MarketOrderResponse:
        """Open a browser session, switch the asset, set stake, and click direction."""

        async with self._get_lock():
            playwright, browser, page = await self._open_authenticated_page(request)
            try:
                await self._select_asset(page, request.pair)
                await self._set_expiration(page)
                await self._set_amount(page, request.units)
                await self._submit_direction(page, request.side)
            finally:
                await page.context.close()
                await browser.close()
                await playwright.stop()

        return MarketOrderResponse(
            mode=TradeMode.LIVE,
            pair=request.pair,
            display_pair=SignalService.display_pair(request.pair),
            side=request.side,
            units=request.units,
            status="submitted",
            fill_price=None,
            requested_price=None,
            external_order_id=None,
            external_trade_id=None,
            account_id="pocket_option_browser",
            message="Order submitted through Pocket Option browser automation.",
            timestamp=datetime.now(timezone.utc),
        )

    async def close_position(
        self,
        pair: str,
        request: ClosePositionRequest,
    ) -> ClosePositionResponse:
        raise RuntimeError("Pocket Option browser execution does not support programmatic closeout.")

    async def _open_authenticated_page(self, request: MarketOrderRequest):
        """Launch Chromium with a pre-saved authenticated storage state."""

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Add 'playwright' and run 'python -m playwright install chromium'."
            ) from exc

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=self._settings.pocket_option_headless)
        storage_state = await self._resolve_storage_state(request)
        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()
        try:
            await page.goto(self._settings.pocket_option_base_url, wait_until="networkidle")
        except Exception:
            await context.close()
            await browser.close()
            await playwright.stop()
            raise
        return playwright, browser, page

    async def _resolve_storage_state(self, request: MarketOrderRequest):
        """Resolve the authenticated browser session for the requesting user."""

        if request.requested_by:
            try:
                user_id = int(request.requested_by)
            except ValueError as exc:
                raise RuntimeError("requested_by must contain a numeric Telegram user ID.") from exc
            return await self._execution_profile_service.decrypt_session(user_id)

        storage_state_path = Path(self._settings.pocket_option_storage_state_path).expanduser()
        if not storage_state_path.exists():
            raise RuntimeError(
                f"Pocket Option storage state not found at {storage_state_path}. "
                "Create it with scripts/save_pocket_option_session.py first or connect a user session."
            )
        import json

        return json.loads(storage_state_path.read_text(encoding="utf-8"))

    def _get_lock(self) -> asyncio.Lock:
        """Create the browser execution lock lazily for Python 3.9 compatibility."""

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _select_asset(self, page, pair: str) -> None:
        """Switch the currently selected asset using configured selectors."""

        if self._settings.pocket_option_asset_button_selector:
            await page.locator(self._settings.pocket_option_asset_button_selector).click()

        if self._settings.pocket_option_asset_search_selector:
            await page.locator(self._settings.pocket_option_asset_search_selector).fill(
                SignalService.display_pair(pair)
            )

        template = self._settings.pocket_option_asset_option_selector_template
        if not template:
            raise RuntimeError(
                "POCKET_OPTION_ASSET_OPTION_SELECTOR_TEMPLATE must be configured for browser execution."
            )
        selector = template.format(pair=pair, pair_display=SignalService.display_pair(pair))
        await page.locator(selector).first.click()

    async def _set_expiration(self, page) -> None:
        """Set the configured Pocket Option expiration label when a selector is provided."""

        selector = self._settings.pocket_option_expiration_selector
        if not selector:
            return
        await page.locator(selector).fill(self._settings.pocket_option_expiration_label)

    async def _set_amount(self, page, amount: int) -> None:
        """Fill the stake amount before submitting the order."""

        selector = self._settings.pocket_option_amount_input_selector
        if not selector:
            raise RuntimeError(
                "POCKET_OPTION_AMOUNT_INPUT_SELECTOR must be configured for browser execution."
            )
        await page.locator(selector).fill(str(amount))

    async def _submit_direction(self, page, side: OrderSide) -> None:
        """Click the configured buy/sell button."""

        selector = (
            self._settings.pocket_option_buy_button_selector
            if side == OrderSide.BUY
            else self._settings.pocket_option_sell_button_selector
        )
        if not selector:
            raise RuntimeError(
                "POCKET_OPTION_BUY_BUTTON_SELECTOR and POCKET_OPTION_SELL_BUTTON_SELECTOR must be configured."
            )
        await page.locator(selector).click()
