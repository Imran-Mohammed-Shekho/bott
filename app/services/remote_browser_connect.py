"""Hosted Playwright session manager for phone-friendly connect flows."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from app.config.settings import Settings
from app.models.execution import ExecutionProfileStatus
from app.services.execution_profiles import ExecutionProfileService


@dataclass
class RemoteBrowserSession:
    """In-memory browser session used during connect onboarding."""

    playwright: object
    browser: object
    context: object
    page: object
    viewport_width: int
    viewport_height: int
    last_seen_at: datetime


class RemoteBrowserConnectService:
    """Create and drive temporary remote browser sessions for connect links."""

    def __init__(
        self,
        settings: Settings,
        execution_profile_service: ExecutionProfileService,
    ):
        self._settings = settings
        self._execution_profile_service = execution_profile_service
        self._sessions: Dict[str, RemoteBrowserSession] = {}
        self._lock: Optional[asyncio.Lock] = None

    async def ensure_session(self, token: str) -> None:
        """Start a hosted browser session for a valid connect token."""

        connect_token = await self._execution_profile_service.get_connect_token(token)
        if (
            connect_token is None
            or not connect_token.is_active
            or connect_token.used_at is not None
            or connect_token.expires_at < datetime.now(connect_token.expires_at.tzinfo)
        ):
            raise RuntimeError("Connect link is invalid or expired.")

        async with self._get_lock():
            existing = self._sessions.get(token)
            if existing is not None:
                existing.last_seen_at = datetime.now(existing.last_seen_at.tzinfo)
                return

            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is required on the server for hosted remote-browser connect."
                ) from exc

            viewport = {"width": 430, "height": 932}
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=self._settings.pocket_option_headless)
            context = await browser.new_context(viewport=viewport)
            page = await context.new_page()
            try:
                await page.goto(self._settings.pocket_option_base_url, wait_until="domcontentloaded")
            except Exception:
                await context.close()
                await browser.close()
                await playwright.stop()
                raise

            self._sessions[token] = RemoteBrowserSession(
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                last_seen_at=datetime.now().astimezone(),
            )

    async def get_screenshot(self, token: str) -> bytes:
        """Return the latest screenshot for the hosted browser session."""

        session = await self._require_session(token)
        session.last_seen_at = datetime.now().astimezone()
        return await session.page.screenshot(type="png", full_page=False)

    async def click(
        self,
        token: str,
        x: float,
        y: float,
        rendered_width: int,
        rendered_height: int,
    ) -> None:
        """Translate a tap on the rendered image into a browser mouse click."""

        session = await self._require_session(token)
        scale_x = session.viewport_width / rendered_width
        scale_y = session.viewport_height / rendered_height
        await session.page.mouse.click(x * scale_x, y * scale_y)
        session.last_seen_at = datetime.now().astimezone()

    async def type_text(self, token: str, text: str) -> None:
        """Type text into the currently focused field."""

        session = await self._require_session(token)
        await session.page.keyboard.type(text)
        session.last_seen_at = datetime.now().astimezone()

    async def press_key(self, token: str, key: str) -> None:
        """Press a single keyboard key in the hosted browser."""

        session = await self._require_session(token)
        await session.page.keyboard.press(key)
        session.last_seen_at = datetime.now().astimezone()

    async def save_session(
        self,
        token: str,
        autotrade_enabled: bool = False,
        trade_amount: Optional[int] = None,
        expiration_label: Optional[str] = None,
        signal_horizon: Optional[str] = None,
    ) -> ExecutionProfileStatus:
        """Capture browser storage state, encrypt it, and store it as the user's profile."""

        session = await self._require_session(token)
        storage_state = await session.context.storage_state()
        status = await self._execution_profile_service.connect_user(
            token=token,
            storage_state_json=json.dumps(storage_state),
            autotrade_enabled=autotrade_enabled,
            trade_amount=trade_amount,
            expiration_label=expiration_label,
            signal_horizon=signal_horizon,
        )
        await self.close_session(token)
        return status

    async def close_session(self, token: str) -> None:
        """Close a hosted browser session and release resources."""

        async with self._get_lock():
            session = self._sessions.pop(token, None)
        if session is None:
            return
        await session.context.close()
        await session.browser.close()
        await session.playwright.stop()

    async def close_all(self) -> None:
        """Close every hosted browser session during app shutdown."""

        async with self._get_lock():
            tokens = list(self._sessions.keys())
        for token in tokens:
            await self.close_session(token)

    async def _require_session(self, token: str) -> RemoteBrowserSession:
        await self.ensure_session(token)
        async with self._get_lock():
            session = self._sessions.get(token)
        if session is None:
            raise RuntimeError("Remote browser session is not available.")
        return session

    def _get_lock(self) -> asyncio.Lock:
        """Create the lock lazily so sync construction works on Python 3.9."""

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
