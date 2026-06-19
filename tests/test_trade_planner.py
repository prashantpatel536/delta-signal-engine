"""Tests for trade plan calculation."""

from app.trade_planner import build_trade_plan


def test_buy_trade_plan():
    plan = build_trade_plan("BUY", 1776.65, hh50=1800.0, ll50=1767.0)
    assert plan.entry == 1776.65
    assert plan.stop_loss == 1767.0
    assert plan.take_profit == round(1776.65 + (1776.65 - 1767.0) * 2, 2)
    assert plan.risk_reward == 2.0


def test_sell_trade_plan():
    plan = build_trade_plan("SELL", 1776.65, hh50=1800.0, ll50=1767.0)
    assert plan.entry == 1776.65
    assert plan.stop_loss == 1800.0
    assert plan.take_profit == round(1776.65 - (1800.0 - 1776.65) * 2, 2)
    assert plan.risk_reward == 2.0
