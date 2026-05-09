"""
Veynor — prediction market intelligence for agents and traders.

    pip install veynor

    import veynor
    client = veynor.Client(api_key="vey_sk_...")
    whales = client.whales(venue="all", min_notional=10_000)
"""

from .client import Client, VeynorError, AuthError, RateLimitError

__all__ = ["Client", "VeynorError", "AuthError", "RateLimitError"]
__version__ = "1.2.0"
