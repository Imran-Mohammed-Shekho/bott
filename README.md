# Forex Signals Telegram Bot

Production-minded Telegram bot and FastAPI backend for forex trading signals. The project can run in:

- `mock` mode for local development
- `oanda` mode for live market data
- `sklearn` mode for real trained model inference
- `paper` trade mode for safe execution rehearsal
- `live` trade mode for real OANDA execution

- `5s`
- `10s`
- `30s`
- `1m`

The prediction layer is modular, so you can swap between mock mode and live/provider-backed mode without rewriting the bot.

## Features

- Telegram commands:
  - `/start`
  - `/help`
  - `/pairs`
  - `/signal EURUSD`
  - `/watch EURUSD`
  - `/stopwatch EURUSD`
  - `/status`
  - `/account` admin only
  - `/positions` admin only
  - `/buy EURUSD 100` admin only
  - `/sell EURUSD 100` admin only
  - `/close EURUSD all` admin only
- FastAPI backend with health, pair list, signal, and subscription endpoints
- Mock market data provider
- OANDA market data provider for live quotes and recent candles
- OANDA market execution provider for real orders
- Supabase-backed Postgres persistence for subscriptions and trade logs
- Render deployment blueprint in `render.yaml`
- Sentry initialization for production monitoring
- Feature engineering module
- Mock multi-horizon prediction provider
- Joblib-backed sklearn prediction provider
- Model loader abstraction for future real model integration
- In-memory subscription tracking for scheduled alerts
- Structured logging, validation, and error handling
- `.env`-driven configuration
- Unit tests for service and API layers

## Project Structure

```text
app/
  api/
    routes.py
  bot/
    formatter.py
    handlers.py
    runner.py
    webhook.py
  config/
    settings.py
  data/
    mock_market_data.py
    oanda_market_data.py
    oanda_trading.py
  features/
    engineering.py
  models/
    interfaces.py
    model_loader.py
    signal.py
    trading.py
  persistence/
    supabase.py
  services/
    market_data_service.py
    prediction_service.py
    signal_service.py
    subscriptions.py
    trading_service.py
  utils/
    logging.py
    monitoring.py
  bootstrap.py
  main.py
infra/
  supabase/
    schema.sql
tests/
  test_api.py
  test_signal_service.py
  test_trading_service.py
.env.example
requirements.txt
render.yaml
README.md
```

## Quick Start

1. Create a virtual environment and install dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For local tests and sklearn extras:

```bash
pip install -r requirements-ml.txt
```

2. Create your environment file.

```bash
cp .env.example .env
```

3. Add your Telegram bot token to `.env`.

```env
TELEGRAM_BOT_TOKEN=your_real_bot_token
ADMIN_TELEGRAM_USER_IDS_CSV=123456789
```

4. Choose your runtime mode in `.env`.

Local demo:

```env
MARKET_DATA_PROVIDER=mock
PREDICTION_PROVIDER=mock
```

Live market data with OANDA:

```env
MARKET_DATA_PROVIDER=oanda
PREDICTION_PROVIDER=mock
OANDA_API_TOKEN=your_oanda_api_token
OANDA_ACCOUNT_ID=your_oanda_account_id
OANDA_BASE_URL=https://api-fxpractice.oanda.com/v3
```

Live market data with trained models:

```env
MARKET_DATA_PROVIDER=oanda
PREDICTION_PROVIDER=sklearn
MODEL_DIR=artifacts/models
```

Production stack:

```env
MARKET_DATA_PROVIDER=oanda
PREDICTION_PROVIDER=mock
TRADE_MODE=paper
DATABASE_URL=postgresql://...
SENTRY_DSN=https://...
ADMIN_API_KEY=your_internal_api_key
ADMIN_TELEGRAM_USER_IDS_CSV=123456789
TELEGRAM_WEBHOOK_URL=https://your-bot.onrender.com/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
```

5. Start the API.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

6. Start the Telegram bot in a second terminal.

```bash
python3 -m app.bot.runner
```

## API Endpoints

- `GET /api/v1/health`
- `GET /api/v1/pairs`
- `GET /api/v1/signal/EURUSD`
- `POST /api/v1/subscriptions`
- `GET /api/v1/subscriptions/123456`
- `DELETE /api/v1/subscriptions/123456/EURUSD`
- `GET /api/v1/account` with `X-Admin-Key`
- `GET /api/v1/positions` with `X-Admin-Key`
- `POST /api/v1/orders/market` with `X-Admin-Key`
- `POST /api/v1/positions/EURUSD/close` with `X-Admin-Key`
- `GET /api/v1/trades` with `X-Admin-Key`

### Example: Get a Signal

```bash
curl http://127.0.0.1:8000/api/v1/signal/EURUSD
```

### Example: Create a Subscription

```bash
curl -X POST http://127.0.0.1:8000/api/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 123456, "user_id": 123456, "pair": "EURUSD", "interval_seconds": 30}'
```

## Sample Telegram Conversation

```text
User: /start
Bot: Forex Signals Bot is ready.
     Use /pairs to list supported instruments and /signal EURUSD to request a signal.

User: /signal EURUSD
Bot: Pair: EUR/USD
     5s: BUY
     10s: HOLD
     30s: SELL
     1m: BUY

     Confidence:
     5s: 0.54
     10s: 0.61
     30s: 0.67
     1m: 0.72

     Extra info:
     - current mid price: 1.08342
     - spread: 0.00008
     - timestamp: 2026-03-24T07:30:21+00:00
     - short risk warning: Use tight risk management. Fast-horizon signals can reverse quickly.

     This is an experimental signal and not financial advice.

User: /watch EURUSD 15
Bot: Watching EUR/USD every 15 seconds.

User: /status
Bot: Active watches:
     - EUR/USD every 15s

User: /stopwatch EURUSD
Bot: Stopped updates for EUR/USD.
```

## Testing

```bash
pytest
```

Optional ML packages and local test-only extras live in `requirements-ml.txt`.

## Real Model Artifacts

If `PREDICTION_PROVIDER=sklearn`, place these files in `MODEL_DIR`:

- `5s.joblib`
- `10s.joblib`
- `30s.joblib`
- `1m.joblib`

Each artifact can be either:

- a raw sklearn-compatible estimator
- a dict with `model`, optional `classes`, and optional `version`

## Production Stack

- Host on Render with `render.yaml`
- Use Supabase Postgres via `DATABASE_URL`
- Use OANDA practice first, then switch to live only after validation
- Enable Sentry with `SENTRY_DSN`
- Set `ADMIN_API_KEY` for protected API routes
- Set `ADMIN_TELEGRAM_USER_IDS_CSV` so only your Telegram account can trade
- Apply `infra/supabase/schema.sql` if you want to create tables manually
- Point Telegram webhook to `/telegram/webhook`

Example protected market order:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/orders/market \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your_internal_api_key" \
  -d '{"pair":"EURUSD","side":"BUY","units":100,"request_source":"api"}'
```

## Validation Before Real Use

Before trusting the signals, you still need:

- historical training data
- out-of-sample validation
- backtesting after spread and slippage
- paper trading
- drawdown limits and risk controls
