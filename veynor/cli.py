"""
Veynor CLI — prediction market intelligence from your terminal.

    pip install veynor
    export VEYNOR_API_KEY=vey_sk_...

    veynor whales
    veynor scan movers
    veynor scan arb
    veynor signals --type wide-spreads --limit 5 --json
    veynor search "fed rate"
    veynor usage

Polymarket order execution (requires: pip install veynor[trade]):

    export POLYMARKET_PRIVATE_KEY=0x...

    veynor trade balance
    veynor trade positions
    veynor trade buy  <token_id> --amount 50
    veynor trade sell <token_id> --shares 100
    veynor trade copy               # mirror latest whale trade
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import click

from .client import Client, VeynorError, AuthError, RateLimitError
from .polymarket_trader import PolymarketTrader, PolymarketError

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_client() -> Client:
    key = os.environ.get("VEYNOR_API_KEY")
    if not key:
        click.echo(
            "No API key found. Set VEYNOR_API_KEY or pass --api-key.\n"
            "Register at https://veynor.xyz/agents",
            err=True,
        )
        sys.exit(1)
    return Client(api_key=key)


def out(data: object, as_json: bool) -> None:
    """Print structured or human-readable output."""
    if as_json:
        click.echo(json.dumps(data, indent=2))
    else:
        click.echo(data)


def handle_error(e: VeynorError) -> None:
    if isinstance(e, AuthError):
        click.echo(f"Auth error: {e}", err=True)
    elif isinstance(e, RateLimitError):
        click.echo("Rate limit hit. Slow down or upgrade your tier.", err=True)
    else:
        click.echo(f"API error {e.status_code}: {e}", err=True)
    sys.exit(1)


def fmt_trade(t: dict) -> str:
    side   = t.get("side", "?").upper()
    notl   = t.get("notional", 0)
    plat   = t.get("platform", "?")
    market = t.get("market", t.get("market_slug", "?"))
    price  = t.get("price")
    price_str = f" @ {price:.2f}" if price is not None else ""
    return f"  [{plat}] {side}{price_str}  ${notl:>10,.0f}  {market}"


def fmt_market(m: dict, platform: str = "") -> str:
    plat   = platform or m.get("platform", "")
    title  = m.get("title", m.get("question", m.get("slug", "?")))
    vol    = m.get("volume_24h", m.get("volume", 0)) or 0
    price  = m.get("last_price", m.get("price"))
    price_str = f"  {price:.2f}" if price is not None else ""
    return f"  [{plat}]{price_str}  ${vol:>10,.0f}/24h  {title}"


def fmt_signal(s: dict, kind: str) -> str:
    title = s.get("title", s.get("question", s.get("market", "?")))
    if kind == "price_movers":
        move = s.get("price_change", s.get("move"))
        move_str = f"  Δ{move:.2f}" if move is not None else ""
        return f"{move_str}  {title}"
    elif kind == "arb_opportunities":
        spread = s.get("spread", s.get("edge"))
        spread_str = f"  edge {spread:.2f}" if spread is not None else ""
        return f"{spread_str}  {title}"
    elif kind == "wide_spreads":
        spread = s.get("spread", s.get("bid_ask_spread"))
        spread_str = f"  spread {spread:.2f}" if spread is not None else ""
        return f"{spread_str}  {title}"
    return f"  {title}"


# ── Root command ───────────────────────────────────────────────────────────────

@click.group()
@click.version_option(package_name="veynor")
def cli() -> None:
    """Veynor — prediction market intelligence for traders and agents."""


# ── veynor whales ──────────────────────────────────────────────────────────────

@cli.command()
@click.option("--venue",         default="all", show_default=True,
              type=click.Choice(["all", "kalshi", "polymarket"]),
              help="Exchange filter.")
@click.option("--min-notional",  default=8_000, show_default=True, type=float,
              help="Minimum trade size in USD.")
@click.option("--category",      default=None,
              type=click.Choice(["All", "Sports", "Politics", "Other"]),
              help="Market category filter.")
@click.option("--limit",         default=20, show_default=True, type=int,
              help="Max trades to return (1-60).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def whales(venue: str, min_notional: float, category: Optional[str],
           limit: int, as_json: bool) -> None:
    """Recent large trades across Kalshi and Polymarket."""
    client = get_client()
    try:
        data = client.whales(
            venue=venue, min_notional=min_notional, category=category, limit=limit
        )
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    trades = data.get("trades", [])
    summary = data.get("summary", "")
    if summary:
        click.echo(summary)
    click.echo(f"\n{len(trades)} whale trades (min ${min_notional:,.0f}):\n")
    for t in trades:
        click.echo(fmt_trade(t))


# ── veynor markets ─────────────────────────────────────────────────────────────

@cli.command("markets")
@click.option("--venue",    default="all", show_default=True,
              type=click.Choice(["all", "kalshi", "polymarket"]))
@click.option("--category", default=None,
              type=click.Choice(["All", "Sports", "Politics", "Other"]))
@click.option("--limit",    default=10, show_default=True, type=int,
              help="Max markets per platform (1-20).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def top_markets(venue: str, category: Optional[str], limit: int,
                as_json: bool) -> None:
    """Top markets by 24-hour volume."""
    client = get_client()
    try:
        data = client.top_markets(venue=venue, category=category, limit=limit)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    summary = data.get("summary", "")
    if summary:
        click.echo(summary)

    kalshi     = data.get("kalshi", [])
    polymarket = data.get("polymarket", [])

    if kalshi:
        click.echo("\nKalshi:\n")
        for m in kalshi:
            click.echo(fmt_market(m, "kalshi"))

    if polymarket:
        click.echo("\nPolymarket:\n")
        for m in polymarket:
            click.echo(fmt_market(m, "polymarket"))


# ── veynor search ──────────────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--venue",  default="all", show_default=True,
              type=click.Choice(["all", "kalshi", "polymarket"]))
@click.option("--limit",  default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def search(query: str, venue: str, limit: int, as_json: bool) -> None:
    """Search markets by keyword across both venues."""
    client = get_client()
    try:
        data = client.search(query, venue=venue, limit=limit)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    summary = data.get("summary", "")
    if summary:
        click.echo(summary)

    kalshi     = data.get("kalshi", [])
    polymarket = data.get("polymarket", [])

    if kalshi:
        click.echo(f"\nKalshi ({len(kalshi)} results):\n")
        for m in kalshi:
            click.echo(fmt_market(m, "kalshi"))

    if polymarket:
        click.echo(f"\nPolymarket ({len(polymarket)} results):\n")
        for m in polymarket:
            click.echo(fmt_market(m, "polymarket"))

    if not kalshi and not polymarket:
        click.echo(f'No markets found for "{query}".')


# ── veynor market ──────────────────────────────────────────────────────────────

@cli.command("market")
@click.argument("venue", type=click.Choice(["kalshi", "polymarket"]))
@click.argument("market_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def market_detail(venue: str, market_id: str, as_json: bool) -> None:
    """Full details for a specific market.

    \b
    Examples:
      veynor market kalshi KXNBA-25-LAL
      veynor market polymarket 0x1234...
    """
    client = get_client()
    try:
        data = client.market(venue, market_id)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    summary = data.get("summary", "")
    market  = data.get("market", {})

    if summary:
        click.echo(summary)
    if market:
        click.echo(json.dumps(market, indent=2))


# ── veynor signals ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--type", "signal_type", default="all", show_default=True,
              type=click.Choice(["all", "wide-spreads", "price-movers", "arb-opportunities"]),
              help="Signal type filter.")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def signals(signal_type: str, limit: int, as_json: bool) -> None:
    """Alpha signals: wide spreads, price movers, arb opportunities."""
    # Normalize hyphen to underscore for the API
    api_type = signal_type.replace("-", "_")
    client = get_client()
    try:
        data = client.signals(signal_type=api_type, limit=limit)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    summary = data.get("summary", "")
    if summary:
        click.echo(summary)

    sections = {
        "price_movers":      ("Price Movers",       data.get("price_movers", [])),
        "arb_opportunities": ("Arb Opportunities",  data.get("arb_opportunities", [])),
        "wide_spreads":      ("Wide Spreads",        data.get("wide_spreads", [])),
    }

    for key, (label, items) in sections.items():
        if items and (api_type == "all" or api_type == key):
            click.echo(f"\n{label}:\n")
            for s in items:
                click.echo(fmt_signal(s, key))


# ── veynor scan (shorthand) ────────────────────────────────────────────────────

@cli.command()
@click.argument("signal", type=click.Choice(["movers", "arb", "spreads"]))
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def scan(signal: str, limit: int, as_json: bool) -> None:
    """Shorthand for common signal scans.

    \b
    veynor scan movers    — biggest price moves in the last hour
    veynor scan arb       — cross-venue arb opportunities
    veynor scan spreads   — markets with wide bid/ask spreads
    """
    mapping = {
        "movers":  "price_movers",
        "arb":     "arb_opportunities",
        "spreads": "wide_spreads",
    }
    api_type = mapping[signal]
    client = get_client()
    try:
        data = client.signals(signal_type=api_type, limit=limit)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    items = data.get(api_type, [])
    summary = data.get("summary", "")
    if summary:
        click.echo(summary)
    click.echo(f"\n{len(items)} results:\n")
    for s in items:
        click.echo(fmt_signal(s, api_type))


# ── veynor usage ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def usage(as_json: bool) -> None:
    """Check your credit balance. Always free."""
    client = get_client()
    try:
        data = client.usage()
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    tier      = data.get("tier", "?")
    used      = data.get("credits_used", "?")
    remaining = data.get("credits_remaining")
    remaining = "unlimited" if remaining is None else remaining
    calls     = data.get("total_calls", "?")

    click.echo(f"\nTier:       {tier}")
    click.echo(f"Used:       {used} credits")
    click.echo(f"Remaining:  {remaining} credits")
    click.echo(f"Total calls: {calls}\n")


# ── veynor trade ───────────────────────────────────────────────────────────────

@cli.group()
def trade() -> None:
    """Place and manage Polymarket orders (requires pip install veynor[trade]).

    \b
    Setup (one time):
      pip install veynor[trade]
      export POLYMARKET_PRIVATE_KEY=0x...

    Get your key from Polymarket settings > Private Key.
    Works for both email (Magic) accounts and external wallets (MetaMask etc).

    For Magic/email accounts, also set your profile address:
      export POLYMARKET_ADDRESS=0x...   (shown in Polymarket profile settings)

    Store credentials in your shell -- never in code or git.
    All signing is local. Your key is never sent to Veynor's servers.

    \b
    Examples:
      veynor trade balance
      veynor trade positions
      veynor trade buy  0xabc...  --amount 50
      veynor trade sell 0xabc...  --shares 100
      veynor trade copy
    """


def _get_trader() -> PolymarketTrader:
    return PolymarketTrader()


def _handle_pm_error(e: PolymarketError) -> None:
    click.echo(f"Polymarket error: {e}", err=True)
    sys.exit(1)


# ── veynor trade balance ───────────────────────────────────────────────────────

@trade.command("balance")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_balance(as_json: bool) -> None:
    """Show your USDC balance on Polymarket."""
    trader = _get_trader()
    try:
        data = trader.get_balance()
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(data, True)
        return

    val  = data.get("value_usdc", 0)
    addr = data.get("address", "")
    click.echo(f"\n  Portfolio value: ${val:,.2f} USDC")
    if addr:
        click.echo(f"  Address:         {addr}")
    click.echo()


# ── veynor trade positions ─────────────────────────────────────────────────────

@trade.command("positions")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_positions(as_json: bool) -> None:
    """List your open Polymarket positions."""
    trader = _get_trader()
    try:
        positions = trader.get_positions()
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(positions, True)
        return

    if not positions:
        click.echo("\n  No open positions.\n")
        return

    click.echo(f"\n  {len(positions)} open positions:\n")
    for p in positions:
        outcome  = p.get("outcome", "?").upper()
        size     = p.get("size", 0)
        avg      = p.get("avg_price", 0)
        cur      = p.get("current_price", 0)
        val      = p.get("current_value", 0)
        pnl      = p.get("cash_pnl", 0)
        pnl_pct  = p.get("percent_pnl", 0)
        title    = p.get("title", "?")
        pnl_str  = f"{pnl:+.2f} ({pnl_pct:+.1f}%)"
        click.echo(f"  {outcome:<3}  {size:>7.2f} shares @ {avg:.3f}  now {cur:.3f}  val ${val:>7.2f}  pnl {pnl_str}")
        click.echo(f"       {title}")
        click.echo()
    click.echo()


# ── veynor trade buy ───────────────────────────────────────────────────────────

@trade.command("buy")
@click.argument("token_id")
@click.option("--amount", default=None, type=float,
              help="Fixed USDC amount to spend (e.g. --amount 50).")
@click.option("--pct", default=None, type=float,
              help="Percentage of available USDC balance to spend (e.g. --pct 5 = 5%).")
@click.option("--yes", "confirmed", is_flag=True,
              help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_buy(token_id: str, amount: Optional[float], pct: Optional[float],
              confirmed: bool, as_json: bool) -> None:
    """Buy shares on Polymarket with a market order.

    \b
    Specify size with --amount (fixed USDC) or --pct (% of available balance).
    TOKEN_ID is the outcome token address. Find it with:
      veynor market polymarket <market_id> --json

    \b
    Examples:
      veynor trade buy 0xabc... --amount 50
      veynor trade buy 0xabc... --pct 5        # spend 5% of balance
      veynor trade buy 0xabc... --pct 10 --yes
    """
    if amount is None and pct is None:
        click.echo("  Specify --amount or --pct.", err=True)
        sys.exit(1)
    if amount is not None and pct is not None:
        click.echo("  Use --amount or --pct, not both.", err=True)
        sys.exit(1)

    trader = _get_trader()

    # Resolve pct -> dollar amount against live balance
    if pct is not None:
        try:
            bal_data = trader.get_balance()
        except PolymarketError as e:
            _handle_pm_error(e)
            return
        balance = bal_data.get("balance_usdc", 0)
        if balance <= 0:
            click.echo(f"\n  Balance is ${balance:.2f} — nothing to deploy.\n", err=True)
            sys.exit(1)
        amount = round(balance * pct / 100, 2)
        click.echo(f"\n  Balance: ${balance:,.2f} USDC  |  {pct}% = ${amount:.2f}")

    if not confirmed:
        click.echo(f"\n  BUY ${amount:.2f} USDC of token {token_id[:16]}...")
        if not click.confirm("  Confirm order?"):
            click.echo("  Cancelled.")
            return

    try:
        result = trader.market_buy(token_id, amount)
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(result, True)
        return

    status   = result.get("status", "?")
    order_id = result.get("order_id", "")
    click.echo(f"\n  Order {status}")
    if order_id:
        click.echo(f"  ID: {order_id}")
    click.echo(f"  ${amount:.2f} USDC | token {token_id[:20]}...\n")


# ── veynor trade sell ──────────────────────────────────────────────────────────

@trade.command("sell")
@click.argument("token_id")
@click.option("--shares", required=True, type=float,
              help="Number of shares to sell.")
@click.option("--yes", "confirmed", is_flag=True,
              help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_sell(token_id: str, shares: float, confirmed: bool, as_json: bool) -> None:
    """Sell shares on Polymarket with a market order.

    \b
    Examples:
      veynor trade sell 0xabc... --shares 100
    """
    if not confirmed:
        click.echo(f"\n  SELL {shares:.2f} shares of token {token_id[:16]}...")
        if not click.confirm("  Confirm order?"):
            click.echo("  Cancelled.")
            return

    trader = _get_trader()
    try:
        result = trader.market_sell(token_id, shares)
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(result, True)
        return

    status   = result.get("status", "?")
    order_id = result.get("order_id", "")
    click.echo(f"\n  Order {status}")
    if order_id:
        click.echo(f"  ID: {order_id}")
    click.echo(f"  {shares:.2f} shares | token {token_id[:20]}...\n")


# ── veynor trade copy ──────────────────────────────────────────────────────────

@trade.command("copy")
@click.option("--min-notional", default=10_000, show_default=True, type=float,
              help="Minimum whale trade size to copy.")
@click.option("--pct", default=2.0, show_default=True, type=float,
              help="Percentage of your available USDC balance to deploy.")
@click.option("--amount", default=None, type=float,
              help="Fixed USDC override. Overrides --pct if both are passed.")
@click.option("--yes", "confirmed", is_flag=True,
              help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_copy(min_notional: float, pct: float, amount: Optional[float],
               confirmed: bool, as_json: bool) -> None:
    """Mirror the latest whale trade on Polymarket.

    \b
    Fetches the most recent large Polymarket trade from your Veynor feed,
    then places a proportional market order on the same token/direction.

    Size defaults to 2% of your available USDC balance. Use --pct to adjust
    or --amount to override with a fixed dollar figure.

    \b
    Examples:
      veynor trade copy                          # 2% of balance
      veynor trade copy --pct 5                  # 5% of balance
      veynor trade copy --amount 100             # fixed $100
      veynor trade copy --min-notional 50000     # only copy $50k+ whales
    """
    trader = _get_trader()

    # 1. Fetch balance first (needed for pct sizing and display)
    try:
        bal_data = trader.get_balance()
    except PolymarketError as e:
        _handle_pm_error(e)
        return
    balance = bal_data.get("balance_usdc", 0)

    # 2. Pull the latest Polymarket whale from the Veynor feed
    client = get_client()
    try:
        data = client.whales(venue="polymarket", min_notional=min_notional, limit=1)
    except VeynorError as e:
        handle_error(e)
        return

    trades = data.get("trades", [])
    if not trades:
        click.echo(f"\n  No Polymarket whale trades above ${min_notional:,.0f} right now.\n")
        return

    whale    = trades[0]
    notional = whale.get("notional", 0)
    side     = whale.get("side", "BUY").upper()
    token_id = whale.get("token_id", whale.get("asset_id", ""))
    market   = whale.get("market", whale.get("market_slug", "?"))
    price    = whale.get("price")

    if not token_id:
        click.echo(
            "\n  Cannot copy: whale trade is missing token_id. "
            "Try veynor whales --venue polymarket --json to inspect.\n",
            err=True,
        )
        sys.exit(1)

    # 3. Resolve deploy size
    if amount is not None:
        deploy = amount
        size_note = f"fixed amount"
    else:
        if balance <= 0:
            click.echo(f"\n  Balance is ${balance:.2f} — nothing to deploy.\n", err=True)
            sys.exit(1)
        deploy = round(balance * pct / 100, 2)
        size_note = f"{pct}% of ${balance:,.2f} balance"

    deploy = max(deploy, 1.0)  # CLOB minimum

    # 4. Show the full picture before confirming
    price_str = f" @ {price:.3f}" if price else ""
    click.echo(f"\n  Whale:      {side}{price_str}  ${notional:,.0f}  {market}")
    click.echo(f"  Your size:  ${deploy:.2f} USDC  ({size_note})")
    click.echo(f"  Token:      {token_id[:20]}...")

    if as_json:
        preview = {
            "whale": whale,
            "balance_usdc": balance,
            "your_order": {
                "side": side, "amount_usdc": deploy,
                "token_id": token_id, "market": market,
            },
        }
        if not confirmed:
            out(preview, True)
            return

    if not confirmed:
        if not click.confirm("\n  Place this order?"):
            click.echo("  Cancelled.")
            return

    # 5. Execute
    try:
        if side == "BUY":
            result = trader.market_buy(token_id, deploy)
        else:
            result = trader.market_sell(token_id, deploy)
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(result, True)
        return

    status   = result.get("status", "?")
    order_id = result.get("order_id", "")
    click.echo(f"\n  Order {status}")
    if order_id:
        click.echo(f"  ID: {order_id}")
    click.echo()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
