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

To trigger a rebalance, POST directly to the webhook:

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(echo $WEBHOOK_SECRET)" \
  -d '{"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.5}}'
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
