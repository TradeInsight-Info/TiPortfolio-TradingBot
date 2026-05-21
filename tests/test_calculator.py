"""
Unit tests for calculate_deltas().

All tests use local fixtures - no network calls, no Flask app, no database.
"""

from __future__ import annotations

import math
import pytest
from app.calculator import OrderDelta, calculate_deltas

# Shared fixtures
@pytest.fixture()
def portfolio_value() -> float:
    return 10_000.0

@pytest.fixture()
def prices() -> dict[str, float]:
    return {"SPY": 500.0, "QQQ": 400.0, "GLD": 200.0}

# floor(portfolio_value * weight / price) - current_shares
class TestDeltaFormula:
    def test_basic_buy_calculation(self, portfolio_value, prices):
        """
        floor(10000 * 0.6 / 500) = 12; held 10 -> delta +2
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.6},
            current_positions={"SPY": 10.0},
            current_prices=prices,
        )
        assert len(result) == 1
        delta = result[0]
        assert delta.symbol == "SPY"
        assert delta.target_shares == math.floor(10_000 * 0.6 / 500)
        assert delta.delta == 12 - 10

    def test_fractional_target_shares(self, portfolio_value):
        """
        $10 000 * 0.33 / 500 = 6.6 -> target_shares=6.6, delta=6.6 (fractional allowed)
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.33},
            current_positions={"SPY": 0.0},
            current_prices={"SPY": 500.0},
        )
        assert result[0].target_shares == pytest.approx(6.6)
        assert result[0].delta == pytest.approx(6.6)

    def test_sells_when_holding_more_than_target(self, portfolio_value, prices):
        """
        floor(10000 * 0.1 / 500) = 2; held 10 -> delta -8
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.1},
            current_positions={"SPY": 10.0},
            current_prices=prices,
        )
        assert result[0].delta == 2 - 10

# New symbol (not currently held) -> positive delta
class TestNewSymbolProducesBuy:
    def test_symbol_not_held_generates_buy(self, portfolio_value, prices):
        """
        QQQ not in positions; floor(10000 * 0.4 / 400) = 10 -> delta +10
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"QQQ": 0.4},
            current_positions={},
            current_prices=prices,
        )
        assert len(result) == 1
        assert result[0].symbol == "QQQ"
        assert result[0].delta > 0

    def test_multiple_new_symbols_all_positive(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.5, "GLD": 0.5},
            current_positions={},
            current_prices=prices,
        )
        for od in result:
            assert od.delta > 0, f"Expected positive delta for {od.symbol}"

    def test_new_symbol_current_shares_is_zero(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"QQQ": 0.4},
            current_positions={},
            current_prices=prices,
        )
        assert result[0].current_shares == 0.0

# Held symbol absent from target -> full sell (negative delta)
class TestFullExitWhenAbsentFromTarget:
    def test_held_symbol_not_in_target_produces_negative_delta(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={},
            current_positions={"SPY": 15.0},
            current_prices=prices,
        )
        assert len(result) == 1
        assert result[0].symbol == "SPY"
        assert result[0].delta == -15

    def test_full_exit_delta_equals_negative_current_shares(self, portfolio_value, prices):
        current = {"SPY": 7.0, "QQQ": 3.0}
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={},
            current_positions=current,
            current_prices=prices,
        )
        deltas_by_symbol = {od.symbol: od.delta for od in result}
        assert deltas_by_symbol["SPY"] == -7
        assert deltas_by_symbol["QQQ"] == -3

    def test_full_exit_target_shares_is_zero(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={},
            current_positions={"GLD": 5.0},
            current_prices=prices,
        )
        assert result[0].target_shares == 0

# Delta == 0 -> no order generated
class TestZeroDeltaGeneratesNoOrder:
    def test_exact_target_shares_already_held_produces_no_order(self, portfolio_value, prices):
        """
        floor(10000 * 0.5 / 500) = 10; already holding 10 -> skip
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.5},
            current_positions={"SPY": 10.0},
            current_prices=prices,
        )
        assert result == []

    def test_mixed_symbols_zero_delta_excluded(self, portfolio_value, prices):
        """
        SPY: no change needed; QQQ: needs a buy -> only QQQ in result
        """
        # floor(10000 * 0.5 / 500) = 10 -> hold 10 already, delta 0
        # floor(10000 * 0.25 / 400) = 6 -> hold 0, delta +6
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.5, "QQQ": 0.25},
            current_positions={"SPY": 10.0, "QQQ": 0.0},
            current_prices=prices,
        )
        symbols = {od.symbol for od in result}
        assert "SPY" not in symbols
        assert "QQQ" in symbols

    def test_empty_positions_and_zero_weight_produces_no_order(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={},
            current_positions={},
            current_prices=prices,
        )
        assert result == []

# Edge cases
class TestEdgeCases:
    def test_result_elements_are_order_delta_instances(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"QQQ": 0.5, "SPY": 0.5},
            current_positions={},
            current_prices=prices,
        )
        assert isinstance(result[1], OrderDelta)
    
    def test_fractional_current_shares_used_exactly_for_delta(self, portfolio_value, prices):
        """
        Alpaca may return fractional qty (e.g. 10.7).
        round(10000 * 0.6 / 500, 6) = 12.0; delta = 12.0 - 10.7 = 1.3.
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"SPY": 0.6},
            current_positions={"SPY": 10.7},
            current_prices=prices,
        )
        assert result[0].delta == pytest.approx(1.3)

    def test_high_price_symbol_may_produce_zero_target_shares(self, portfolio_value):
        """
        floor(10000 * 0.001 / 50000) = 0; held 0 -> delta 0 -> no order
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"BRK": 0.001},
            current_positions={},
            current_prices={"BRK": 50_000.0},
        )
        assert result == []

    def test_high_price_symbol_held_sells_down_to_fractional_target(self, portfolio_value):
        """
        round(10000 * 0.001 / 50000, 6) = 0.0002; held 1.0 -> delta = 0.0002 - 1.0 = -0.9998
        """
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"BRK": 0.001},
            current_positions={"BRK": 1.0},
            current_prices={"BRK": 50_000.0},
        )
        assert len(result) == 1
        assert result[0].delta == pytest.approx(-0.9998)

    def test_invalid_portfolio_value_raises(self, prices):
        with pytest.raises(ValueError, match="portfolio_value"):
            calculate_deltas(
                portfolio_value=0,
                target_weights={"SPY": 1.0},
                current_positions={},
                current_prices=prices,
            )

    def test_negative_portfolio_value_raises(self, prices):
        with pytest.raises(ValueError, match="portfolio_value"):
            calculate_deltas(
                portfolio_value=-100.0,
                target_weights={"SPY": 1.0},
                current_positions={},
                current_prices=prices,
            )

    def test_missing_price_raises(self, portfolio_value):
        with pytest.raises(ValueError, match="No price found for symbol"):
            calculate_deltas(
                portfolio_value=portfolio_value,
                target_weights={"TSLA": 1.0},
                current_positions={},
                current_prices={},
            )

    def test_zero_price_raises(self, portfolio_value):
        with pytest.raises(ValueError, match="Price for"):
            calculate_deltas(
                portfolio_value=portfolio_value,
                target_weights={"SPY": 1.0},
                current_positions={},
                current_prices={"SPY": 0.0},
            )

    def test_output_is_sorted_by_symbol(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"QQQ": 0.4, "GLD": 0.3, "SPY": 0.3},
            current_positions={},
            current_prices=prices,
        )
        symbols = [od.symbol for od in result]
        assert symbols == sorted(symbols)

    def test_order_delta_is_immutable(self, portfolio_value, prices):
        result = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights={"QQQ": 1.0},
            current_positions={},
            current_prices=prices,
        )
        with pytest.raises((AttributeError, TypeError)): # errors that may be caught by different Python versions
            result[0].delta = 999   # frozen=True on dataclass
