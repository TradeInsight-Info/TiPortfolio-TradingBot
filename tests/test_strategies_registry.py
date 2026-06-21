import pytest
from app import strategies_registry as reg


def test_registry_has_three_strategies():
    ids = {s["id"] for s in reg.list_strategies()}
    assert ids == {"vix", "trend_broad", "pit_top5"}


def test_get_strategy_fields():
    s = reg.get_strategy("trend_broad")
    assert s["name"]
    assert isinstance(s["universe"], list) and s["universe"]
    assert s["alpaca_key_env"] and s["alpaca_secret_env"]
    assert s["benchmark"]


def test_get_unknown_strategy_raises():
    with pytest.raises(KeyError):
        reg.get_strategy("nope")
