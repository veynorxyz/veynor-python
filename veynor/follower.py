"""
veynor follow — whale-following daemon for Polymarket and Kalshi.

Polls the Veynor whale feed on an interval, detects new large trades,
and mirrors them on your connected exchange accounts.

Architecture:
  1. Poll /v1/whale-trades every --interval seconds
  2. Fingerprint each trade — skip if already seen
  3. Filter by min_notional, category, side
  4. Polymarket: look up the market to get token_id + neg_risk flag (avoids
     the "invalid signature" bug — neg_risk markets need a different exchange
     contract address for EIP-712 signing)
  5. Kalshi: extract ticker from market URL, map side (auto-detected via env)
  6. Execute market_buy via the appropriate trader
  7. Enforce daily spend cap — hard stop if exceeded

Deduplication key: (platform, market_name, side, notional)
Persisted to ~/.veynor_seen_trades.json so restarts don't re-fire.

Kalshi setup:
  export KALSHI_API_KEY_ID=<uuid>
  export KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem
  OR export KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n..."

Usage:
    veynor follow --amount 2 --min-notional 15000
    veynor follow --amount 5 --category Politics --dry-run
    veynor follow --pct 2 --max-daily 50
    veynor follow --venues polymarket kalshi --amount 3
"""

from __future__ import annotations

import json
import os
import sys
import time
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── Seen-trade store ──────────────────────────────────────────────────────────

SEEN_PATH = Path.home() / ".veynor_seen_trades.json"


def _load_seen() -> set[str]:
    try:
        data = json.loads(SEEN_PATH.read_text())
        return set(data.get("fingerprints", []))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    try:
        # Keep only the last 5000 fingerprints to avoid unbounded growth
        trimmed = list(seen)[-5000:]
        SEEN_PATH.write_text(json.dumps({"fingerprints": trimmed}))
    except Exception:
        pass


def _fingerprint(trade: dict) -> str:
    # Stable fields: platform + market + side + notional (rounded to dollar).
    # Timestamp changes each scanner cycle (re-fetch updates it).
    # Price can shift slightly. Notional is the actual trade size — stable.
    # Two different trades on the same market will have different notionals.
    key = "|".join([
        str(trade.get("platform", "")),
        str(trade.get("market", "")),
        str(trade.get("side", "")),
        str(round(float(trade.get("notional", 0)))),
    ])
    return hashlib.md5(key.encode()).hexdigest()


# ── Daily spend tracker ───────────────────────────────────────────────────────

class DailySpend:
    """
    Simple in-memory daily spend tracker.
    Resets automatically when the calendar date changes.
    """
    def __init__(self, max_daily: float):
        self.max_daily  = max_daily
        self._date      = date.today()
        self._spent     = 0.0

    def _check_rollover(self) -> None:
        if date.today() != self._date:
            self._date  = date.today()
            self._spent = 0.0

    def can_spend(self, amount: float) -> bool:
        self._check_rollover()
        if self.max_daily <= 0:
            return True  # no cap
        return self._spent + amount <= self.max_daily

    def record(self, amount: float) -> None:
        self._check_rollover()
        self._spent += amount

    @property
    def spent(self) -> float:
        self._check_rollover()
        return self._spent

    @property
    def remaining(self) -> float:
        self._check_rollover()
        if self.max_daily <= 0:
            return float("inf")
        return max(0.0, self.max_daily - self._spent)


# ── Market lookup ─────────────────────────────────────────────────────────────

def _lookup_polymarket_token(
    client,
    market_name: str,
    side: str,
) -> tuple[Optional[str], bool]:
    """
    Search for a Polymarket market by name, return (token_id, neg_risk).
    side: "YES" or "NO" — determines which token_id to return.
    Returns (None, False) if not found.
    """
    try:
        results = client.search(market_name, venue="polymarket", limit=5)
        markets = results.get("polymarket", [])
        if not markets:
            return None, False

        best = markets[0]
        condition_id = best.get("condition_id")
        if not condition_id:
            return None, False

        details = client.market("polymarket", condition_id)
        m = details.get("market", {})

        neg_risk = bool(m.get("neg_risk", False))
        token_id = m.get("no_token_id") if side.upper() == "NO" else m.get("yes_token_id")
        return token_id, neg_risk
    except Exception:
        return None, False


def _kalshi_ticker_from_url(url: str) -> Optional[str]:
    """
    Extract Kalshi ticker from a market URL.
    e.g. https://kalshi.com/markets/kxiplgame/.../kxiplgame-26may18srhcsk
         → KXIPLGAME-26MAY18SRHCSK
    """
    try:
        slug = url.rstrip("/").split("/")[-1]
        return slug.upper() if slug else None
    except Exception:
        return None


def _kalshi_side_from_feed(side: str) -> str:
    """
    Map whale feed side to Kalshi YES/NO.
    Feed shows "YES", "NO", "TEAM NAME", "NO TEAM NAME".
    "NO <something>" → NO side.
    Anything else (team name, YES) → YES side.
    """
    s = side.strip().upper()
    if s == "NO" or s.startswith("NO "):
        return "NO"
    return "YES"


# ── Main follower loop ────────────────────────────────────────────────────────

def run_follower(
    client,
    min_notional:  float = 10_000,
    amount:        Optional[float] = None,
    pct:           Optional[float] = None,
    category:      str = "All",
    max_daily:     float = 0.0,
    interval:      int = 30,
    dry_run:       bool = False,
    sides:         str = "YES",   # "YES", "NO", or "ALL"
    venues:        Optional[list] = None,  # ["polymarket", "kalshi"] — default: auto-detect
    verbose:       bool = False,
    echo = print,
) -> None:
    """
    Core follower loop. Call from the CLI command — separated here so it
    can also be imported and run programmatically (e.g. in a script or agent).

    Kalshi is included automatically when KALSHI_API_KEY_ID is set.
    Pass venues=["polymarket"] to disable Kalshi even if credentials exist.
    """
    # Import here so the module doesn't hard-fail if trade deps aren't installed
    try:
        from .polymarket_trader import PolymarketTrader, PolymarketError
    except ImportError:
        echo("pip install veynor[trade] required for whale following.", file=sys.stderr)
        sys.exit(1)

    # ── Init traders ──────────────────────────────────────────────────────────
    poly_trader   = PolymarketTrader()
    kalshi_trader = None

    if venues is None:
        # Auto-detect: include Kalshi if credentials are present
        kalshi_key_id = os.environ.get("KALSHI_API_KEY_ID") or os.environ.get("KALSHI_KEY_ID")
        active_venues = ["polymarket"]
        if kalshi_key_id:
            active_venues.append("kalshi")
    else:
        active_venues = [v.lower() for v in venues]
        kalshi_key_id = os.environ.get("KALSHI_API_KEY_ID") or os.environ.get("KALSHI_KEY_ID")

    if "kalshi" in active_venues:
        try:
            from .kalshi_trader import KalshiTrader, KalshiError
            kalshi_trader = KalshiTrader()
        except Exception as e:
            echo(f"  Warning: could not init Kalshi trader: {e}. Kalshi trades will be skipped.")
            active_venues = [v for v in active_venues if v != "kalshi"]

    daily_spend = DailySpend(max_daily)
    seen        = _load_seen()

    echo(f"\n  Veynor Whale Follower {'(DRY RUN) ' if dry_run else ''}-- starting up")
    echo(f"  Venues:        {', '.join(active_venues)}")
    echo(f"  Min notional:  ${min_notional:,.0f}")
    echo(f"  Sides:         {sides}")
    echo(f"  Category:      {category}")
    echo(f"  Poll interval: {interval}s")
    if max_daily > 0:
        echo(f"  Daily cap:     ${max_daily:.2f}")
    echo()

    def _fetch_trades(limit: int = 60) -> list:
        """Fetch whale trades across all active venues."""
        all_trades = []
        for venue in active_venues:
            try:
                data = client.whales(
                    venue=venue,
                    min_notional=min_notional,
                    limit=limit,
                    category=category if category != "All" else None,
                )
                all_trades.extend(data.get("trades", []))
            except Exception as e:
                if verbose:
                    echo(f"  [{_now()}] Feed error ({venue}): {e}")
        return all_trades

    # Seed seen on first boot — don't act on existing feed
    try:
        seed_trades = _fetch_trades(limit=60)
        for t in seed_trades:
            seen.add(_fingerprint(t))
        _save_seen(seen)
        echo(f"  Seeded {len(seed_trades)} existing trades as seen. Watching for new flow...\n")
    except Exception as e:
        echo(f"  Warning: could not seed seen trades: {e}")

    while True:
        try:
            time.sleep(interval)

            # ── Fetch latest whale feed ───────────────────────────────────────
            trades = _fetch_trades(limit=60)
            if not trades and verbose:
                echo(f"  [{_now()}] Feed returned no trades.")

            # ── Find new trades ───────────────────────────────────────────────
            new_trades = []
            for t in trades:
                fp = _fingerprint(t)
                if fp not in seen:
                    new_trades.append((t, fp))

            if not new_trades:
                if verbose:
                    echo(f"  [{_now()}] No new trades. ({len(trades)} in feed)")
                continue

            echo(f"  [{_now()}] {len(new_trades)} new whale trade(s) detected")

            for trade, fp in new_trades:
                seen.add(fp)

                platform = str(trade.get("platform", trade.get("venue", "polymarket"))).lower()
                market   = str(trade.get("market", ""))
                side     = str(trade.get("side", "YES")).upper()
                notional = float(trade.get("notional", 0))
                price    = float(trade.get("price", 0))

                # Skip venues we're not following
                if platform not in active_venues:
                    continue

                # Normalise side for Kalshi — feed may use team names
                if platform == "kalshi":
                    side = _kalshi_side_from_feed(side)

                if sides != "ALL" and side != sides.upper():
                    echo(f"  [{_now()}] Skip {side} trade on '{market[:40]}' ({platform}, side filter)")
                    continue

                echo(f"  [{_now()}] New whale ({platform}): {side} ${notional:,.0f} on '{market[:50]}' @ {round(price*100)}c")

                # ── Resolve size ──────────────────────────────────────────────
                try:
                    if pct is not None:
                        if platform == "kalshi" and kalshi_trader:
                            bal  = kalshi_trader.get_balance()
                            cash = bal.get("cash_usd", 0)
                        else:
                            bal  = poly_trader.get_balance()
                            cash = bal.get("cash_usdc", 0)
                        trade_amount = round(cash * pct / 100, 2)
                    else:
                        trade_amount = amount or 2.0
                except Exception as e:
                    echo(f"  [{_now()}] Could not fetch balance: {e} -- using fixed $2")
                    trade_amount = 2.0

                # ── Daily cap check ───────────────────────────────────────────
                if not daily_spend.can_spend(trade_amount):
                    echo(f"  [{_now()}] Daily cap reached (${daily_spend.spent:.2f} / ${daily_spend.max_daily:.2f}). Skipping.")
                    continue

                # ── Execute: Kalshi path ──────────────────────────────────────
                if platform == "kalshi":
                    market_url = str(trade.get("url", ""))
                    ticker = _kalshi_ticker_from_url(market_url) if market_url else None

                    if not ticker:
                        # Fall back: try the market field itself if it looks like a ticker
                        candidate = market.strip().upper().replace(" ", "-")
                        if len(candidate) < 40 and "-" in candidate:
                            ticker = candidate
                        else:
                            echo(f"  [{_now()}] Could not resolve Kalshi ticker for '{market[:40]}'. Skipping.")
                            continue

                    echo(f"  [{_now()}] Kalshi ticker: {ticker}")

                    if dry_run:
                        echo(f"  [{_now()}] DRY RUN -- would buy ${trade_amount:.2f} of {side} on {ticker}")
                        daily_spend.record(trade_amount)
                        continue

                    try:
                        from .kalshi_trader import KalshiError
                        result   = kalshi_trader.market_buy(ticker, side=side, amount_usd=trade_amount)
                        status   = result.get("status", "?")
                        order_id = result.get("order_id", "")
                        daily_spend.record(trade_amount)
                        echo(f"  [{_now()}] Kalshi order {status} -- ID: {order_id} | ${trade_amount:.2f} {side} on {ticker}")
                        if daily_spend.max_daily > 0:
                            echo(f"  [{_now()}] Daily spend: ${daily_spend.spent:.2f} / ${daily_spend.max_daily:.2f} (${daily_spend.remaining:.2f} left)")
                    except Exception as e:
                        echo(f"  [{_now()}] Kalshi order failed: {e}")
                    continue

                # ── Execute: Polymarket path ──────────────────────────────────
                echo(f"  [{_now()}] Looking up Polymarket market...")
                token_id, neg_risk = _lookup_polymarket_token(client, market, side)

                if not token_id:
                    echo(f"  [{_now()}] Could not resolve token_id for '{market[:40]}'. Skipping.")
                    continue

                echo(f"  [{_now()}] token_id: {token_id[:20]}... neg_risk: {neg_risk}")

                if dry_run:
                    echo(f"  [{_now()}] DRY RUN -- would buy ${trade_amount:.2f} of {side} @ ~{round(price*100)}c")
                    daily_spend.record(trade_amount)
                    continue

                try:
                    result   = poly_trader.market_buy(token_id, trade_amount, neg_risk=neg_risk)
                    status   = result.get("status", "?")
                    order_id = result.get("order_id", "")
                    daily_spend.record(trade_amount)
                    echo(f"  [{_now()}] Poly order {status} -- ID: {order_id} | ${trade_amount:.2f} {side}")
                    if daily_spend.max_daily > 0:
                        echo(f"  [{_now()}] Daily spend: ${daily_spend.spent:.2f} / ${daily_spend.max_daily:.2f} (${daily_spend.remaining:.2f} left)")
                except Exception as e:
                    echo(f"  [{_now()}] Poly order failed: {e}")

            _save_seen(seen)

        except KeyboardInterrupt:
            echo(f"\n  Follower stopped. Daily spend: ${daily_spend.spent:.2f}")
            _save_seen(seen)
            break
        except Exception as e:
            echo(f"  [{_now()}] Unexpected error: {e}")
            time.sleep(5)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
