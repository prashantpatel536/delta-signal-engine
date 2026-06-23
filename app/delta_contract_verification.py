"""Fetch and verify Delta Exchange contract specifications against live API."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.config import DELTA_API_BASE_URL
from app.contract_specs import DELTA_CONTRACT_SIZES

logger = logging.getLogger(__name__)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# Documented formulas aligned with Delta Exchange user guide (USDT-settled linear perpetuals)
# https://guides.delta.exchange/delta-exchange-user-guide/derivatives-guide/docs
# https://guides.delta.exchange/delta-exchange-user-guide/trading-guide/margin-explainer/margin-explainer
DELTA_FORMULAS: dict[str, str] = {
    "quantity_base": "quantity = contracts × contract_value",
    "position_notional": "position_notional = contracts × contract_value × mark_price",
    "pnl_long_usdt": "PnL (long) = contracts × contract_value × (exit_price − entry_price)",
    "pnl_short_usdt": "PnL (short) = contracts × contract_value × (entry_price − exit_price)",
    "initial_margin_isolated": (
        "initial_margin = position_notional / leverage "
        "= (contracts × contract_value × mark_price) / leverage"
    ),
    "initial_margin_pct_form": (
        "initial_margin = contracts × contract_value × mark_price × initial_margin_pct "
        "(where initial_margin_pct ≈ 1/leverage below position threshold)"
    ),
    "contracts_from_budget": (
        "contracts = floor(margin_budget × leverage / (contract_value × entry_price))"
    ),
}


def fetch_delta_products() -> dict[str, dict[str, Any]]:
    """Load live product specs from Delta Exchange REST API."""
    url = f"{DELTA_API_BASE_URL}/products"
    req = urllib.request.Request(url, headers={"User-Agent": "delta-signal-engine-audit/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Delta products fetch failed: %s", exc)
        return {}

    lookup: dict[str, dict[str, Any]] = {}
    for product in payload.get("result", []):
        symbol = product.get("symbol")
        if symbol in SYMBOLS:
            lookup[symbol] = product
    return lookup


def _lot_size_display(product: dict[str, Any]) -> str:
    raw = product.get("lot_size")
    if raw is not None:
        return str(raw)
    # USDT linear perpetuals: minimum increment is 1 contract when lot_size is unset
    return "1 contract (minimum order increment)"


def verify_symbol_spec(symbol: str, product: dict[str, Any] | None) -> dict[str, Any]:
    """Compare portal config against live Delta API for one symbol."""
    configured_size = DELTA_CONTRACT_SIZES.get(symbol)
    if product is None:
        return {
            "symbol": symbol,
            "verified": False,
            "error": "Product not returned by Delta API",
            "configured_contract_size": configured_size,
        }

    live_size = float(product.get("contract_value") or 0)
    size_match = abs(live_size - float(configured_size or 0)) < 1e-12

    return {
        "symbol": symbol,
        "verified": size_match and product.get("state") == "live",
        "contract_size": live_size,
        "configured_contract_size": configured_size,
        "contract_size_match": size_match,
        "contract_unit_currency": product.get("contract_unit_currency"),
        "contract_type": product.get("contract_type"),
        "settling_asset": (product.get("settling_asset") or {}).get("symbol"),
        "quoting_asset": (product.get("quoting_asset") or {}).get("symbol"),
        "lot_size": _lot_size_display(product),
        "lot_size_raw": product.get("lot_size"),
        "tick_size": product.get("tick_size"),
        "position_size_limit": product.get("position_size_limit"),
        "initial_margin_scaling": product.get("initial_margin"),
        "maintenance_margin_scaling": product.get("maintenance_margin"),
        "impact_size": product.get("impact_size"),
        "state": product.get("state"),
        "quantity_formula": DELTA_FORMULAS["quantity_base"],
        "margin_formula": DELTA_FORMULAS["initial_margin_isolated"],
        "pnl_formula_long": DELTA_FORMULAS["pnl_long_usdt"],
        "pnl_formula_short": DELTA_FORMULAS["pnl_short_usdt"],
        "portal_contracts_formula": DELTA_FORMULAS["contracts_from_budget"],
        "documentation_urls": [
            "https://guides.delta.exchange/delta-exchange-user-guide/derivatives-guide/docs",
            "https://guides.delta.exchange/delta-exchange-user-guide/trading-guide/margin-explainer/margin-explainer",
            f"https://api.delta.exchange/v2/products (symbol={symbol})",
        ],
    }


def verify_all_contract_specs() -> dict[str, Any]:
    """Verify BTC/ETH/SOL specs against live Delta Exchange API."""
    products = fetch_delta_products()
    symbols: dict[str, Any] = {}
    all_verified = True

    for symbol in SYMBOLS:
        spec = verify_symbol_spec(symbol, products.get(symbol))
        symbols[symbol] = spec
        if not spec.get("verified"):
            all_verified = False

    return {
        "all_verified": all_verified,
        "source": f"{DELTA_API_BASE_URL}/products",
        "formulas": DELTA_FORMULAS,
        "symbols": symbols,
    }
