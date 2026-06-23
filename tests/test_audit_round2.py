"""Tests for audit round 2 endpoints logic."""

from app.services.audit_service import audit_service


def test_trade_replay_validation_structure():
    result = audit_service.trade_replay_validation(limit=5)
    assert "trades" in result
    assert "all_verified" in result
    for row in result["trades"]:
        assert "manual_pnl" in row
        assert "verified" in row


def test_missed_profit_by_symbol_structure():
    result = audit_service.missed_profit_by_symbol()
    assert "symbols" in result
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert symbol in result["symbols"]
        data = result["symbols"][symbol]
        assert "gross_profit_usd" in data
        assert "gross_loss_usd" in data
        assert "net_usd_recomputed" in data


def test_strategy_reality_check():
    result = audit_service.strategy_reality_check()
    assert "strategy_return_pct" in result
    assert "maximum_drawdown_pct" in result
    assert "sharpe_like_score" in result


def test_portfolio_simulator_scenarios():
    result = audit_service.portfolio_simulator(starting_capital=1000.0)
    scenarios = result["scenarios"]
    assert "approved_trades_only" in scenarios
    assert "all_generated_signals" in scenarios
    assert "missed_winners_only" in scenarios
    for key, scenario in scenarios.items():
        assert "equity_curve" in scenario
        assert len(scenario["equity_curve"]) >= 1
