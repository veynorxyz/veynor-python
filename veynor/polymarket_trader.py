"""
Polymarket order execution via the CLOB API.

Auth model: non-custodial. Your private key never leaves your machine.
The key is read from the POLYMARKET_PRIVATE_KEY environment variable.

    export POLYMARKET_PRIVATE_KEY=0x...

Credentials are derived on the fly from your wallet signature.
No key is stored, sent to Veynor, or logged.

Requires: pip install veynor[trade]
  (installs py-clob-client and eth-account as optional extras)
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# ── Lazy import guard ──────────────────────────────────────────────────────────

def _require_trade_deps() -> None:
    missing = []
    try:
        import py_clob_client  # noqa: F401
    except ImportError:
        missing.append("py-clob-client")
    try:
        import eth_account  # noqa: F401
    except ImportError:
        missing.append("eth-account")
    if missing:
        deps = " ".join(missing)
        print(
            f"Trading requires extra packages: pip install {deps}\n"
            f"Or install all at once: pip install veynor[trade]",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Constants ──────────────────────────────────────────────────────────────────

CLOB_HOST     = "https://clob.polymarket.com"
CHAIN_ID      = 137          # Polygon mainnet
USDC_DECIMALS = 6


# ── Trader ─────────────────────────────────────────────────────────────────────

class PolymarketTrader:
    """
    Thin wrapper around py-clob-client for Polymarket order execution.

    Usage:
        trader = PolymarketTrader()          # reads POLYMARKET_PRIVATE_KEY
        print(trader.get_balance())
        trader.market_buy(token_id, amount_usdc=50.0)
    """

    def __init__(self, private_key: Optional[str] = None) -> None:
        _require_trade_deps()

        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        pk = private_key or os.environ.get("POLYMARKET_PRIVATE_KEY")
        if not pk:
            print(
                "No private key found. Set POLYMARKET_PRIVATE_KEY.\n"
                "Example: export POLYMARKET_PRIVATE_KEY=0x...",
                file=sys.stderr,
            )
            sys.exit(1)

        # Normalise key format
        if not pk.startswith("0x"):
            pk = "0x" + pk

        # Build client — L1 auth only first, then derive L2 creds
        self._client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=pk,
        )

        # Derive L2 API credentials from the wallet (no server call needed)
        try:
            creds: ApiCreds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
        except Exception as exc:
            print(f"Failed to derive API credentials: {exc}", file=sys.stderr)
            sys.exit(1)

        self._pk = pk

    # ── Account ────────────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """
        Returns USDC balance and allowance on Polymarket (Polygon).
        Uses get_balance_allowance() which is the actual ClobClient method.
        Amounts are converted from raw integer to human-readable USDC.
        """
        try:
            from py_clob_client.clob_types import AssetType
            raw = self._client.get_balance_allowance(
                params={"asset_type": AssetType.COLLATERAL}
            )
            # Response: {"balance": "1000000", "allowance": "1000000", ...}
            balance   = float(raw.get("balance",   0)) / 10 ** USDC_DECIMALS
            allowance = float(raw.get("allowance", 0)) / 10 ** USDC_DECIMALS
            return {
                "balance_usdc":   round(balance, 2),
                "allowance_usdc": round(allowance, 2),
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def get_positions(self) -> list[dict]:
        """
        Returns recent trades as a proxy for open positions.
        Uses get_trades() which is the actual ClobClient method.
        """
        try:
            raw = self._client.get_trades()
            # raw is a dict with a "data" list
            trades = raw if isinstance(raw, list) else raw.get("data", [])
            positions = []
            for p in trades:
                positions.append({
                    "market":        p.get("market", p.get("market_slug", "")),
                    "token_id":      p.get("asset_id", p.get("outcome_index", "")),
                    "side":          p.get("side", "?"),
                    "size":          float(p.get("size", 0)),
                    "price":         float(p.get("price", 0)),
                    "status":        p.get("status", ""),
                    "trade_id":      p.get("id", ""),
                })
            return positions
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    # ── Orders ─────────────────────────────────────────────────────────────────

    def market_buy(self, token_id: str, amount_usdc: float) -> dict:
        """
        Place a market BUY for `amount_usdc` worth of shares on `token_id`.
        token_id is the YES/NO outcome token address on Polygon.
        Returns the order response dict from the CLOB.
        """
        return self._market_order(token_id, amount_usdc, side="BUY")

    def market_sell(self, token_id: str, amount_shares: float) -> dict:
        """
        Place a market SELL of `amount_shares` shares of `token_id`.
        """
        return self._market_order(token_id, amount_shares, side="SELL")

    def _market_order(self, token_id: str, amount: float, side: str) -> dict:
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            clob_side = BUY if side == "BUY" else SELL

            args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
            )
            signed = self._client.create_market_order(args)
            resp   = self._client.post_order(signed, OrderType.FOK)
            return {
                "status":    resp.get("status", resp.get("orderStatus", "unknown")),
                "order_id":  resp.get("orderID", resp.get("id", "")),
                "side":      side,
                "token_id":  token_id,
                "amount":    amount,
                "raw":       resp,
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open limit order by ID."""
        try:
            resp = self._client.cancel(order_id)
            return {"cancelled": resp.get("not_cancelled", []) == [], "raw": resp}
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def get_open_orders(self) -> list[dict]:
        """Returns open limit orders."""
        try:
            raw = self._client.get_orders()
            return raw if isinstance(raw, list) else raw.get("data", [])
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc


# ── Errors ─────────────────────────────────────────────────────────────────────

class PolymarketError(Exception):
    pass
