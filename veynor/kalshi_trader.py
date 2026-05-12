"""
Kalshi order execution via the Kalshi REST API v2.

Auth model: RSA key pair — non-custodial.
Your private key never leaves your machine (or your server's .env).

Setup:
  1. Generate a key pair:
       openssl genrsa -out kalshi_key.pem 2048
       openssl rsa -in kalshi_key.pem -pubout -out kalshi_key_pub.pem
  2. Register the public key at https://kalshi.com/profile/api-keys
     Copy the resulting Key ID (a UUID).
  3. Set env vars:
       export KALSHI_API_KEY_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
       export KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi_key.pem
     OR pass the PEM text directly:
       export KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n..."

Requires: pip install veynor[trade]   (adds 'cryptography' to deps)
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from typing import Optional

import requests

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
except ImportError:
    hashes = serialization = asym_padding = None  # type: ignore

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _load_private_key():
    """Load RSA private key from env (path or raw PEM)."""
    if hashes is None:
        raise KalshiError(
            "cryptography package not installed. Run: pip install veynor[trade]"
        )

    pem_text = os.environ.get("KALSHI_PRIVATE_KEY", "")
    if pem_text:
        pem_bytes = pem_text.replace("\\n", "\n").encode()
    else:
        path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
        if not path:
            raise KalshiError(
                "No Kalshi private key found.\n"
                "Set KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem  or\n"
                "    KALSHI_PRIVATE_KEY='-----BEGIN RSA PRIVATE KEY-----\\n...'"
            )
        with open(path, "rb") as f:
            pem_bytes = f.read()

    return serialization.load_pem_private_key(pem_bytes, password=None)


def _rsa_sign(private_key, message: str) -> str:
    """RSA-SHA256 sign message, return base64-encoded signature."""
    sig = private_key.sign(message.encode(), asym_padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _auth_headers(key_id: str, private_key, method: str, path: str) -> dict:
    """Build Kalshi HMAC auth headers. Note: path must start with /trade-api/v2/..."""
    ts_ms = str(int(time.time() * 1000))
    message = ts_ms + method.upper() + path
    sig = _rsa_sign(private_key, message)
    return {
        "KALSHI-ACCESS-KEY":       key_id,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "Content-Type":            "application/json",
    }


# ── Trader ────────────────────────────────────────────────────────────────────

class KalshiTrader:
    """
    Kalshi order execution — limit and market orders on both YES and NO sides.

    Usage:
        trader = KalshiTrader()
        print(trader.get_balance())
        trader.market_buy("KXNBA-25JUL05-T204", side="YES", amount_usd=50.0)
        trader.limit_buy("KXNBA-25JUL05-T204", side="YES", price=0.62, count=100)
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        private_key_path: Optional[str] = None,
    ) -> None:
        self._key_id = (
            key_id
            or os.environ.get("KALSHI_API_KEY_ID", "")
            or os.environ.get("KALSHI_KEY_ID", "")
        )
        if not self._key_id:
            print(
                "No Kalshi API key ID found. Set KALSHI_API_KEY_ID=<uuid>",
                file=sys.stderr,
            )
            sys.exit(1)

        # Allow inline override for programmatic use
        if private_key_pem:
            os.environ["KALSHI_PRIVATE_KEY"] = private_key_pem
        elif private_key_path:
            os.environ["KALSHI_PRIVATE_KEY_PATH"] = private_key_path

        self._private_key = _load_private_key()
        self._sess = requests.Session()

    # ── Low-level request ─────────────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, body: Optional[dict] = None) -> dict:
        """Make an authenticated Kalshi API request."""
        path = f"/trade-api/v2{endpoint}"
        hdrs = _auth_headers(self._key_id, self._private_key, method, path)

        url  = f"{KALSHI_BASE}{endpoint}"
        resp = self._sess.request(
            method,
            url,
            headers=hdrs,
            json=body if body else None,
            timeout=15,
        )
        if not resp.ok:
            raise KalshiError(
                f"Kalshi API error ({resp.status_code}): {resp.text[:400]}"
            )
        return resp.json() if resp.text else {}

    # ── Market helpers ────────────────────────────────────────────────────────

    def get_market(self, ticker: str) -> dict:
        """Fetch market details for a given ticker."""
        return self._request("GET", f"/markets/{ticker}")

    def _best_price(self, ticker: str, side: str) -> float:
        """
        Return best available price for a buy/sell on YES or NO.
        Fetches the orderbook and picks the best ask (buy) or best bid (sell).
        Falls back to mid from the market snapshot.
        """
        try:
            book = self._request("GET", f"/markets/{ticker}/orderbook")
            ob   = book.get("orderbook", book)
            if side.upper() == "YES":
                asks = ob.get("yes", {}).get("asks") or ob.get("asks", [])
                bids = ob.get("yes", {}).get("bids") or ob.get("bids", [])
            else:
                # For NO side, Kalshi's orderbook gives NO prices directly
                asks = ob.get("no", {}).get("asks") or []
                bids = ob.get("no", {}).get("bids") or []

            # asks sorted ascending, bids sorted descending
            asks_sorted = sorted(asks, key=lambda x: float(x[0] if isinstance(x, list) else x.get("price", 99)))
            bids_sorted = sorted(bids, key=lambda x: float(x[0] if isinstance(x, list) else x.get("price", 0)), reverse=True)

            if asks_sorted:
                best_ask = float(asks_sorted[0][0] if isinstance(asks_sorted[0], list) else asks_sorted[0].get("price", 99))
                return min(99, int(best_ask * 1.05)) if best_ask <= 1 else min(99, int(best_ask) + 2)
            if bids_sorted:
                best_bid = float(bids_sorted[0][0] if isinstance(bids_sorted[0], list) else bids_sorted[0].get("price", 1))
                return max(1, int(best_bid * 0.95)) if best_bid <= 1 else max(1, int(best_bid) - 2)
        except Exception:
            pass

        # Fallback: use market mid price
        try:
            mkt = self.get_market(ticker)
            m   = mkt.get("market", mkt)
            if side.upper() == "YES":
                p = (float(m.get("yes_bid_dollars", 0.5)) + float(m.get("yes_ask_dollars", 0.5))) / 2
            else:
                p = 1 - (float(m.get("yes_bid_dollars", 0.5)) + float(m.get("yes_ask_dollars", 0.5))) / 2
            # Convert 0-1 range to cents if needed
            if p <= 1:
                p_cents = round(p * 100)
            else:
                p_cents = round(p)
            return max(1, min(99, p_cents))
        except Exception:
            pass

        return 60 if side.upper() == "YES" else 60   # last resort

    # ── Order submission ──────────────────────────────────────────────────────

    def _place_order(
        self,
        ticker: str,
        action: str,       # "buy" | "sell"
        count: int,
        yes_price: Optional[int],   # cents (1-99), None for market orders
        order_type: str = "limit",
        client_order_id: Optional[str] = None,
        buy_max_cost: Optional[int] = None,
    ) -> dict:
        body: dict = {
            "action":          action,
            "type":            order_type,
            "ticker":          ticker,
            "count":           count,
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        if yes_price is not None:
            body["yes_price"] = yes_price
        if buy_max_cost is not None:
            body["buy_max_cost"] = buy_max_cost   # for market buys: max USDC to spend (cents)

        resp = self._request("POST", "/portfolio/orders", body)
        order = resp.get("order", resp)
        return {
            "status":    order.get("status", "unknown"),
            "order_id":  order.get("order_id", ""),
            "ticker":    ticker,
            "action":    action,
            "side":      "YES" if yes_price is not None and yes_price >= 50 else "NO",
            "count":     count,
            "yes_price": yes_price,
            "raw":       resp,
        }

    # ── Public order methods ──────────────────────────────────────────────────

    def market_buy(self, ticker: str, *, side: str = "YES", amount_usd: float) -> dict:
        """
        Market BUY — fetches best ask and places an aggressive limit order.

        Parameters
        ----------
        ticker     Kalshi market ticker (e.g. KXNBA-25JUL05-T204)
        side       "YES" or "NO" (default "YES")
        amount_usd USDC amount to spend
        """
        try:
            price_cents = self._best_price(ticker, side)
            # count = whole contracts; each contract = 1 USD at settlement
            count = max(1, int(amount_usd / (price_cents / 100)))
            if side.upper() == "NO":
                # For NO: Kalshi uses yes_price field; NO price = 100 - yes_price
                yes_p = max(1, min(99, 100 - price_cents))
            else:
                yes_p = max(1, min(99, price_cents))
            return self._place_order(ticker, "buy", count, yes_p)
        except KalshiError:
            raise
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def market_sell(self, ticker: str, *, side: str = "YES", count: int) -> dict:
        """
        Market SELL — fetches best bid and places an aggressive limit order.

        Parameters
        ----------
        ticker  Kalshi market ticker
        side    "YES" or "NO"
        count   Number of contracts to sell
        """
        try:
            price_cents = self._best_price(ticker, side)
            if side.upper() == "NO":
                yes_p = max(1, min(99, 100 - price_cents))
            else:
                yes_p = max(1, min(99, price_cents))
            return self._place_order(ticker, "sell", count, yes_p)
        except KalshiError:
            raise
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def limit_buy(
        self, ticker: str, *, side: str = "YES", price: float, count: int
    ) -> dict:
        """
        GTC limit BUY.

        Parameters
        ----------
        ticker  Kalshi market ticker
        side    "YES" or "NO"
        price   Probability in [0.01, 0.99]  (e.g. 0.65 for 65¢)
        count   Number of contracts
        """
        try:
            if side.upper() == "NO":
                yes_p = max(1, min(99, round((1 - price) * 100)))
            else:
                yes_p = max(1, min(99, round(price * 100)))
            return self._place_order(ticker, "buy", count, yes_p)
        except KalshiError:
            raise
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def limit_sell(
        self, ticker: str, *, side: str = "YES", price: float, count: int
    ) -> dict:
        """
        GTC limit SELL.

        Parameters
        ----------
        ticker  Kalshi market ticker
        side    "YES" or "NO"
        price   Probability in [0.01, 0.99]
        count   Number of contracts to sell
        """
        try:
            if side.upper() == "NO":
                yes_p = max(1, min(99, round((1 - price) * 100)))
            else:
                yes_p = max(1, min(99, round(price * 100)))
            return self._place_order(ticker, "sell", count, yes_p)
        except KalshiError:
            raise
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order by ID."""
        try:
            resp = self._request("DELETE", f"/portfolio/orders/{order_id}")
            return {"cancelled": True, "raw": resp}
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def get_order(self, order_id: str) -> dict:
        """Fetch a single order by ID."""
        return self._request("GET", f"/portfolio/orders/{order_id}")

    def get_open_orders(self, ticker: Optional[str] = None) -> list[dict]:
        """List open orders, optionally filtered to a single ticker."""
        params = "?status=resting"
        if ticker:
            params += f"&ticker={ticker}"
        resp = self._request("GET", f"/portfolio/orders{params}")
        return resp.get("orders", [])

    # ── Account ───────────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """Portfolio cash balance."""
        try:
            resp = self._request("GET", "/portfolio/balance")
            bal  = resp.get("balance", resp)
            return {
                "cash_cents":        bal.get("balance", 0),
                "cash_usd":          round(bal.get("balance", 0) / 100, 2),
                "payout_cents":      bal.get("payout", 0),
                "fees_paid_cents":   bal.get("fees", 0),
            }
        except Exception as exc:
            raise KalshiError(str(exc)) from exc

    def get_positions(self, ticker: Optional[str] = None) -> list[dict]:
        """Open positions. Optionally filter to a single ticker."""
        params = ""
        if ticker:
            params = f"?ticker={ticker}"
        resp = self._request("GET", f"/portfolio/positions{params}")
        raw  = resp.get("market_positions", resp.get("positions", []))
        out  = []
        for p in raw:
            out.append({
                "ticker":            p.get("market_id", p.get("ticker", "")),
                "yes_count":         p.get("position", p.get("yes_count", 0)),
                "no_count":          p.get("no_count", 0),
                "total_traded":      p.get("total_traded", 0),
                "fees_paid":         p.get("fees_paid", 0),
                "realized_pnl":      p.get("realized_pnl", 0),
                "resting_order_count": p.get("resting_orders_count", 0),
            })
        return out


# ── Errors ────────────────────────────────────────────────────────────────────

class KalshiError(Exception):
    pass
