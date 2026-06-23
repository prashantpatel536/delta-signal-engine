"""Tests for trade plan calculation."""

from app.trade_planner import build_trade_plan


def test_buy_trade_plan_eth_min_sl():
    plan = build_trade_plan(
        "BUY", 1776.65, hh50=1800.0, ll50=1767.0, symbol="ETHUSDT", balance=1000.0
    )
    assert plan.entry == 1776.65
    assert plan.stop_loss == round(1776.65 - 15.0, 2)
    assert plan.sl_distance_points == 15.0
    assert plan.risk_reward >= 2.0


def test_sell_trade_plan_eth_structure_sl():
    plan = build_trade_plan(
        "SELL", 1776.65, hh50=1800.0, ll50=1767.0, symbol="ETHUSDT", balance=1000.0
    )
    assert plan.entry == 1776.65
    assert plan.stop_loss == 1800.0
    assert plan.sl_distance_points == round(1800.0 - 1776.65, 2)
    assert plan.risk_reward >= 2.0
