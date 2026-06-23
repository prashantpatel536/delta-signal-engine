"""Tests for Delta contract verification against live API."""

from app.delta_contract_verification import (
    DELTA_FORMULAS,
    fetch_delta_products,
    verify_all_contract_specs,
)
from app.contract_specs import DELTA_CONTRACT_SIZES


def test_formulas_documented():
    assert "quantity_base" in DELTA_FORMULAS
    assert "initial_margin_isolated" in DELTA_FORMULAS


def test_live_api_returns_all_symbols():
    products = fetch_delta_products()
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert symbol in products
        assert float(products[symbol]["contract_value"]) == DELTA_CONTRACT_SIZES[symbol]


def test_verify_all_contract_specs():
    report = verify_all_contract_specs()
    assert report["all_verified"] is True
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        spec = report["symbols"][symbol]
        assert spec["contract_size_match"] is True
        assert spec["quantity_formula"]
        assert spec["margin_formula"]
