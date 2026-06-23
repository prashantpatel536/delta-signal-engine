"""Tests for Delta-style risk engine calculations."""

from app.risk_engine import (
    APPLIED_RISK_ACCOUNT_PCT,
    build_risk_matrix_row,
    build_signal_risk_profile,
    distance_to_liquidation,
    enforce_trade_params,
    liq_status_from_buffer,
    missed_opportunity_metrics,
    point_distance_for_account_impact,
)


def test_point_distance_btc_20pct_account_loss():
    # 50% margin, 25x → divisor 1250
    dist = point_distance_for_account_impact(100_000, 20.0)
    assert dist == round(100_000 * 20 / 1250, 4)


def test_enforce_trade_params_defaults():
    lev, pct = enforce_trade_params(None, None)
    assert lev == 25.0
    assert pct == 50.0


def test_liquidation_distance_25x():
    dist = distance_to_liquidation("BUY", 100_000, 25)
    assert dist == round(100_000 / 25, 4)


def test_liq_status_thresholds():
    assert liq_status_from_buffer(2.5) == "SAFE"
    assert liq_status_from_buffer(1.5) == "CAUTION"
    assert liq_status_from_buffer(0.8) == "DANGER"


def test_build_signal_risk_profile_includes_liq_fields():
    profile = build_signal_risk_profile(
        side="BUY",
        entry=100_000,
        structure_stop_loss=99_000,
        structure_take_profit=102_000,
        balance=1000,
    )
    assert profile.risk_pct == APPLIED_RISK_ACCOUNT_PCT
    assert profile.liq_status in {"SAFE", "CAUTION", "DANGER"}
    assert profile.liquidation_price < 100_000
    assert profile.liq_buffer > 0


def test_risk_matrix_row_keys():
    row = build_risk_matrix_row("BTCUSDT", 50_000, 1000)
    assert row["symbol"] == "BTCUSDT"
    assert row["risk_20pct_distance"] > 0
    assert row["reward_50pct_distance"] > 0


def test_missed_opportunity_metrics():
    metrics = missed_opportunity_metrics("BUY", 100, 110, 1000)
    assert metrics["points"] == 10
    assert metrics["pnl_usd"] > 0
    assert metrics["roe_pct"] > 0
    assert metrics["account_impact_pct"] > 0
