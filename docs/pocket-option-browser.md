# Pocket Option Browser Execution

This project can route live trade execution through a Playwright-controlled Pocket Option browser session.

## 1. Install browser dependencies

```bash
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
```

## 2. Save an authenticated Pocket Option session

```bash
.venv/bin/python scripts/save_pocket_option_session.py
```

Log in manually in the opened Chromium window, then return to the terminal and press Enter. The session is stored at `POCKET_OPTION_STORAGE_STATE_PATH`.

## 2B. User-friendly secure connect flow

For per-user sessions, the user does not need to paste raw JSON manually if they can run a helper locally.

1. In Telegram, the user runs:

```text
/connect
```

2. The bot replies with a one-time secure link like:

```text
https://your-app.onrender.com/api/v1/connect/...
```

3. The user runs:

```bash
.venv/bin/python scripts/connect_pocket_option_session.py "SECURE_CONNECT_URL"
```

Optional flags:

```bash
.venv/bin/python scripts/connect_pocket_option_session.py "SECURE_CONNECT_URL" \
  --trade-amount 1 \
  --expiry M5 \
  --horizon 1m \
  --autotrade
```

What happens:
- Chromium opens
- the user logs into Pocket Option
- the script captures Playwright storage state
- the script uploads it directly to the secure connect endpoint
- the backend encrypts and stores it in Supabase

The user never needs to manually copy JSON in this flow.

## 3. Configure execution

Set:

```env
TRADE_MODE=live
EXECUTION_PROVIDER=pocket_option_browser
POCKET_OPTION_STORAGE_STATE_PATH=.state/pocket_option.json
POCKET_OPTION_ASSET_OPTION_SELECTOR_TEMPLATE=text="{pair_display}"
POCKET_OPTION_AMOUNT_INPUT_SELECTOR=input[type="text"]
POCKET_OPTION_BUY_BUTTON_SELECTOR=button:has-text("Up")
POCKET_OPTION_SELL_BUTTON_SELECTOR=button:has-text("Down")
```

The exact selectors depend on the current Pocket Option UI. Inspect the page and replace them with stable selectors if needed.

Optional selectors:

```env
POCKET_OPTION_ASSET_BUTTON_SELECTOR=
POCKET_OPTION_ASSET_SEARCH_SELECTOR=
POCKET_OPTION_EXPIRATION_SELECTOR=
POCKET_OPTION_EXPIRATION_LABEL=M5
POCKET_OPTION_HEADLESS=true
POCKET_OPTION_TRADE_AMOUNT=1
```

## 4. Execute from Telegram

Admin command:

```text
/execsignal EURUSD 1m 1
```

Format:

```text
/execsignal <pair> [horizon] [amount]
```

- `pair`: `EURUSD`
- `horizon`: `5s`, `10s`, `30s`, `1m`
- `amount`: stake amount passed into the Pocket Option amount field

If the selected horizon is `HOLD`, no order is opened.
