"""Tests for canonical Delta calculator."""

from app.delta_calculator import compute_trade_metrics, sample_calculation, validate_stored_trade


def test_btc_sizing_1000_balance():
    metrics = compute_trade_metrics(
        side="BUY",
        entry=100_000.0,
        exit_price=100_505.0,
        balance=1000.0,
        symbol="BTCUSDT",
        stop_loss=99_500.0,
    )
    assert metrics["contracts"] == 125
    assert metrics["quantity"] == 0.125
    assert metrics["pnl_usd"] == round(505 * 0.125, 2)


def test_eth_sizing_1000_balance():
    metrics = compute_trade_metrics(
        side="BUY",
        entry=3500.0,
        exit_price=3566.0,
        balance=1000.0,
        symbol="ETHUSDT",
        stop_loss=3460.0,
    )
    assert metrics["contracts"] == 357
    assert abs(metrics["quantity"] - 3.57) < 0.001
    assert metrics["pnl_usd"] == round(66 * 3.57, 2)


def test_sol_sizing_1000_balance():
    metrics = compute_trade_metrics(
        side="BUY",
        entry=150.0,
        exit_price=153.0,
        balance=1000.0,
        symbol="SOLUSDT",
        stop_loss=148.0,
    )
    assert metrics["contracts"] == 83
    assert metrics["quantity"] == 83.0
    assert metrics["pnl_usd"] == 249.0


def test_validate_stored_trade_within_tolerance():
    check = validate_stored_trade(
        side="BUY",
        entry=100_000.0,
        exit_price=100_505.0,
        quantity=0.125,
        margin_used=500.0,
        pnl=63.12,
        balance_at_open=1000.0,
        symbol="BTCUSDT",
        stop_loss=99_500.0,
    )
    assert check["within_1pct"] is True


def test_sample_calculations_include_roe():
    sample = sample_calculation("BTCUSDT", 100_000.0, 100_505.0)
    assert sample["roe_pct"] > 0
    assert sample["margin_used"] == 500.0
