# Running Locally

## Architecture

Three Docker services orchestrated by Docker Compose:

- **db** — Postgres (internal port 5432)
- **tradingbot** — Flask API (`localhost:5000`)
- **scheduler** — one-shot container; runs the strategy script once on `docker compose up` (scheduling is handled by k8s CronJob in production)

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

To trigger the strategy manually:

```bash
# Inside the scheduler container (uses live yfinance data)
docker compose exec scheduler python /app/strategies/market_vix_rebalance.py

# Locally against the running bot
TRADING_BOT_WEBHOOK_URL=http://localhost:5000 python scheduler/strategies/market_vix_rebalance.py

# Dry run — prints weights, no POST
python scheduler/strategies/market_vix_rebalance.py --dry-run
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

> The `--dry-run` flag prints the computed weights without POSTing to the webhook — useful for testing the strategy logic without a running backend.
