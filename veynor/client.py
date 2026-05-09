"""
Veynor Python Client — prediction market intelligence for agents and traders.

    pip install veynor

Usage:
    import veynor
    client = veynor.Client(api_key="vey_sk_...")

    whales  = client.whales(venue="all", min_notional=10_000)
    markets = client.top_markets(limit=10)
    arb     = client.signals(signal_type="arb_opportunities")
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests
from requests import Response

__all__ = ["Client", "VeynorError", "AuthError", "RateLimitError"]

_DEFAULT_BASE_URL = "https://api.veynor.xyz"


# ── Exceptions ─────────────────────────────────────────────────────────────────

class VeynorError(Exception):
    """Base exception for all Veynor errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(VeynorError):
    """Raised when the API key is missing, invalid, or over quota."""


class RateLimitError(VeynorError):
    """Raised when the per-minute request rate limit is exceeded."""


# ── Client ─────────────────────────────────────────────────────────────────────

class Client:
    """
    Veynor REST API client.

    Parameters
    ----------
    api_key : str, optional
        Your Veynor API key (``vey_sk_...``).
        Falls back to the ``VEYNOR_API_KEY`` environment variable.
    base_url : str, optional
        Override the API base URL. Defaults to ``https://api.veynor.xyz``.
    timeout : int, optional
        Request timeout in seconds. Default: 20.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = 20,
    ) -> None:
        key = api_key or os.environ.get("VEYNOR_API_KEY")
        if not key:
            raise AuthError(
                "No API key provided. Pass api_key= or set the VEYNOR_API_KEY "
                "environment variable. Register at https://veynor.xyz/agents"
            )
        self._base_url = base_url.rstrip("/")
        self._timeout  = timeout
        self._session  = requests.Session()
        self._session.headers.update({
            "X-API-Key": key,
            "Accept":    "application/json",
            "User-Agent": "veynor-python/1.0.0",
        })

    # ── Internal ───────────────────────────────────────────────────────────────

    def _get(self, path: str, **params: Any) -> Any:
        """Make a GET request; raise typed exceptions on error."""
        # Drop None values so optional params don't pollute the query string
        clean = {k: v for k, v in params.items() if v is not None}
        url   = f"{self._base_url}{path}"
        resp: Response = self._session.get(url, params=clean, timeout=self._timeout)
        return self._handle(resp)

    @staticmethod
    def _handle(resp: Response) -> Any:
        if resp.status_code == 200:
            return resp.json()
        try:
            body = resp.json()
            msg  = body.get("error", resp.text)
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"

        if resp.status_code in (401, 403):
            raise AuthError(msg, resp.status_code)
        if resp.status_code == 429:
            raise RateLimitError(msg, resp.status_code)
        raise VeynorError(msg, resp.status_code)

    # ── Public API ─────────────────────────────────────────────────────────────

    def whales(
        self,
        *,
        venue: str = "all",
        min_notional: float = 8_000,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """
        Recent large trades across Kalshi and Polymarket.

        Parameters
        ----------
        venue : "all" | "kalshi" | "polymarket"
        min_notional : float
            Minimum trade size in USD (default 8000).
        category : "All" | "Sports" | "Politics" | "Other", optional
        limit : int
            Max trades to return (1–60, default 20).

        Returns
        -------
        dict with keys: summary, trades (list), meta
        """
        return self._get(
            "/v1/whale-trades",
            platform=venue,
            min_notional=min_notional,
            category=category,
            limit=limit,
        )

    def top_markets(
        self,
        *,
        venue: str = "all",
        category: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        """
        Top prediction markets by 24-hour volume.

        Parameters
        ----------
        venue : "all" | "kalshi" | "polymarket"
        category : "All" | "Sports" | "Politics" | "Other", optional
        limit : int
            Max markets per platform (1–20, default 10).

        Returns
        -------
        dict with keys: summary, kalshi (list), polymarket (list), meta
        """
        return self._get(
            "/v1/markets/top",
            platform=venue,
            category=category,
            limit=limit,
        )

    def search(
        self,
        query: str,
        *,
        venue: str = "all",
        limit: int = 10,
    ) -> dict:
        """
        Search prediction markets by keyword across both venues.

        Parameters
        ----------
        query : str
            E.g. "fed rate", "NBA finals", "Iran"
        venue : "all" | "kalshi" | "polymarket"
        limit : int

        Returns
        -------
        dict with keys: summary, polymarket (list), kalshi (list), meta
        """
        return self._get("/v1/markets/search", q=query, platform=venue, limit=limit)

    def market(self, venue: str, market_id: str) -> dict:
        """
        Full details for a specific market.

        Parameters
        ----------
        venue : "polymarket" | "kalshi"
        market_id : str
            Polymarket condition ID (0x...) or Kalshi ticker (e.g. KXNBA-...).

        Returns
        -------
        dict with keys: summary, market (full object), meta
        """
        return self._get(f"/v1/markets/{venue}/{market_id}")

    def signals(
        self,
        *,
        signal_type: str = "all",
        limit: int = 10,
    ) -> dict:
        """
        Alpha-generating signals: wide spreads, price movers, arb opportunities.

        Parameters
        ----------
        signal_type : "all" | "wide_spreads" | "price_movers" | "arb_opportunities"
        limit : int
            Max results per signal type (1–20, default 10).

        Returns
        -------
        dict with keys: summary, wide_spreads, price_movers, arb_opportunities, meta
        """
        return self._get("/v1/signals", signal_type=signal_type, limit=limit)

    def positions(
        self,
        wallet: str,
        *,
        size_threshold: float = 0.1,
    ) -> list:
        """
        Open positions for a Polymarket wallet address.

        Calls the Polymarket Data API directly — no private key required.
        For placing or managing orders, use the ``veynor[trade]`` extras instead.

        Parameters
        ----------
        wallet : str
            Polymarket proxy wallet address (``0x...``).
        size_threshold : float
            Minimum position size to include (default 0.1 shares).

        Returns
        -------
        list of position dicts, each with: title, outcome, size, avgPrice,
        curPrice, currentValue, cashPnl, percentPnl, realizedPnl, endDate.

        Example
        -------
        >>> client = veynor.Client(api_key="vey_sk_...")
        >>> for p in client.positions("0xabc..."):
        ...     print(p["title"], p["cashPnl"])
        """
        url  = "https://data-api.polymarket.com/positions"
        resp = self._session.get(
            url,
            params={"user": wallet, "sizeThreshold": size_threshold},
            timeout=self._timeout,
        )
        return self._handle(resp)

    def usage(self) -> dict:
        """
        Current credit usage, tier, and quota. Always free.

        Returns
        -------
        dict with keys: summary, tier, credits_used, credits_remaining, total_calls, tool_costs
        """
        return self._get("/v1/usage")
