# Position Integrity Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 2× position drift bug (DB-derived positions used instead of live Alpaca state), and add webhook-time warnings for symbol universe changes and position drift.

**Architecture:** Add a `/positions` endpoint that proxies Alpaca live state with a 1-hour cache; replace any DB-sum position display with this endpoint. Add two lightweight warning paths inside `receive_signal()` — one for unexpected symbol pivots, one for position drift vs DB intent. No DB schema changes.

**Tech Stack:** Flask, SQLAlchemy, Alpaca REST API, React/Vite, pytest

---

## File Map

| File | Change |
|------|--------|
| `app/rebalance.py` | Add `get_last_successful()` method |
| `app/webhook.py` | Add symbol-change warning (Fix 2) + drift warning (Fix 3) |
| `app/alpaca_client.py` | Add `list_positions_full()` and `get_account()` |
| `app/positions.py` | **New** — `GET /positions` blueprint with 1-hour cache |
| `app/__init__.py` | Register new positions blueprint |
| `tests/test_rebalance_repository.py` | Tests for `get_last_successful()` |
| `tests/test_webhook.py` | Tests for symbol-change + drift warnings |
| `tests/test_positions.py` | **New** — tests for `GET /positions` |
| `tests/test_alpaca_client.py` | Tests for `list_positions_full()` + `get_account()` |
| `frontend/src/hooks/usePositions.js` | **New** — React hook for `/positions` |
| `frontend/src/components/PositionSummary.jsx` | **New** — live positions display |
| `frontend/src/App.jsx` | Integrate `PositionSummary` |

---

### Task 1: Symbol-change warning in webhook (Fix 2)

**Goal:** Log a WARNING when the incoming webhook's symbol universe differs from the last successful rebalance, so accidental pivots are always visible in logs.

**Files:**
- Modify: `app/rebalance.py` — add `get_last_successful()`
- Modify: `app/webhook.py` — add warning after target_weights parsed (~line 239)
- Modify: `tests/test_rebalance_repository.py` — test new method
- Modify: `tests/test_webhook.py` — test warning is logged

**Acceptance Criteria:**
- [ ] `RebalanceRepository.get_last_successful()` returns the most-recent event with `status="success"`, or `None` if none exists
- [ ] `receive_signal()` logs `WARNING symbol_universe_changed` when incoming symbols ≠ last event's symbols
- [ ] No warning is logged when symbols are identical
- [ ] No warning is logged when there are no prior successful events (fresh DB)
- [ ] Execution proceeds regardless — warning never blocks the trade

**Verify:** `pytest tests/test_rebalance_repository.py tests/test_webhook.py -v -k "last_successful or symbol_universe"` → all pass

**Steps:**

- [ ] **Step 1: Write failing tests**

In `tests/test_rebalance_repository.py`, add:

```python
class TestGetLastSuccessful:
    def test_returns_none_when_no_events(self, repo):
        assert repo.get_last_successful() is None

    def test_returns_none_when_only_failed_events(self, repo, sample_weights, sample_orders):
        repo.save(target_weights=sample_weights, orders=sample_orders, status="failed")
        assert repo.get_last_successful() is None

    def test_returns_most_recent_success(self, repo, sample_weights, sample_orders):
        from datetime import datetime, timezone, timedelta
        older = repo.save(
            target_weights=sample_weights, orders=sample_orders, status="success",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        newer = repo.save(
            target_weights={"SPY": 1.0}, orders=[], status="success",
        )
        result = repo.get_last_successful()
        assert result.id == newer.id

    def test_ignores_no_change_events(self, repo, sample_weights, sample_orders):
        success = repo.save(
            target_weights=sample_weights, orders=sample_orders, status="success",
        )
        repo.save(target_weights=sample_weights, orders=[], status="no_change")
        result = repo.get_last_successful()
        assert result.id == success.id
```

In `tests/test_webhook.py`, add (inside a new class or alongside existing tests):

```python
import logging

class TestSymbolUniverseWarning:
    def test_no_warning_on_first_rebalance(self, app, mock_alpaca, caplog):
        # No prior events in DB → no warning
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"weights": {"SPY": 0.6, "QQQ": 0.4}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" not in caplog.text

    def test_warning_when_symbols_change(self, app, mock_alpaca, caplog, seeded_success_event):
        # seeded_success_event has target_weights {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}
        # Incoming payload has SPY — universe changed
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"weights": {"SPY": 1.0}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" in caplog.text

    def test_no_warning_when_symbols_same(self, app, mock_alpaca, caplog, seeded_success_event):
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" not in caplog.text
```

Add a `seeded_success_event` fixture to `tests/conftest.py` (or at the top of `test_webhook.py` in the module-level mock_alpaca scope):

```python
# In test_webhook.py, add this fixture (uses the in-memory SQLite app fixture)
@pytest.fixture()
def seeded_success_event(app):
    """Seed one successful rebalance so symbol-change tests have a baseline."""
    from app.rebalance import RebalanceRepository
    with app.app_context():
        repo = RebalanceRepository(app.config["DB_SESSION"])
        repo.save(
            target_weights={"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10},
            orders=[],
            status="success",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Development/TradeInsight/TiPortfolio-TradingBot
pytest tests/test_rebalance_repository.py::TestGetLastSuccessful tests/test_webhook.py::TestSymbolUniverseWarning -v
```

Expected: FAIL — `AttributeError: 'RebalanceRepository' object has no attribute 'get_last_successful'`

- [ ] **Step 3: Add `get_last_successful()` to `app/rebalance.py`**

After the `get_since()` method (line ~188), add:

```python
def get_last_successful(self) -> RebalanceEvent | None:
    """
    Return the most-recent event with status='success', or None.
    Used by webhook to detect symbol-universe changes and position drift.
    """
    with self._tx() as session:
        event = (
            session.query(RebalanceEvent)
            .filter(RebalanceEvent.status == "success")
            .order_by(RebalanceEvent.timestamp.desc())
            .first()
        )
        if event is not None:
            session.expunge(event)
    return event
```

- [ ] **Step 4: Add symbol-change warning to `app/webhook.py`**

After line 239 (`target_weights: dict[str, float] = body["weights"]`), add:

```python
# Warn when the incoming symbol universe differs from the last known rebalance.
# This catches accidental pivots (manual webhook calls, old scripts) before
# they silently change the portfolio composition.
_read_repo = RebalanceRepository(current_app.config["DB_SESSION"])
_last_success = _read_repo.get_last_successful()
if _last_success and _last_success.target_weights:
    prev_symbols = set(_last_success.target_weights.keys())
    new_symbols  = set(target_weights.keys())
    if prev_symbols != new_symbols:
        logger.warning(
            "symbol_universe_changed | prev=%s new=%s last_event_id=%s",
            sorted(prev_symbols), sorted(new_symbols), _last_success.id,
        )
```

Also add the import at the top of `webhook.py` if not already present:
```python
from app.rebalance import RebalanceRepository
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_rebalance_repository.py::TestGetLastSuccessful tests/test_webhook.py::TestSymbolUniverseWarning -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd ~/Development/TradeInsight/TiPortfolio-TradingBot
git add app/rebalance.py app/webhook.py tests/test_rebalance_repository.py tests/test_webhook.py
git commit -m "feat: warn on symbol universe change at webhook + add get_last_successful"
```

---

### Task 2: Live positions backend (Fix 1 — backend)

**Goal:** Add `GET /positions` to the Flask backend that proxies Alpaca live positions + account state, with a 1-hour in-memory cache. Alpaca is authoritative; the DB is never consulted for position state.

**Files:**
- Modify: `app/alpaca_client.py` — add `list_positions_full()` and `get_account()`
- Create: `app/positions.py` — new blueprint with `/positions` route
- Modify: `app/__init__.py` — register new blueprint
- Create: `tests/test_positions.py` — new test file
- Modify: `tests/test_alpaca_client.py` — tests for two new methods

**Acceptance Criteria:**
- [ ] `GET /positions` returns `{positions: [...], equity: float, cash: float, as_of: ISO}` with HTTP 200
- [ ] Each position entry has `{symbol, qty, market_value, avg_entry_price}`
- [ ] Response is served from cache within the 1-hour TTL (no second Alpaca call)
- [ ] Returns stale data (with `"stale": true`) if Alpaca is down but cache exists
- [ ] Returns HTTP 503 only when Alpaca is down AND cache is empty
- [ ] `list_positions_full()` returns a list of dicts (not a `dict[str, float]`)
- [ ] `get_account()` returns `{"equity": float, "cash": float}`

**Verify:** `pytest tests/test_positions.py tests/test_alpaca_client.py -v -k "positions_full or get_account or test_positions"` → all pass

**Steps:**

- [ ] **Step 1: Write failing tests for AlpacaClient methods**

In `tests/test_alpaca_client.py`, add:

```python
class TestListPositionsFull:
    def test_returns_list_of_position_dicts(self, requests_mock):
        requests_mock.get(
            "https://paper-api.alpaca.markets/v2/positions",
            json=[
                {"symbol": "QQQ", "qty": "10.0", "market_value": "7175.40",
                 "avg_entry_price": "700.75"},
                {"symbol": "BIL", "qty": "16.0", "market_value": "1465.44",
                 "avg_entry_price": "91.54"},
            ],
        )
        client = AlpacaClient("key", "secret", "paper")
        result = client.list_positions_full()
        assert result == [
            {"symbol": "QQQ", "qty": 10.0, "market_value": 7175.40, "avg_entry_price": 700.75},
            {"symbol": "BIL", "qty": 16.0, "market_value": 1465.44, "avg_entry_price": 91.54},
        ]

    def test_returns_empty_list_when_no_positions(self, requests_mock):
        requests_mock.get("https://paper-api.alpaca.markets/v2/positions", json=[])
        client = AlpacaClient("key", "secret", "paper")
        assert client.list_positions_full() == []


class TestGetAccount:
    def test_returns_equity_and_cash(self, requests_mock):
        requests_mock.get(
            "https://paper-api.alpaca.markets/v2/account",
            json={"equity": "10067.79", "cash": "0.00", "buying_power": "20135.58"},
        )
        client = AlpacaClient("key", "secret", "paper")
        result = client.get_account()
        assert result == {"equity": 10067.79, "cash": 0.0}
```

Create `tests/test_positions.py`:

```python
"""Tests for GET /positions."""
from __future__ import annotations
import os
from unittest.mock import patch, MagicMock
import pytest

os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")

from app import create_app  # noqa: E402
import app.positions as positions_module  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset module-level cache between tests."""
    positions_module._cache.clear()
    yield
    positions_module._cache.clear()


@pytest.fixture()
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


MOCK_POSITIONS = [
    {"symbol": "QQQ", "qty": 10.0, "market_value": 7175.40, "avg_entry_price": 700.75},
    {"symbol": "BIL", "qty": 16.0, "market_value": 1465.44, "avg_entry_price": 91.54},
]
MOCK_ACCOUNT = {"equity": 9468.00, "cash": 0.0}


def _mock_alpaca():
    mock = MagicMock()
    mock.list_positions_full.return_value = MOCK_POSITIONS
    mock.get_account.return_value = MOCK_ACCOUNT
    return mock


class TestGetPositions:
    def test_returns_live_positions_from_alpaca(self, app):
        with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["equity"] == 9468.00
        assert data["cash"] == 0.0
        assert len(data["positions"]) == 2
        assert data["positions"][0]["symbol"] == "QQQ"
        assert "as_of" in data

    def test_caches_response_within_ttl(self, app):
        mock_alpaca = _mock_alpaca()
        with patch("app.positions.AlpacaClient", return_value=mock_alpaca):
            with app.test_client() as client:
                client.get("/positions")
                client.get("/positions")
        # Alpaca only called once — second request served from cache
        assert mock_alpaca.list_positions_full.call_count == 1

    def test_serves_stale_on_alpaca_failure_when_cache_exists(self, app):
        from app.alpaca_client import AlpacaError
        # Prime the cache
        with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
            with app.test_client() as client:
                client.get("/positions")

        # Now expire cache by backdating it
        from datetime import timedelta
        positions_module._cache["fetched_at"] -= timedelta(hours=2)

        # Alpaca now fails
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError("timeout")
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stale"] is True

    def test_returns_503_when_alpaca_down_and_no_cache(self, app):
        from app.alpaca_client import AlpacaError
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError("timeout")
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_alpaca_client.py::TestListPositionsFull tests/test_alpaca_client.py::TestGetAccount tests/test_positions.py -v
```

Expected: FAIL — methods not defined, `app/positions.py` not found

- [ ] **Step 3: Add `list_positions_full()` and `get_account()` to `app/alpaca_client.py`**

After `get_positions()` (line ~108), add:

```python
def list_positions_full(self) -> list[dict]:
    """
    Fetch all current positions with full detail for the /positions display endpoint.

    Returns:
        List of dicts: [{"symbol", "qty", "market_value", "avg_entry_price"}, ...]
        Empty list when no positions are held.

    Raises:
        AlpacaError: on network or API failure.
    """
    url = f"{self._base_url}/v2/positions"
    logger.info("Fetching full positions from Alpaca (%s)", self._mode)
    raw = self._get(url)
    return [
        {
            "symbol":          p["symbol"],
            "qty":             float(p["qty"]),
            "market_value":    float(p["market_value"]),
            "avg_entry_price": float(p["avg_entry_price"]),
        }
        for p in raw
    ]
```

After `get_account_equity()` (line ~179), add:

```python
def get_account(self) -> dict:
    """
    Fetch equity and cash from /v2/account.

    Returns:
        {"equity": float, "cash": float}

    Raises:
        AlpacaError: on network or API failure.
    """
    url = f"{self._base_url}/v2/account"
    logger.info("Fetching account state from Alpaca (%s)", self._mode)
    body = self._get(url)
    return {
        "equity": float(body["equity"]),
        "cash":   float(body["cash"]),
    }
```

- [ ] **Step 4: Create `app/positions.py`**

```python
"""
GET /positions — return live Alpaca portfolio positions with a 1-hour cache.

Alpaca is authoritative for position state; this endpoint is the ONLY
place in the app that answers "what do we hold right now."
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from app.alpaca_client import AlpacaClient, AlpacaError

logger = logging.getLogger(__name__)
bp = Blueprint("positions", __name__)

_CACHE_TTL_SECONDS = 3600
_cache: dict = {}  # keys: "data" (response dict), "fetched_at" (datetime)


@bp.get("/positions")
def get_positions():
    """
    Return live Alpaca positions, equity, and cash.

    Cached for 1 hour. Serves stale data with "stale": true if Alpaca
    is unreachable but a prior response exists. Returns 503 only when
    Alpaca is down and no cached response exists.

    Response:
        {
            "positions": [{"symbol", "qty", "market_value", "avg_entry_price"}],
            "equity":    float,
            "cash":      float,
            "as_of":     ISO 8601 timestamp of last successful fetch
        }
    """
    now = datetime.now(timezone.utc)

    if _cache and (now - _cache["fetched_at"]).total_seconds() < _CACHE_TTL_SECONDS:
        return jsonify(_cache["data"]), 200

    try:
        alpaca = AlpacaClient(
            api_key=current_app.config["ALPACA_API_KEY"],
            api_secret=current_app.config["ALPACA_API_SECRET"],
            mode=current_app.config["ALPACA_MODE"],
        )
        positions = alpaca.list_positions_full()
        account   = alpaca.get_account()
    except AlpacaError as exc:
        logger.error("Alpaca positions fetch failed: %s", exc)
        if _cache:
            return jsonify({**_cache["data"], "stale": True}), 200
        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 503

    data = {
        "positions": positions,
        "equity":    account["equity"],
        "cash":      account["cash"],
        "as_of":     now.isoformat(),
    }
    _cache["data"]       = data
    _cache["fetched_at"] = now
    return jsonify(data), 200
```

- [ ] **Step 5: Register blueprint in `app/__init__.py`**

After the existing blueprint registrations (after `benchmark_bp`), add:

```python
from app.positions import bp as positions_bp
app.register_blueprint(positions_bp)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_alpaca_client.py::TestListPositionsFull tests/test_alpaca_client.py::TestGetAccount tests/test_positions.py -v
```

Expected: all PASS

- [ ] **Step 7: Smoke-test the endpoint locally**

```bash
cd ~/Development/TradeInsight/TiPortfolio-TradingBot
python run.py &
curl http://localhost:5000/positions | python -m json.tool
```

Expected: JSON with `positions`, `equity`, `cash`, `as_of` keys. Kill the dev server after.

- [ ] **Step 8: Commit**

```bash
git add app/alpaca_client.py app/positions.py app/__init__.py \
        tests/test_alpaca_client.py tests/test_positions.py
git commit -m "feat: add GET /positions endpoint proxying Alpaca live state (1-hour cache)"
```

---

### Task 3: Live positions frontend (Fix 1 — frontend)

**Goal:** Add `usePositions` hook + `PositionSummary` component that fetches `/positions` from Alpaca live; integrate it in the Trades section so positions shown are always accurate.

**Files:**
- Create: `frontend/src/hooks/usePositions.js`
- Create: `frontend/src/components/PositionSummary.jsx`
- Modify: `frontend/src/App.jsx` — render `PositionSummary` above the trades table

**Acceptance Criteria:**
- [ ] `usePositions` fetches `GET /positions` (via same `VITE_API_BASE_URL` pattern as `useDelta`)
- [ ] `PositionSummary` renders each position's symbol, qty, market_value, and percentage of equity
- [ ] If Alpaca data is stale (`stale: true` in response), component shows a "stale" indicator
- [ ] If `/positions` returns 503, component shows an error state (not a crash)
- [ ] Removing the old DB-sum position display (if any existed) does not break any other component

**Verify:** Load `http://localhost:5173` (Vite dev server) and confirm the Trades section shows a live position summary with correct values matching Alpaca dashboard.

**Steps:**

- [ ] **Step 1: Create `frontend/src/hooks/usePositions.js`**

```javascript
import { useState, useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export function usePositions() {
  const [data, setData]       = useState(null);   // {positions, equity, cash, as_of, stale?}
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPositions() {
      try {
        const resp = await fetch(`${API_BASE}/positions`);
        const json = await resp.json();
        if (!resp.ok) throw new Error(json.error ?? `HTTP ${resp.status}`);
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchPositions();
    return () => { cancelled = true; };
  }, []);

  return { data, loading, error };
}
```

- [ ] **Step 2: Create `frontend/src/components/PositionSummary.jsx`**

```jsx
import { usePositions } from "../hooks/usePositions";

function formatCurrency(value) {
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

function formatPct(value, equity) {
  if (!equity) return "—";
  return `${((value / equity) * 100).toFixed(1)}%`;
}

export default function PositionSummary() {
  const { data, loading, error } = usePositions();

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm py-2">
        <span className="animate-spin inline-block h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
        Loading positions…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-destructive py-2">
        Could not load live positions: {error}
      </div>
    );
  }

  if (!data) return null;

  const { positions, equity, cash, as_of, stale } = data;

  return (
    <div className="rounded-lg border border-border bg-card p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Current Holdings
        </h3>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {stale && (
            <span className="text-yellow-600 font-medium">⚠ stale</span>
          )}
          <span>Equity: {formatCurrency(equity)}</span>
          <span>·</span>
          <span>Cash: {formatCurrency(cash)}</span>
        </div>
      </div>

      {positions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open positions.</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {positions.map((p) => (
            <div
              key={p.symbol}
              className="flex flex-col rounded-md bg-muted/40 px-3 py-2 text-sm min-w-[110px]"
            >
              <span className="font-mono font-semibold">{p.symbol}</span>
              <span className="text-muted-foreground text-xs">
                {p.qty} shares
              </span>
              <span className="tabular-nums">
                {formatCurrency(p.market_value)}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatPct(p.market_value, equity)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Integrate `PositionSummary` in `App.jsx`**

In the `#trades` section (around line 59), add `PositionSummary` above `DeltaTable`:

```jsx
// Add import at top:
import PositionSummary from "./components/PositionSummary";

// Replace the trades section:
<section id="trades" className="max-w-7xl mx-auto px-4 py-16">
  <h2 className="text-2xl font-bold mb-2">Trade Records</h2>
  <p className="text-muted-foreground mb-6">
    All rebalance decisions made by the algorithm, sorted by most recent first.
  </p>
  <PositionSummary />
  <DeltaTable />
</section>
```

- [ ] **Step 4: Start dev server and verify**

```bash
cd ~/Development/TradeInsight/TiPortfolio-TradingBot/frontend
npm run dev
```

Open `http://localhost:5173` → Trades section → confirm "Current Holdings" card shows QQQ/BIL/GLD with correct quantities and values matching Alpaca dashboard.

- [ ] **Step 5: Commit**

```bash
cd ~/Development/TradeInsight/TiPortfolio-TradingBot
git add frontend/src/hooks/usePositions.js \
        frontend/src/components/PositionSummary.jsx \
        frontend/src/App.jsx
git commit -m "feat: replace DB-derived position display with live Alpaca positions component"
```

---

### Task 4: Position drift logging at webhook (Fix 3)

**Goal:** Log a WARNING at the start of every rebalance when live Alpaca positions diverge in symbol universe from the last successful DB event's target weights. Catches out-of-band trades before they accumulate silently.

**Files:**
- Modify: `app/webhook.py` — add drift check after `current_positions` fetch
- Modify: `tests/test_webhook.py` — test drift warning is logged

**Acceptance Criteria:**
- [ ] WARNING logged when Alpaca holds symbols not in last event's `target_weights`
- [ ] WARNING logged when last event's `target_weights` has symbols Alpaca no longer holds
- [ ] No warning when symbol sets match (normal operation)
- [ ] No warning when there are no prior successful events (fresh DB)
- [ ] Drift never blocks execution — trading proceeds regardless

**Verify:** `pytest tests/test_webhook.py -v -k "drift"` → all pass

**Steps:**

- [ ] **Step 1: Write failing tests**

In `tests/test_webhook.py`, add:

```python
class TestPositionDriftLogging:
    def test_no_drift_warning_in_normal_operation(self, app, caplog, seeded_success_event):
        """No drift when Alpaca positions match the last event's target symbols."""
        # seeded_success_event targets QQQ/BIL/GLD
        # mock_alpaca returns those same symbols as current positions
        mock_client = MagicMock()
        mock_client.get_positions.side_effect = (
            lambda target_symbols=None: {"QQQ": 10.0, "BIL": 16.0, "GLD": 2.0}
        )
        mock_client.get_latest_prices.side_effect = (
            lambda symbols: {s: 100.0 for s in symbols}
        )
        mock_client.get_account_equity.return_value = 10_000.0
        mock_client._base_url = "https://paper-api.alpaca.markets"

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="no_change", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" not in caplog.text

    def test_drift_warning_when_unexpected_symbol_held(self, app, caplog, seeded_success_event):
        """Drift detected when Alpaca holds SPY but last event targeted QQQ/BIL/GLD."""
        mock_client = MagicMock()
        # Alpaca has SPY instead of expected QQQ/BIL/GLD
        mock_client.get_positions.side_effect = (
            lambda target_symbols=None: {"SPY": 8.0, **(
                {s: 0.0 for s in (target_symbols or [])} if target_symbols else {}
            )}
        )
        mock_client.get_latest_prices.side_effect = (
            lambda symbols: {s: 100.0 for s in symbols}
        )
        mock_client.get_account_equity.return_value = 10_000.0
        mock_client._base_url = "https://paper-api.alpaca.markets"

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="success", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_webhook.py::TestPositionDriftLogging -v
```

Expected: FAIL — `position_drift_detected` not in logs (code not written yet)

- [ ] **Step 3: Add drift check to `app/webhook.py`**

After the `current_positions` fetch block (after line ~250, after the `except AlpacaError` block), add:

```python
# Detect position drift: warn if Alpaca's non-zero symbol set differs from
# what the last successful rebalance targeted. Out-of-band trades (manual
# or from other services) will appear here before they compound.
_drift_repo = RebalanceRepository(current_app.config["DB_SESSION"])
_last_ok = _drift_repo.get_last_successful()
if _last_ok and _last_ok.target_weights:
    expected_symbols = set(_last_ok.target_weights.keys())
    actual_symbols   = {sym for sym, qty in current_positions.items() if qty > 0}
    drifted          = expected_symbols.symmetric_difference(actual_symbols)
    if drifted:
        logger.warning(
            "position_drift_detected | expected=%s actual=%s last_event_id=%s",
            sorted(expected_symbols), sorted(actual_symbols), _last_ok.id,
        )
```

Note: `_last_success` was already fetched in Task 1's symbol-change check. To avoid a second DB query, combine both checks to use the same `_last_success` variable fetched once. Refactor the two blocks to share a single `get_last_successful()` call:

```python
# Fetch once, use for both symbol-change and drift checks
_read_repo  = RebalanceRepository(current_app.config["DB_SESSION"])
_last_event = _read_repo.get_last_successful()

# Fix 2: symbol-change warning (after target_weights parsed, ~line 239)
if _last_event and _last_event.target_weights:
    prev_symbols = set(_last_event.target_weights.keys())
    new_symbols  = set(target_weights.keys())
    if prev_symbols != new_symbols:
        logger.warning(
            "symbol_universe_changed | prev=%s new=%s last_event_id=%s",
            sorted(prev_symbols), sorted(new_symbols), _last_event.id,
        )

# ... (Alpaca calls happen here: get_positions, get_latest_prices, get_account_equity) ...

# Fix 3: position drift warning (after current_positions fetched, ~line 250)
if _last_event and _last_event.target_weights:
    expected_symbols = set(_last_event.target_weights.keys())
    actual_symbols   = {sym for sym, qty in current_positions.items() if qty > 0}
    drifted          = expected_symbols.symmetric_difference(actual_symbols)
    if drifted:
        logger.warning(
            "position_drift_detected | expected=%s actual=%s last_event_id=%s",
            sorted(expected_symbols), sorted(actual_symbols), _last_event.id,
        )
```

This means the `_read_repo` and `_last_event` fetch done in Task 1 (before Alpaca calls) is reused here for the drift check (after Alpaca calls). Remove the separate `_drift_repo` / `_last_ok` fetch introduced in this task's description above and use `_last_event` instead.

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_webhook.py tests/test_rebalance_repository.py tests/test_positions.py tests/test_alpaca_client.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/webhook.py tests/test_webhook.py
git commit -m "feat: log position drift when Alpaca symbols diverge from last DB event"
```
