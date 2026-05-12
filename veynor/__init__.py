"""
Veynor — prediction market intelligence for agents and traders.

    pip install veynor

    import veynor
    client = veynor.Client(api_key="vey_sk_...")
    whales = client.whales(venue="all", min_notional=10_000)
"""

from .client import Client, VeynorError, AuthError, RateLimitError
from .kalshi_trader import KalshiTrader, KalshiError
from .polymarket_trader import PolymarketTrader, PolymarketError

__all__ = [
    "Client", "VeynorError", "AuthError", "RateLimitError",
    "KalshiTrader", "KalshiError",
    "PolymarketTrader", "PolymarketError",
]
__version__ = "1.4.0"
