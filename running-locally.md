# Running Locally

## Architecture

Three Docker services orchestrated by Docker Compose:

- **db** — Postgres (internal port 5432)
- **tradingbot** — Flask API (`localhost:5000`)
- **scheduler** — cron container; fires the strategy script Mon–Fri at 9:30 AM ET

The scheduler talks to the tradingbot over Docker's internal network (`http://tradingbot:5000`). The frontend runs separately and talks to `localhost:5000`.

---

## 1. Start the backend

```bash
docker compose up --build
```

Verify health:

```bash
curl http://localhost:5000/health
```

---

## 2. Trigger the webhook manually

The cron fires on weekdays at 9:30 AM ET. To trigger it immediately:

```bash
# Inside the scheduler container (uses live yfinance data)
docker compose exec scheduler python /app/strategies/25_run_strategy_send_webhook.py

# Locally against the running bot
TRADING_BOT_WEBHOOK_URL=http://localhost:5000 python scheduler/strategies/25_run_strategy_send_webhook.py

# Dry run — prints weights, no POST
python scheduler/strategies/25_run_strategy_send_webhook.py --dry-run

# Use bundled CSV test data (fast, no network required)
python scheduler/strategies/25_run_strategy_send_webhook.py --csv
```

Or POST directly with hardcoded weights:

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}}'
```

---

## 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Navigate to **Trade Records** (`/delta`) to see rebalance events, or **Performance** (`/benchmark`) for strategy metrics.

---

## Data flow

```
Scheduler → POST /webhook → Alpaca API (paper/live)
                         → Postgres (saves rebalance record)

Frontend → GET /delta     → Flask → Postgres → Trade Records page
         → GET /benchmark → Flask →           → Performance page
```

> The `--csv` flag bypasses yfinance for local testing but still requires the Flask server running to POST the webhook.
