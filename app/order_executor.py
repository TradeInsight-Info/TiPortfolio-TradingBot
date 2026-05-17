"""
Submits buy/sell market orders to Alpaca based on share delta.

Responsibilities:
  - Skip the entire run when every delta is zero
  - Submit a market order (POST /v2/orders) for each non-zero delta
  - Capture the Alpaca order ID returned in each response
  - Continue submitting remaining orders even when one order fails
  - Poll each accepted order via GET /v2/orders/{id} to confirm fill status
  - Return an ExecutionResult that carries per-order outcomes and an
    overall status ("success" / "partial" / "failed")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import requests

from app.alpaca_client import AlpacaClient, AlpacaError
from app.calculator import OrderDelta

logger = logging.getLogger(__name__)

# Type for the three possible final statuses
ExecutionStatus = Literal["success", "partial", "failed"]

_REQUEST_TIMEOUT_SECONDS = 10

# Polling constants
# Seconds to wait after submitting ALL orders before polling for fill status
_FILL_POLL_DELAY_SECONDS: float = 5.0

# Alpaca order lifecycle statuses that indicate a fill state
_TERMINAL_FILL_STATUSES = frozenset({
    "filled",
    "partially_filled",
    "canceled",
    "expired",
    "rejected",
    "done_for_day",
})

@dataclass
class OrderResult:
    """
    Outcome of a single market order attempt.

    Attributes:
        symbol:          Ticker symbol, e.g. "SPY".
        side:            "buy" or "sell" derived from delta sign.
        qty:             Absolute share quantity submitted.
        alpaca_order_id: Alpaca's UUID for the order; None when the order failed.
        success:         True if Alpaca accepted the order (HTTP 200/201).
        error:           Human-readable error string; None when successful.
        fill_status:     Alpaca lifecycle status after polling, e.g. "filled".
                         None when order submission itself failed, or when
                         polling was skipped (no order_id available).
        filled_qty:      Shares actually executed after polling; None if not filled.
        filled_avg_price: Average execution price after polling; None if not filled.
    """
    symbol: str
    side: str
    qty: int
    alpaca_order_id: str | None = None
    success: bool = False
    error: str | None = None
    fill_status: str | None = None
    filled_qty: float | None = None
    filled_avg_price: float | None = None

@dataclass
class ExecutionResult:
    """
    Aggregated result of one rebalance execution run.

    Attributes:
        orders:  One OrderResult per non-zero delta that was attempted.
        status:  "success"  - all orders succeeded.
                 "partial"  - at least one order succeeded and one failed.
                 "failed"   - all orders failed, or no orders were attempted
                              (zero-delta guard).
        error_message: Combined error text for failed orders; None on full success.
    """
    orders: list[OrderResult] = field(default_factory=list)
    status: ExecutionStatus = "failed"
    error_message: str | None = None

class OrderExecutor:
    """
    Submits Alpaca market orders derived from a list of OrderDelta objects,
    then polls Alpaca once to confirm fill status.

    Args:
        api_key:    ALPACA_API_KEY from Flask config.
        api_secret: ALPACA_API_SECRET from Flask config.
        base_url:   Alpaca REST base URL (paper or live).
        alpaca_client: An AlpacaClient instance used for polling order status.
                Passed in from the caller (webhook.py) to reuse the
                same authenticated session without creating a second one.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str, alpaca_client: "AlpacaClient",) -> None:
        self._base_url = base_url.rstrip("/")
        self._alpaca_client = alpaca_client
        # Alpaca authenticates via custom headers
        self._headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type":        "application/json",
        }

    # Public API
    def execute(self, deltas: list[OrderDelta]) -> ExecutionResult:
        """
        Submit market orders for every non-zero delta, then poll each
        accepted order once to capture fill confirmation.
        
        If every delta is zero the list is empty and no HTTP call is made.

        Flow:
          1. Submit all orders to Alpaca.
          2. Wait _FILL_POLL_DELAY_SECONDS to allow market orders to fill.
          3. For each order that was accepted (has an alpaca_order_id),
             call GET /v2/orders/{id} once and record the fill result.
          4. Build and return ExecutionResult.

        If Alpaca returns an error or the order has not yet reached 
        a terminal state, fill_status is set to "pending" and 
        filled_qty / filled_avg_price remain None. The rebalance record 
        is still written to the DB so no data is lost.

        Args:
            deltas: Output of calculator.calculate_deltas() - only non-zero
                    deltas should be present, but a zero-delta guard is applied
                    defensively inside this method as well.

        Returns:
            ExecutionResult with per-order outcomes and a rolled-up status.
        """
        # Do nothing when delta list is empty
        if not deltas:
            logger.info("No deltas to execute - skipping order submission.")
            return ExecutionResult(
                orders=[],
                status="failed",
                error_message="No orders submitted: all deltas are zero.",
            )

        # 1. Submit all orders
        order_results: list[OrderResult] = []

        for delta in deltas:
            # Skip any zero-delta entry that should not have been included
            if delta.delta == 0:
                logger.debug("Skipping zero-delta for %s", delta.symbol)
                continue

            result = self._submit_order(delta)
            order_results.append(result)

        # 2. Wait for market orders to fill
        # Only wait when at least one order was successfully accepted.
        accepted = [r for r in order_results if r.success and r.alpaca_order_id]
        if accepted:
            logger.info(
                "Waiting %.1fs before polling fill status for %d order(s)...",
                _FILL_POLL_DELAY_SECONDS,
                len(accepted),
            )
            time.sleep(_FILL_POLL_DELAY_SECONDS)

            # 3. Poll fill status for each accepted order
            for result in accepted:
                self._poll_fill(result)

        return self._build_execution_result(order_results)

    # Internal helpers
    def _submit_order(self, delta: OrderDelta) -> OrderResult:
        """
        POST one market order to Alpaca /v2/orders.

        delta > 0 -> buy
        delta < 0 -> sell
        Returns an OrderResult regardless of success or failure.
        """
        side = "buy" if delta.delta > 0 else "sell"
        qty  = abs(delta.delta)

        payload = {
            "symbol":        delta.symbol,
            "qty":           str(qty),      # Alpaca expects a string quantity
            "side":          side,
            "type":          "market",
            "time_in_force": "day",         # standard for market orders
        }

        url = f"{self._base_url}/v2/orders"
        logger.info(
            "Submitting %s order | symbol=%s qty=%d url=%s",
            side, delta.symbol, qty, url,
        )

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout:
            error_msg = (
                f"Order for {delta.symbol} timed out after "
                f"{_REQUEST_TIMEOUT_SECONDS}s."
            )
            logger.error(error_msg)
            return OrderResult(
                symbol=delta.symbol,
                side=side,
                qty=qty,
                error=error_msg,
            )

        except requests.exceptions.ConnectionError as exc:
            error_msg = f"Network error submitting order for {delta.symbol}: {exc}"
            logger.error(error_msg)
            return OrderResult(
                symbol=delta.symbol,
                side=side,
                qty=qty,
                error=error_msg,
            )

        except requests.exceptions.HTTPError:
            status_code = response.status_code
            error_msg = (
                f"Alpaca rejected order for {delta.symbol}: "
                f"HTTP {status_code} - {response.text}"
            )
            logger.error(error_msg)
            return OrderResult(
                symbol=delta.symbol,
                side=side,
                qty=qty,
                error=error_msg,
            )

        # Success path - capture Alpaca's order ID from the response body
        body = response.json()
        alpaca_order_id = body.get("id")

        logger.info(
            "Order accepted | symbol=%s side=%s qty=%d alpaca_id=%s",
            delta.symbol, side, qty, alpaca_order_id,
        )

        return OrderResult(
            symbol=delta.symbol,
            side=side,
            qty=qty,
            alpaca_order_id=alpaca_order_id,
            success=True,
        )

    def _poll_fill(self, result: OrderResult) -> None:
        """
        Query Alpaca once for the fill status of an already-submitted order
        and update the OrderResult in-place.

        This method intentionally never raises: a polling failure is logged
        and fill_status is set to "pending" so the rest of the pipeline can
        continue and still persist a complete or incomplete record to DB.

        Updates on result (in-place):
            fill_status      - Alpaca lifecycle status string, or "pending" on error.
            filled_qty       - float shares executed, or None.
            filled_avg_price - float average price, or None.
        """
        order_id = result.alpaca_order_id
        try:
            body = self._alpaca_client.get_order(order_id)
        except AlpacaError as exc:
            # Polling failed - mark as pending so the caller can still save the record
            logger.warning(
                "Fill poll failed for order %s (%s): %s - marking as pending",
                order_id, result.symbol, exc,
            )
            result.fill_status = "pending"
            return

        alpaca_status = body.get("status", "unknown")
        result.fill_status = alpaca_status

        if alpaca_status in _TERMINAL_FILL_STATUSES:
            # Parse filled_qty - Alpaca returns it as a string, e.g. "10" or "0"
            raw_qty   = body.get("filled_qty")
            raw_price = body.get("filled_avg_price")

            result.filled_qty = float(raw_qty) if raw_qty else None
            result.filled_avg_price = (
                float(raw_price) if raw_price else None
            )
            logger.info(
                "Fill confirmed | order_id=%s symbol=%s status=%s "
                "filled_qty=%s filled_avg_price=%s",
                order_id, result.symbol, alpaca_status,
                result.filled_qty, result.filled_avg_price,
            )
        else:
            # Order has not yet reached a terminal state within the poll window.
            # Leave filled_qty and filled_avg_price as None.
            logger.info(
                "Order %s (%s) not yet terminal after poll: status=%s",
                order_id, result.symbol, alpaca_status,
            )

    @staticmethod
    def _build_execution_result(order_results: list[OrderResult]) -> ExecutionResult:
        """
        Determine the overall ExecutionStatus from individual OrderResult outcomes.

        Rules:
            all succeeded  -> "success",  error_message = None
            some succeeded -> "partial",  error_message = combined errors
            none succeeded -> "failed",   error_message = combined errors
        """
        if not order_results:
            return ExecutionResult(
                orders=[],
                status="failed",
                error_message="No orders were attempted.",
            )

        succeeded = [r for r in order_results if r.success]
        failed    = [r for r in order_results if not r.success]

        # Collect all error messages from failed orders into one string
        combined_errors: str | None = None
        if failed:
            combined_errors = "; ".join(
                f"{r.symbol}: {r.error}" for r in failed
            )

        if len(failed) == 0:
            status: ExecutionStatus = "success"
        elif len(succeeded) == 0:
            status = "failed"
        else:
            status = "partial"

        return ExecutionResult(
            orders=order_results,
            status=status,
            error_message=combined_errors,
        )
