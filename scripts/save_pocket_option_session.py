"""Open Pocket Option in Chromium and save an authenticated storage state."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config.settings import get_settings


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required. Install requirements-browser.txt and run "
            "'python -m playwright install chromium'."
        ) from exc

    settings = get_settings()
    storage_state_path = Path(settings.pocket_option_storage_state_path).expanduser()
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(settings.pocket_option_base_url, wait_until="domcontentloaded")
        print("Log in to Pocket Option in the opened browser window.")
        print("After login is complete and the trading page is visible, press Enter here.")
        input()
        await context.storage_state(path=str(storage_state_path))
        await browser.close()

    print(f"Saved Pocket Option storage state to {storage_state_path}")


if __name__ == "__main__":
    asyncio.run(main())
