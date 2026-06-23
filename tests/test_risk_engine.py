"""Tests for Delta-style risk engine calculations."""

from app.risk_engine import (
    build_risk_matrix_row,
    build_signal_risk_profile,
    distance_to_liquidation,
    enforce_trade_params,
    liq_status_from_buffer,
    missed_opportunity_metrics,
    point_distance_for_account_impact,
)


def test_point_distance_btc_20pct_account_loss():
    dist = point_distance_for_account_impact(100_000, 20.0)
    assert dist == round(100_000 * 20 / 1250, 4)


def test_enforce_trade_params_defaults():
    lev, pct = enforce_trade_params(None, None)
    assert lev == 25.0
    assert pct == 50.0


def test_enforce_trade_params_overrides_input():
    lev, pct = enforce_trade_params(10, 25)
    assert lev == 25.0
    assert pct == 50.0


def test_liquidation_distance_25x():
    dist = distance_to_liquidation("BUY", 100_000, 25)
    assert dist == round(100_000 / 25, 4)


def test_liq_status_thresholds():
    assert liq_status_from_buffer(2.5) == "SAFE"
    assert liq_status_from_buffer(1.5) == "CAUTION"
    assert liq_status_from_buffer(0.8) == "DANGER"


def test_build_signal_risk_profile_liq_safe():
    profile = build_signal_risk_profile(
        side="BUY",
        entry=100_000,
        stop_loss=99_000,
        take_profit=102_000,
        balance=1000,
        symbol="BTCUSDT",
    )
    assert profile.liq_safe is True
    assert profile.liquidation_price < 99_000
    assert profile.risk_reward >= 2.0
    assert profile.contracts >= 1


def test_risk_matrix_row_keys():
    row = build_risk_matrix_row("BTCUSDT", 50_000, 1000)
    assert row["symbol"] == "BTCUSDT"
    assert row["risk_20pct_distance"] > 0


def test_missed_opportunity_metrics_sol_contracts():
    metrics = missed_opportunity_metrics("BUY", 150, 153, 1000, "SOLUSDT")
    assert metrics["points"] == 3
    assert metrics["contracts"] >= 1
    assert metrics["pnl_usd"] > 0
