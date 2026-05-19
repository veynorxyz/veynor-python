"""
Polymarket V2 order execution via the CLOB API.

V2 EIP-712 order format — "Polymarket CTF Exchange" v2.
Struct: salt, maker, signer, tokenId, makerAmount, takerAmount, side,
        signatureType, timestamp, metadata, builder
(No feeRateBps, no taker, no expiration, no nonce — V1 only.)

Auth model: non-custodial. Your private key never leaves your machine.

    export POLYMARKET_PRIVATE_KEY=0x...
    export POLYMARKET_ADDRESS=0x...   # proxy/Magic wallet (optional)

Requires: pip install veynor[trade]
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import random
import sys
import time
from typing import Optional

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

DATA_API  = "https://data-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID  = 137
USDC_DECIMALS = 6

# ── V2 exchange contracts (live April 28 2026) ────────────────────────────────
CTF_EXCHANGE_ADDRESS         = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE_ADDRESS = "0xe2222d279d744050d28e00520010520000310F59"

# ── V2 EIP-712 domain ────────────────────────────────────────────────────────
V2_DOMAIN_NAME    = "Polymarket CTF Exchange"
V2_DOMAIN_VERSION = "2"

# ── V2 order struct ───────────────────────────────────────────────────────────
# Derived from @polymarket/clob-client-v2 source (CTF_EXCHANGE_V2_ORDER_STRUCT).
V2_ORDER_TYPES = {
    "Order": [
        {"name": "salt",          "type": "uint256"},
        {"name": "maker",         "type": "address"},
        {"name": "signer",        "type": "address"},
        {"name": "tokenId",       "type": "uint256"},
        {"name": "makerAmount",   "type": "uint256"},
        {"name": "takerAmount",   "type": "uint256"},
        {"name": "side",          "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
        {"name": "timestamp",     "type": "uint256"},
        {"name": "metadata",      "type": "bytes32"},
        {"name": "builder",       "type": "bytes32"},
    ]
}

BYTES32_ZERO = bytes(32)   # 32 zero bytes — default metadata + builder
SIDE_BUY  = 0
SIDE_SELL = 1

# signatureType values
SIG_EOA              = 0
SIG_POLY_PROXY       = 1
SIG_POLY_GNOSIS_SAFE = 2

# pUSD CollateralToken (proxy) — for balance queries
PUSD_CONTRACT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
POLYGON_RPC   = "https://polygon.publicnode.com"


def _to_units(amount: float) -> int:
    """Convert a decimal amount to USDC/token base units (6 decimals)."""
    return int(round(amount * 10 ** USDC_DECIMALS))


def _balance_of_calldata(address: str) -> str:
    addr = address.lower().replace("0x", "").zfill(64)
    return "0x70a08231" + addr


# ── Trader ────────────────────────────────────────────────────────────────────

class PolymarketTrader:
    """
    Polymarket V2 order execution.

    Usage:
        trader = PolymarketTrader()
        print(trader.get_balance())
        trader.market_buy(token_id, amount_usdc=10.0, neg_risk=True)
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        proxy_address: Optional[str] = None,
    ) -> None:
        pk = private_key or os.environ.get("POLYMARKET_PRIVATE_KEY")
        if not pk:
            print(
                "No private key found. Set POLYMARKET_PRIVATE_KEY.\n"
                "Example: export POLYMARKET_PRIVATE_KEY=0x...",
                file=sys.stderr,
            )
            sys.exit(1)
        if not pk.startswith("0x"):
            pk = "0x" + pk

        self._pk      = pk
        self._account = Account.from_key(pk)
        self._eoa     = self._account.address   # checksummed EOA

        raw_proxy = proxy_address or os.environ.get("POLYMARKET_ADDRESS")
        self._proxy  = to_checksum_address(raw_proxy) if raw_proxy else None
        self._maker  = self._proxy or self._eoa
        self._sig_type = SIG_POLY_PROXY if self._proxy else SIG_EOA

        # Derive L2 API credentials (py_clob_client still works for cred derivation)
        self._creds = self._derive_creds()

    # ── Credential derivation ─────────────────────────────────────────────────

    def _derive_creds(self):
        try:
            from py_clob_client.client import ClobClient  # type: ignore
            client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                key=self._pk,
                signature_type=self._sig_type,
                funder=self._proxy,
            )
            creds = client.create_or_derive_api_creds()
            return creds
        except Exception as exc:
            print(f"Failed to derive API credentials: {exc}", file=sys.stderr)
            sys.exit(1)

    # ── L2 HMAC auth ─────────────────────────────────────────────────────────

    def _l2_headers(self, method: str, path: str, body: str = "") -> dict:
        """Build POLY L2 auth headers for a signed request."""
        ts = str(int(time.time()))
        message = ts + method.upper() + path + (body or "")
        # secret is base64-encoded; decode with padding tolerance
        secret_bytes = base64.urlsafe_b64decode(self._creds.api_secret)
        sig = base64.urlsafe_b64encode(
            hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return {
            "Content-Type":    "application/json",
            "POLY_ADDRESS":    self._eoa,
            "POLY_SIGNATURE":  sig,
            "POLY_TIMESTAMP":  ts,
            "POLY_API_KEY":    self._creds.api_key,
            "POLY_PASSPHRASE": self._creds.api_passphrase,
        }

    # ── V2 order construction + signing ──────────────────────────────────────

    def _build_and_sign_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: int,
        neg_risk: bool = False,
    ) -> dict:
        """
        Construct and sign a V2 order.
        Returns a dict ready to include in the POST /order body.
        """
        salt       = random.randint(1, 2**32 - 1)
        timestamp  = int(time.time() * 1000)   # milliseconds

        # Polymarket V2 precision rules for BUY orders:
        #   makerAmount (USDC)   — max 5 decimal places → must be divisible by 10
        #   takerAmount (tokens) — max 2 decimal places → must be divisible by 10_000
        # Strategy: snap takerAmount to nearest multiple of 10_000, then derive
        # makerAmount from the exact price ratio so both sit on the 0.001 tick grid.
        TAKER_SNAP = 10_000   # tokens: 2 decimal places
        MAKER_SNAP = 10       # USDC:   5 decimal places
        UNITS      = 10 ** USDC_DECIMALS   # 1_000_000

        # Express price as an exact reduced fraction (max 3 decimal places)
        price_n = round(round(price, 3) * 1000)
        price_d = 1000
        g = math.gcd(price_n, price_d)
        price_n //= g
        price_d //= g

        if side == SIDE_BUY:
            # Snap takerAmount (tokens) to TAKER_SNAP
            k = max(1, round(size * UNITS / TAKER_SNAP))
            taker_amount = k * TAKER_SNAP
            # Derive makerAmount from exact price ratio; price_d | 10_000 always true
            # for 3-decimal prices, so this is always an integer.
            maker_amount = taker_amount * price_n // price_d
            # Ensure makerAmount itself is on the MAKER_SNAP grid
            maker_amount = round(maker_amount / MAKER_SNAP) * MAKER_SNAP
        else:
            # SELL: makerAmount = tokens, takerAmount = USDC
            # Snap makerAmount (tokens) to TAKER_SNAP (same 2-decimal rule)
            k = max(1, round(size * UNITS / TAKER_SNAP))
            maker_amount = k * TAKER_SNAP
            taker_amount = maker_amount * price_n // price_d
            taker_amount = round(taker_amount / MAKER_SNAP) * MAKER_SNAP

        verifying_contract = (
            NEG_RISK_CTF_EXCHANGE_ADDRESS if neg_risk else CTF_EXCHANGE_ADDRESS
        )

        # EIP-712 message (bytes32 fields as raw bytes for eth_account)
        message = {
            "salt":          salt,
            "maker":         self._maker,
            "signer":        self._eoa,
            "tokenId":       int(token_id),
            "makerAmount":   maker_amount,
            "takerAmount":   taker_amount,
            "side":          side,
            "signatureType": self._sig_type,
            "timestamp":     timestamp,
            "metadata":      BYTES32_ZERO,
            "builder":       BYTES32_ZERO,
        }

        structured = {
            "types": {
                "EIP712Domain": [
                    {"name": "name",              "type": "string"},
                    {"name": "version",           "type": "string"},
                    {"name": "chainId",           "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **V2_ORDER_TYPES,
            },
            "domain": {
                "name":              V2_DOMAIN_NAME,
                "version":           V2_DOMAIN_VERSION,
                "chainId":           CHAIN_ID,
                "verifyingContract": verifying_contract,
            },
            "primaryType": "Order",
            "message":     message,
        }

        encoded  = encode_typed_data(full_message=structured)
        signed   = self._account.sign_message(encoded)
        sig_hex  = signed.signature.hex()
        if not sig_hex.startswith("0x"):
            sig_hex = "0x" + sig_hex

        side_str = "BUY" if side == SIDE_BUY else "SELL"
        return {
            "salt":          salt,              # integer — JS does parseInt(order.salt, 10)
            "maker":         self._maker,
            "signer":        self._eoa,
            "tokenId":       token_id,          # string
            "makerAmount":   str(maker_amount), # string
            "takerAmount":   str(taker_amount), # string
            "side":          side_str,          # "BUY" / "SELL"
            "signatureType": self._sig_type,    # integer — JS sends enum value directly
            "timestamp":     str(timestamp),    # string (Date.now().toString() in JS)
            "expiration":    "0",
            "metadata":      "0x" + "00" * 32,
            "builder":       "0x" + "00" * 32,
            "signature":     sig_hex,
        }

    def _post_order(
        self,
        order: dict,
        order_type: str = "GTC",
    ) -> dict:
        body_dict = {
            "deferExec": False,
            "postOnly":  False,
            "order":     order,
            "owner":     self._creds.api_key,  # API key — NOT maker address
            "orderType": order_type,
        }
        body    = json.dumps(body_dict, separators=(",", ":"))
        headers = self._l2_headers("POST", "/order", body)
        resp    = requests.post(
            f"{CLOB_HOST}/order",
            headers=headers,
            data=body,
            timeout=15,
        )
        if not resp.ok:
            raise PolymarketError(
                f"Order rejected ({resp.status_code}): {resp.text}"
            )
        return resp.json()

    # ── Public order methods ──────────────────────────────────────────────────

    def market_buy(self, token_id: str, amount_usdc: float, neg_risk: bool = False) -> dict:
        """
        Market BUY — fetches best ask and places an aggressive limit order.
        amount_usdc is the USDC amount to spend.
        neg_risk must be True for neg-risk markets.
        Enforces Polymarket's minimum of 5 contracts (shares).
        """
        try:
            price = self._get_aggressive_price(token_id, SIDE_BUY)
            size  = amount_usdc / price
            # Polymarket enforces a minimum of 5 contracts per order.
            # If the requested amount buys fewer than 5 shares, bump up to 5.
            MIN_CONTRACTS = 5.0
            if size < MIN_CONTRACTS:
                size = MIN_CONTRACTS
            order = self._build_and_sign_order(token_id, price, size, SIDE_BUY, neg_risk)
            resp  = self._post_order(order, "GTC")
            order_id = (
                resp.get("orderID") or resp.get("orderId") or resp.get("order_id")
            )
            return {
                "status":      "ok" if order_id else "rejected",
                "order_id":    order_id,
                "side":        "BUY",
                "token_id":    token_id,
                "amount_usdc": amount_usdc,
                "price":       price,
                "raw":         resp,
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def market_sell(self, token_id: str, amount_shares: float, neg_risk: bool = False) -> dict:
        """
        Market SELL — fetches best bid and places an aggressive limit order.
        amount_shares is the number of outcome token shares to sell.
        """
        try:
            price = self._get_aggressive_price(token_id, SIDE_SELL)
            order = self._build_and_sign_order(token_id, price, amount_shares, SIDE_SELL, neg_risk)
            resp  = self._post_order(order, "GTC")
            order_id = (
                resp.get("orderID") or resp.get("orderId") or resp.get("order_id")
            )
            return {
                "status":        "ok" if order_id else "rejected",
                "order_id":      order_id,
                "side":          "SELL",
                "token_id":      token_id,
                "amount_shares": amount_shares,
                "price":         price,
                "raw":           resp,
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def limit_buy(
        self, token_id: str, price: float, size: float, neg_risk: bool = False
    ) -> dict:
        """GTC limit BUY. price in [0.01, 0.99], size in shares."""
        try:
            order    = self._build_and_sign_order(token_id, price, size, SIDE_BUY, neg_risk)
            resp     = self._post_order(order, "GTC")
            order_id = resp.get("orderID") or resp.get("orderId") or resp.get("order_id")
            return {
                "status": "ok" if order_id else "rejected",
                "order_id": order_id, "side": "BUY",
                "token_id": token_id, "price": price, "size": size, "raw": resp,
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def limit_sell(
        self, token_id: str, price: float, size: float, neg_risk: bool = False
    ) -> dict:
        """GTC limit SELL. price in [0.01, 0.99], size in shares."""
        try:
            order    = self._build_and_sign_order(token_id, price, size, SIDE_SELL, neg_risk)
            resp     = self._post_order(order, "GTC")
            order_id = resp.get("orderID") or resp.get("orderId") or resp.get("order_id")
            return {
                "status": "ok" if order_id else "rejected",
                "order_id": order_id, "side": "SELL",
                "token_id": token_id, "price": price, "size": size, "raw": resp,
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open limit order by ID."""
        try:
            body_dict = {"orderID": order_id}
            body      = json.dumps(body_dict, separators=(",", ":"))
            headers   = self._l2_headers("DELETE", "/order", body)
            resp      = requests.delete(
                f"{CLOB_HOST}/order", headers=headers, data=body, timeout=10
            )
            return {"cancelled": resp.ok, "raw": resp.json() if resp.ok else resp.text}
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def get_open_orders(self) -> list[dict]:
        """Returns open limit orders from the CLOB."""
        try:
            headers = self._l2_headers("GET", "/orders")
            resp    = requests.get(f"{CLOB_HOST}/orders", headers=headers, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            return raw if isinstance(raw, list) else raw.get("data", [])
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    # ── Account ───────────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """pUSD cash + open position values."""
        try:
            addr = self._proxy or self._eoa
            cash = self._pusd_balance(addr)
            pos_resp = requests.get(
                f"{DATA_API}/positions", params={"user": addr}, timeout=10
            )
            pos_resp.raise_for_status()
            positions_value = sum(
                float(p.get("currentValue", 0)) for p in pos_resp.json()
            )
            return {
                "address":         addr,
                "cash_usdc":       round(cash, 2),
                "positions_value": round(positions_value, 2),
                "total_value":     round(cash + positions_value, 2),
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def wallet_status(self, funded_threshold: float = 5.0) -> dict:
        """Structured wallet status for agents and setup checks."""
        try:
            addr  = self._proxy or self._eoa
            cash  = round(self._pusd_balance(addr), 2)
            is_funded = cash >= funded_threshold
            return {
                "address":        addr,
                "usdc_balance":   cash,
                "is_funded":      is_funded,
                "ready_to_trade": is_funded,
                "deposit_address": addr,
                "deposit_url":    "https://polymarket.com/profile",
                "network":        "polygon",
            }
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    def get_positions(self) -> list[dict]:
        """Open positions from Polymarket's data API."""
        try:
            addr = self._proxy or self._eoa
            resp = requests.get(
                f"{DATA_API}/positions", params={"user": addr}, timeout=10
            )
            resp.raise_for_status()
            return [
                {
                    "title":         p.get("title", ""),
                    "outcome":       p.get("outcome", "?"),
                    "size":          float(p.get("size", 0)),
                    "avg_price":     float(p.get("avgPrice", 0)),
                    "current_price": float(p.get("curPrice", 0)),
                    "current_value": float(p.get("currentValue", 0)),
                    "cash_pnl":      float(p.get("cashPnl", 0)),
                    "percent_pnl":   float(p.get("percentPnl", 0)),
                    "realized_pnl":  float(p.get("realizedPnl", 0)),
                    "end_date":      p.get("endDate", ""),
                    "asset":         p.get("asset", ""),
                    "redeemable":    p.get("redeemable", False),
                }
                for p in resp.json()
            ]
        except Exception as exc:
            raise PolymarketError(str(exc)) from exc

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pusd_balance(self, address: str) -> float:
        rpc_payload = {
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [
                {"to": PUSD_CONTRACT, "data": _balance_of_calldata(address)},
                "latest",
            ],
        }
        rpc_resp = requests.post(POLYGON_RPC, json=rpc_payload, timeout=10)
        rpc_resp.raise_for_status()
        hex_balance = rpc_resp.json().get("result", "0x0")
        return int(hex_balance, 16) / 10 ** USDC_DECIMALS

    def _get_aggressive_price(self, token_id: str, side: int) -> float:
        """
        Fetch current best price and add a small buffer to ensure fill.
        BUY  → 5 % above ask,  capped at 0.99
        SELL → 5 % below bid,  floored at 0.01
        Falls back to 0.99 / 0.01 if the orderbook is unavailable.
        """
        clob_side = "buy" if side == SIDE_BUY else "sell"
        try:
            resp = requests.get(
                f"{CLOB_HOST}/price",
                params={"token_id": token_id, "side": clob_side},
                timeout=10,
            )
            if resp.ok:
                market_price = float(resp.json().get("price", 0))
                if 0 < market_price < 1:
                    if side == SIDE_BUY:
                        return min(0.99, round(market_price * 1.05, 4))
                    else:
                        return max(0.01, round(market_price * 0.95, 4))
        except Exception:
            pass
        return 0.99 if side == SIDE_BUY else 0.01


# ── Errors ────────────────────────────────────────────────────────────────────

class PolymarketError(Exception):
    pass
