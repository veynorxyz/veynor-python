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

import requests

DATA_API = "https://data-api.polymarket.com"

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

PUSD_CONTRACT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"  # pUSD CollateralToken (proxy)
POLYGON_RPC   = "https://polygon.publicnode.com"

# ERC-20 balanceOf(address) selector + 32-byte padded address
def _balance_of_calldata(address: str) -> str:
    addr = address.lower().replace("0x", "").zfill(64)
    return "0x70a08231" + addr


# ── Trader ─────────────────────────────────────────────────────────────────────

class PolymarketTrader:
    """
    Thin wrapper around py-clob-client for Polymarket order execution.

    Usage:
        trader = PolymarketTrader()          # reads POLYMARKET_PRIVATE_KEY
        print(trader.get_balance())
        trader.market_buy(token_id, amount_usdc=50.0)
    """

    def __init__(self, private_key: Optional[str] = None, proxy_address: Optional[str] = None) -> None:
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
        # Proxy/account address for data API queries (differs from signing key for Magic users)
        self._proxy_address = proxy_address or os.environ.get("POLYMARKET_ADDRESS")

    # ── Account ────────────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """
        Returns cash (pUSD on-chain balance) and portfolio value.
        pUSD balance queried directly from the CollateralToken contract on Polygon.
        Position values from Polymarket data API.
        """
        try:
            addr = self._proxy_address or self._client.get_address()

            # 1. pUSD cash balance — direct on-chain query
            rpc_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                "params": [
                    {"to": PUSD_CONTRACT, "data": _balance_of_calldata(addr)},
                    "latest",
                ],
            }
            rpc_resp = requests.post(POLYGON_RPC, json=rpc_payload, timeout=10)
            rpc_resp.raise_for_status()
            hex_balance = rpc_resp.json().get("result", "0x0")
            cash = int(hex_balance, 16) / 10 ** USDC_DECIMALS

            # 2. Position values from data API
            pos_resp = requests.get(f"{DATA_API}/positions", params={"user": addr}, timeout=10)
            pos_resp.raise_for_status()
            positions = pos_resp.json()
            positions_value = sum(float(p.get("currentValue", 0)) for p in positions)

            total_value = cash + positions_value

            return {
                "address":         addr,
                "cash_usdc":       round(cash, 2),
                "positions_value": round(positions_value, 2),
                "total_value":     round(total_value, 2),
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def get_positions(self) -> list[dict]:
        """
        Returns open positions from Polymarket's data API.
        Works for all account types including Magic/proxy wallets.
        """
        try:
            addr = self._proxy_address or self._client.get_address()
            resp = requests.get(f"{DATA_API}/positions", params={"user": addr}, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            positions = []
            for p in raw:
                positions.append({
                    "title":          p.get("title", ""),
                    "outcome":        p.get("outcome", "?"),
                    "size":           float(p.get("size", 0)),
                    "avg_price":      float(p.get("avgPrice", 0)),
                    "current_price":  float(p.get("curPrice", 0)),
                    "current_value":  float(p.get("currentValue", 0)),
                    "cash_pnl":       float(p.get("cashPnl", 0)),
                    "percent_pnl":    float(p.get("percentPnl", 0)),
                    "realized_pnl":   float(p.get("realizedPnl", 0)),
                    "end_date":       p.get("endDate", ""),
                    "asset":          p.get("asset", ""),
                    "redeemable":     p.get("redeemable", False),
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
