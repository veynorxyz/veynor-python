"""
Veynor CLI — prediction market intelligence from your terminal.

    pip install veynor
    export VEYNOR_API_KEY=vey_sk_...

    veynor wallet create
    veynor setup
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
    veynor trade orders             # open limit orders
    veynor trade buy  <token_id> --amount 50
    veynor trade sell <token_id> --shares 100
    veynor trade copy               # mirror latest whale trade
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
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
    plat  = platform or m.get("platform", "")
    title = m.get("title", m.get("question", m.get("slug", "?")))
    vol   = m.get("volume_24h", m.get("volume", 0)) or 0
    yes   = m.get("yes_price", m.get("last_price", m.get("price")))
    yes_str = f"  YES {round(yes * 100):>3}¢" if yes is not None else "          "
    return f"  [{plat}]{yes_str}  ${vol:>10,.0f}/24h  {title}"


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


# ── veynor wallet ──────────────────────────────────────────────────────────────

@cli.group("wallet")
def wallet() -> None:
    """Wallet utilities — create and inspect Polygon wallets for Polymarket trading."""


@wallet.command("create")
@click.option("--save", is_flag=True,
              help="Save private key to ~/.veynor/credentials (chmod 600).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for agents).")
def wallet_create(save: bool, as_json: bool) -> None:
    """Generate a new Polygon wallet keypair.

    \b
    Creates a fresh private key and Polygon address. You will still need to:
      1. Fund the wallet with USDC on Polygon
      2. Register it with Polymarket (one-time browser step)
    """
    try:
        from eth_account import Account
    except ImportError:
        click.echo(
            "eth-account is required. Run: pip install veynor[trade]", err=True
        )
        sys.exit(1)

    acct = Account.create()
    address = acct.address
    private_key = acct.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    if as_json:
        click.echo(json.dumps({
            "address":     address,
            "private_key": private_key,
            "network":     "polygon",
            "deposit_url": "https://polymarket.com/profile",
            "register_url": "https://polymarket.com",
        }, indent=2))
        return

    SEP = "  " + "─" * 44

    click.echo(f"\n  New Polygon wallet generated\n{SEP}\n")
    click.echo(f"  Address:     {address}")
    click.echo(f"  Private key: {private_key}\n")
    click.echo("  ⚠  Store your private key securely. Anyone with it controls your funds.")
    click.echo("     Never commit it to code or share it.\n")

    if save:
        import stat
        creds_dir  = os.path.expanduser("~/.veynor")
        creds_file = os.path.join(creds_dir, "credentials")
        os.makedirs(creds_dir, exist_ok=True)
        with open(creds_file, "w") as f:
            f.write(f"POLYMARKET_PRIVATE_KEY={private_key}\n")
            f.write(f"POLYMARKET_ADDRESS={address}\n")
        os.chmod(creds_file, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600
        click.echo(f"  Saved to: {creds_file}\n")
        click.echo("  Add this to your ~/.zshrc to load automatically:\n")
        click.echo(f"    source {creds_file}\n")
    else:
        click.echo("  [1] Save your key — add to ~/.zshrc:\n")
        click.echo(f"    export POLYMARKET_PRIVATE_KEY={private_key}")
        click.echo(f"    export POLYMARKET_ADDRESS={address}\n")

    click.echo("  [2] Fund with USDC on Polygon:\n")
    click.echo(f"    Deposit to: {address}")
    click.echo("    Bridge or buy at: https://polymarket.com/profile\n")
    click.echo("  [3] Register with Polymarket (one-time, requires browser):\n")
    click.echo("    https://polymarket.com → Sign in with wallet → connect your address\n")
    click.echo(SEP)
    click.echo("  Once funded and registered, run: veynor setup\n")


# ── veynor setup ───────────────────────────────────────────────────────────────

@cli.command("setup")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON (for agents).")
def setup(as_json: bool) -> None:
    """Interactive setup wizard — check API key, trade deps, wallet, and balance."""

    CHECK   = "  ✓"   # ✓
    CROSS   = "  ✗"   # ✗
    WARN    = "  ⚠"   # ⚠
    SEP     = "  " + "─" * 44

    results: dict = {}

    if not as_json:
        click.echo("\n  Veynor Setup\n" + SEP)

    # ── Step 1: API key ────────────────────────────────────────────────────────
    api_key = os.environ.get("VEYNOR_API_KEY")
    if not api_key:
        results["api_key"] = {"ok": False, "reason": "VEYNOR_API_KEY not set"}
        if as_json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"\n{CROSS}  [1/4] API key — not found\n")
            click.echo("  Get a free key at https://veynor.xyz/agents, then:\n")
            click.echo("    export VEYNOR_API_KEY=vey_sk_...\n")
            click.echo("  Add that line to ~/.zshrc to persist across sessions.\n")
        return

    try:
        client = Client(api_key=api_key)
        usage  = client.usage()
        tier   = usage.get("tier", "free")
        rem    = usage.get("credits_remaining", "?")
        results["api_key"] = {"ok": True, "tier": tier, "credits_remaining": rem}
        if not as_json:
            click.echo(f"\n{CHECK}  [1/4] API key        {tier} tier · {rem} credits remaining")
    except Exception as exc:
        results["api_key"] = {"ok": False, "reason": str(exc)}
        if as_json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"\n{CROSS}  [1/4] API key — invalid or unreachable ({exc})\n")
        return

    # ── Step 2: Trade dependencies ─────────────────────────────────────────────
    try:
        import py_clob_client  # noqa: F401
        import eth_account     # noqa: F401
        results["trade_deps"] = {"ok": True}
        if not as_json:
            click.echo(f"{CHECK}  [2/4] Trade deps     py-clob-client, eth-account")
    except ImportError:
        results["trade_deps"] = {"ok": False, "reason": "veynor[trade] not installed"}
        if as_json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"\n{CROSS}  [2/4] Trade deps — not installed\n")
            click.echo("  Run:\n")
            click.echo("    pip install veynor[trade]\n")
            click.echo("  Then run veynor setup again.\n")
        return

    # ── Step 3: Wallet / private key ───────────────────────────────────────────
    pk = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not pk:
        results["wallet"] = {"ok": False, "reason": "POLYMARKET_PRIVATE_KEY not set"}
        if as_json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"\n{CROSS}  [3/4] Wallet — POLYMARKET_PRIVATE_KEY not set\n")
            click.echo("  How to get your key:\n")
            click.echo("  • Email/Magic account:")
            click.echo("      polymarket.com → Profile → Settings → Private Key")
            click.echo("      (Magic will guide you through an export flow)\n")
            click.echo("  • MetaMask or external wallet:")
            click.echo("      MetaMask → Account details → Show private key\n")
            click.echo("  Then:\n")
            click.echo("    export POLYMARKET_PRIVATE_KEY=0x...")
            click.echo("    export POLYMARKET_ADDRESS=0x...   # Magic users only\n")
            click.echo("  Add both lines to ~/.zshrc to persist.\n")
        return

    try:
        from .polymarket_trader import PolymarketTrader, PolymarketError as PMError
        trader  = PolymarketTrader()
        status  = trader.wallet_status()
        addr    = status["address"]
        balance = status["usdc_balance"]
        funded  = status["is_funded"]

        results["wallet"] = {"ok": True, "address": addr}
        if not as_json:
            short = addr[:20] + "..." if len(addr) > 20 else addr
            click.echo(f"{CHECK}  [3/4] Wallet         {short}")

        # ── Step 4: USDC balance ───────────────────────────────────────────────
        results["balance"] = {
            "ok":           funded,
            "usdc_balance": balance,
            "deposit_address": addr,
            "deposit_url":  "https://polymarket.com/profile",
        }
        if as_json:
            results["ready_to_trade"] = funded
            click.echo(json.dumps(results, indent=2))
        else:
            if balance >= 10:
                click.echo(f"{CHECK}  [4/4] USDC balance   ${balance:,.2f} available")
                click.echo(f"\n{SEP}")
                click.echo("  Ready. Try:\n")
                click.echo("    veynor trade buy <token_id> --amount 10\n")
            elif balance > 0:
                click.echo(f"{WARN}  [4/4] USDC balance   ${balance:,.2f} (low)\n")
                click.echo("  Deposit USDC (Polygon network) to:")
                click.echo(f"    {addr}\n")
                click.echo("  Or visit: https://polymarket.com/profile → Add Funds\n")
            else:
                click.echo(f"{CROSS}  [4/4] USDC balance   $0.00 — wallet not funded\n")
                click.echo("  Deposit USDC (Polygon network) to:")
                click.echo(f"    {addr}\n")
                click.echo("  Or visit: https://polymarket.com/profile → Add Funds\n")

    except Exception as exc:
        results["wallet"] = {"ok": False, "reason": str(exc)}
        if as_json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(f"\n{CROSS}  [3/4] Wallet — could not initialise ({exc})\n")
            click.echo("  Check that your POLYMARKET_PRIVATE_KEY is a valid 0x... hex key.\n")


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


# ── veynor positions ───────────────────────────────────────────────────────────

@cli.command("positions")
@click.argument("wallet", default=None, required=False)
@click.option("--size-threshold", default=0.1, show_default=True, type=float,
              help="Minimum position size to include.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def positions(wallet: Optional[str], size_threshold: float, as_json: bool) -> None:
    """Show open positions for a Polymarket wallet address.

    \b
    WALLET is a Polymarket proxy wallet address (0x...).
    Falls back to the POLYMARKET_ADDRESS environment variable if not provided.
    No private key required — read-only intelligence call.

    \b
    Examples:
      veynor positions 0xabc...
      veynor positions                        # uses $POLYMARKET_ADDRESS
      veynor positions 0xabc... --json
    """
    addr = wallet or os.environ.get("POLYMARKET_ADDRESS")
    if not addr:
        click.echo(
            "  No wallet address provided. Pass one as an argument or set "
            "POLYMARKET_ADDRESS in your environment.",
            err=True,
        )
        sys.exit(1)

    client = get_client()
    try:
        items = client.positions(addr, size_threshold=size_threshold)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(items, True)
        return

    if not items:
        click.echo("\n  No open positions.\n")
        return

    total_val  = sum(p.get("currentValue", 0) for p in items)
    total_pnl  = sum(p.get("cashPnl", 0) for p in items)
    total_real = sum(p.get("realizedPnl", 0) for p in items)

    click.echo(f"\n  {len(items)} open position(s)   val ${total_val:,.2f}   unrealized {total_pnl:+.2f}   realized {total_real:+.2f}\n")
    for p in items:
        outcome  = p.get("outcome", "?").upper()
        size     = p.get("size", 0)
        avg      = p.get("avgPrice", 0)
        cur      = p.get("curPrice", 0)
        val      = p.get("currentValue", 0)
        pnl      = p.get("cashPnl", 0)
        pnl_pct  = p.get("percentPnl", 0)
        title    = p.get("title", "?")
        end_date = p.get("endDate", "")
        pnl_str  = f"{pnl:+.2f} ({pnl_pct:+.1f}%)"
        date_str = f"  exp {end_date}" if end_date else ""
        click.echo(f"  {outcome:<3}  {size:>7.1f} shares @ {avg:.3f}  now {cur:.3f}  val ${val:>7.2f}  pnl {pnl_str}{date_str}")
        click.echo(f"       {title}")
        click.echo()


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


# ── veynor pulse ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--venue", default="all", type=click.Choice(["all", "kalshi", "polymarket"]),
              help="Filter by venue (default: all).")
@click.option("--category", default=None, type=click.Choice(["All", "Sports", "Politics", "Other"]),
              help="Filter by category.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def pulse(venue: str, category: Optional[str], as_json: bool) -> None:
    """AI-synthesized prediction market briefing.

    \b
    Covers:
      - Top markets by 24h volume
      - Whale activity and directional bias
      - Wide spread opportunities (inefficiencies)
      - Price movers (biggest 1h moves)
      - Volume spikes (unusual flow vs baseline)

    \b
    Examples:
      veynor pulse
      veynor pulse --venue kalshi
      veynor pulse --category Politics
      veynor pulse --json | jq '.highlights.volume_spikes'
    """
    client = get_client()
    try:
        data = client.pulse(venue=venue, category=category)
    except VeynorError as e:
        handle_error(e)
        return

    if as_json:
        out(data, True)
        return

    summary   = data.get("summary", "No summary available.")
    hl        = data.get("highlights", {})
    meta      = data.get("meta", {})
    top_mkts  = hl.get("top_markets", [])
    whales    = hl.get("whale_activity", {})
    spreads   = hl.get("wide_spreads", [])
    movers    = hl.get("price_movers", [])
    spikes    = hl.get("volume_spikes", [])
    data_age  = meta.get("data_age", "")

    click.echo()
    click.echo(f"  Prediction Market Pulse — {datetime.now().strftime('%a %b %d %Y')}")
    if data_age:
        click.echo(f"  Data as of: {data_age[:19].replace('T', ' ')}")
    click.echo()
    click.echo(f"  {summary}")
    click.echo()

    # _t() is defined at module level — no local shadow needed

    if top_mkts:
        click.echo("  Top markets")
        for m in top_mkts[:3]:
            click.echo(
                f"    {_t(m.get('title', ''), 52):<54}  "
                f"{m.get('volume_24h', ''):>8}  ({m.get('venue', '')})"
            )

    if whales:
        recent = whales.get("recent", [])
        if recent:
            click.echo("  Whale flow")
            for t in recent[:2]:
                market  = _t(str(t.get("market", "")), 52)
                side    = str(t.get("side", "YES"))
                notional = str(t.get("notional", ""))
                venue   = str(t.get("venue", ""))
                click.echo(f"    {market:<54}  {side:<3}  {notional:>7}  {venue}")
        else:
            click.echo(
                f"  Whale flow     {whales.get('count', 0)} trades  "
                f"{whales.get('total_notional', '$0')} total  "
                f"{whales.get('bias', '—')}"
            )

    if movers:
        m = movers[0]
        click.echo(
            f"  Biggest mover  {_t(m.get('title', '')):<57}  "
            f"{m.get('move_1h') or m.get('move_15m') or '—'} (1h)"
        )

    if spikes:
        s = spikes[0]
        click.echo(
            f"  Volume spike   {_t(s.get('title', '')):<57}  "
            f"{s.get('spike_ratio', '—')} ratio  "
            f"{s.get('recent_flow', '')} recent"
        )

    if spreads:
        sp = spreads[0]
        click.echo(
            f"  Wide spread    {_t(sp.get('title', '')):<57}  "
            f"bid/ask {sp.get('bid_ask', '—')}  spread {sp.get('spread_cents', '—')}"
        )

    credits = meta.get("credits_used", 5)
    click.echo()
    click.echo(f"  {credits} credits used · veynor.xyz/agents to upgrade")
    click.echo()


# ── veynor ask ─────────────────────────────────────────────────────────────────

def _t(title: str, max_len: int = 55) -> str:
    """Truncate at a word boundary, append ellipsis only if actually cut."""
    if len(title) <= max_len:
        return title
    cut = title[:max_len].rsplit(" ", 1)[0]
    return cut + "…"


VALID_TAGS = ["crypto", "geopolitics", "trump", "us_politics", "macro", "sports"]

@cli.command("ask")
@click.argument("tag", type=click.Choice(VALID_TAGS, case_sensitive=False))
@click.option("--limit", default=20, show_default=True, type=int,
              help="Max markets to return.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def ask(tag: str, limit: int, as_json: bool) -> None:
    """Cross-venue market summary for a topic.

    TAG is one of: crypto, geopolitics, trump, us_politics, macro, sports

    \b
    Examples:
      veynor ask geopolitics
      veynor ask trump
      veynor ask crypto --limit 30
    """
    client = get_client()
    try:
        data = client.topic(tag, limit=limit)
    except (VeynorError, AuthError) as e:
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    summary  = data.get("summary", "")
    markets  = data.get("markets", [])
    meta     = data.get("meta", {})
    total    = meta.get("total", len(markets))
    kalshi_n = meta.get("kalshi_count", 0)
    poly_n   = meta.get("polymarket_count", 0)

    tag_labels = {
        "crypto":     "Crypto",
        "geopolitics":"Geopolitics",
        "trump":      "Trump",
        "us_politics":"US Politics",
        "macro":      "Macro / Economy",
        "sports":     "Sports",
    }
    label = tag_labels.get(tag, tag)

    click.echo()
    click.echo(f"  {label} — prediction market snapshot")
    click.echo(f"  {total} markets  ·  Kalshi: {kalshi_n}  Polymarket: {poly_n}")
    click.echo()
    click.echo(f"  {summary}")
    click.echo()

    if markets:
        click.echo(f"  {'Market':<122}  {'Price':>5}  {'Vol/24h':>9}  Venue")
        click.echo("  " + "-" * 146)
        for m in markets[:15]:
            raw_title = m.get("title", "")
            # For Kalshi multi-outcome markets the title is shared across variants.
            # Extract the outcome keyword from the ticker suffix (e.g. KXFOO-26MAY-IRAN → "Iran")
            market_id = str(m.get("id", ""))
            if market_id.startswith("KALSHI:"):
                suffix = market_id.split("-")[-1].upper()
                # Only append if it looks like a meaningful outcome tag (2-6 alpha chars)
                if suffix.isalpha() and 2 <= len(suffix) <= 6:
                    raw_title = f"{raw_title} [{suffix}]"
            title   = raw_title  # no truncation — show full title
            price   = f"{round(float(m.get('yes_price', 0)) * 100)}¢"
            vol     = m.get("volume_24h", 0)
            vol_str = f"${vol/1_000_000:.1f}M" if vol >= 1_000_000 else f"${vol/1_000:.0f}K" if vol >= 1_000 else f"${vol:.0f}"
            venue   = str(m.get("platform", "")).upper()
            click.echo(f"  {title:<122}  {price:>5}  {vol_str:>9}  {venue}")

    credits = meta.get("credits_used", 3)
    click.echo()
    click.echo(f"  {credits} credits used · veynor.xyz/agents to upgrade")
    click.echo()


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

    cash     = data.get("cash_usdc", 0)
    pos_val  = data.get("positions_value", 0)
    total    = data.get("total_value", 0)
    addr     = data.get("address", "")
    click.echo(f"\n  Cash (available):  ${cash:,.2f}")
    click.echo(f"  In positions:      ${pos_val:,.2f}")
    click.echo(f"  Total value:       ${total:,.2f}")
    if addr:
        click.echo(f"  Address:           {addr}")
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
@click.option("--neg-risk", "neg_risk", is_flag=True,
              help="Use neg-risk exchange contract (required for neg-risk markets).")
@click.option("--yes", "confirmed", is_flag=True,
              help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_buy(token_id: str, amount: Optional[float], pct: Optional[float],
              neg_risk: bool, confirmed: bool, as_json: bool) -> None:
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
        balance = bal_data.get("cash_usdc", 0)
        if balance <= 0:
            click.echo(f"\n  Balance is ${balance:.2f} — nothing to deploy.\n", err=True)
            sys.exit(1)
        amount = round(balance * pct / 100, 2)
        click.echo(f"\n  Cash available: ${balance:,.2f}  |  {pct}% = ${amount:.2f}")

    if not confirmed:
        click.echo(f"\n  BUY ${amount:.2f} USDC of token {token_id[:16]}...")
        if not click.confirm("  Confirm order?"):
            click.echo("  Cancelled.")
            return

    try:
        result = trader.market_buy(token_id, amount, neg_risk=neg_risk)
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
    balance = bal_data.get("cash_usdc", 0)

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
        size_note = f"{pct}% of ${balance:,.2f} cash"

    deploy = max(deploy, 1.0)  # CLOB minimum

    # 4. Show the full picture before confirming
    price_str = f" @ {price:.3f}" if price else ""
    click.echo(f"\n  Whale:      {side}{price_str}  ${notional:,.0f}  {market}")
    click.echo(f"  Your size:  ${deploy:.2f} USDC  ({size_note})")
    click.echo(f"  Token:      {token_id[:20]}...")

    if as_json:
        preview = {
            "whale": whale,
            "cash_usdc": balance,
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


# ── veynor trade limit ────────────────────────────────────────────────────────

@trade.command("limit")
@click.argument("side", type=click.Choice(["buy", "sell"]))
@click.argument("token_id")
@click.option("--price", required=True, type=float, help="Limit price (e.g. 0.83 for 83 cents).")
@click.option("--size",  required=True, type=float, help="Number of shares/contracts.")
@click.option("--yes", "confirmed", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_limit(side: str, token_id: str, price: float, size: float,
                confirmed: bool, as_json: bool) -> None:
    """Place a GTC limit order on Polymarket.

    \b
    Examples:
      veynor trade limit buy  0xabc... --price 0.83 --size 5
      veynor trade limit sell 0xabc... --price 0.95 --size 20
    """
    trader = _get_trader()

    if not confirmed:
        click.echo(f"\n  LIMIT {side.upper()} {size:.2f} shares @ {price:.4f}  (~${price * size:.2f})")
        click.echo(f"  Token: {token_id[:24]}...")
        if not click.confirm("  Place order?"):
            click.echo("  Cancelled.")
            return

    try:
        if side == "buy":
            result = trader.limit_buy(token_id, price, size)
        else:
            result = trader.limit_sell(token_id, price, size)
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
    click.echo(f"  {side.upper()} {size:.2f} shares @ {price:.4f}  token {token_id[:20]}...\n")


# ── veynor trade orders ────────────────────────────────────────────────────────

@trade.command("orders")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def trade_orders(as_json: bool) -> None:
    """List your open limit orders on Polymarket."""
    trader = _get_trader()
    try:
        orders = trader.get_open_orders()
    except PolymarketError as e:
        _handle_pm_error(e)
        return

    if as_json:
        out(orders, True)
        return

    if not orders:
        click.echo("\n  No open orders.\n")
        return

    click.echo(f"\n  {len(orders)} open order(s):\n")
    for o in orders:
        order_id = o.get("id", o.get("orderID", "?"))
        side     = o.get("side", "?").upper()
        size     = float(o.get("original_size") or o.get("originalSize") or o.get("size") or 0)
        filled   = float(o.get("size_matched") or o.get("sizeMatched") or o.get("sizeFilled") or 0)
        price    = o.get("price")
        asset    = o.get("asset_id", o.get("tokenID", "?"))
        outcome  = o.get("outcome", "")
        status   = o.get("status", o.get("orderStatus", "?"))
        price_str  = f" @ {float(price):.4f}" if price is not None else ""
        filled_str = f"  filled {filled:.2f}/{size:.2f}" if filled > 0 else f"  size {size:.2f}"
        outcome_str = f"  {outcome}" if outcome else ""
        click.echo(f"  {side}{outcome_str}{price_str}{filled_str}  [{status}]")
        click.echo(f"    token {str(asset)[:20]}...  id {str(order_id)[:12]}...")
        click.echo()
    click.echo()


# ── veynor follow ──────────────────────────────────────────────────────────────

@cli.command("follow")
@click.option("--amount", default=None, type=float,
              help="Fixed USDC to spend per copied trade (e.g. --amount 5).")
@click.option("--pct", default=None, type=float,
              help="% of available balance per copied trade (e.g. --pct 2).")
@click.option("--min-notional", default=10_000, type=float, show_default=True,
              help="Only copy whale trades at or above this size in USD.")
@click.option("--category", default="All", show_default=True,
              type=click.Choice(["All", "Sports", "Politics", "Other"], case_sensitive=False),
              help="Only follow trades in this category.")
@click.option("--sides", default="YES", show_default=True,
              type=click.Choice(["YES", "NO", "ALL"], case_sensitive=False),
              help="Which sides to follow: YES, NO, or ALL.")
@click.option("--max-daily", default=0.0, type=float,
              help="Max USDC to spend per day across all copied trades (0 = no cap).")
@click.option("--interval", default=30, type=int, show_default=True,
              help="Poll interval in seconds.")
@click.option("--dry-run", is_flag=True,
              help="Log what would be traded without executing any orders.")
@click.option("--verbose", is_flag=True,
              help="Log every poll cycle, not just new trades.")
@click.option("--venues", default=None, multiple=True,
              type=click.Choice(["polymarket", "kalshi"], case_sensitive=False),
              help="Which venues to follow (default: auto-detect from env). "
                   "Repeat for multiple: --venues polymarket --venues kalshi")
def follow(
    amount: Optional[float],
    pct: Optional[float],
    min_notional: float,
    category: str,
    sides: str,
    max_daily: float,
    interval: int,
    dry_run: bool,
    verbose: bool,
    venues: tuple,
) -> None:
    """Mirror large whale trades on Polymarket and/or Kalshi automatically.

    \b
    Polls the Veynor whale feed every INTERVAL seconds. When a new trade
    is detected above MIN_NOTIONAL, it buys the same outcome on your
    connected exchange account(s).

    \b
    Polymarket credentials:
      export POLYMARKET_PRIVATE_KEY=0x...
      export POLYMARKET_ADDRESS=0x...    (Magic/email wallet proxy address)

    \b
    Kalshi credentials (optional -- auto-detected if set):
      export KALSHI_API_KEY_ID=<uuid>
      export KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem

    \b
    Safety: use --max-daily to cap total spend per day.
    Test first with --dry-run to see what would be traded.

    \b
    Examples:
      veynor follow --amount 2 --dry-run
      veynor follow --amount 5 --min-notional 20000
      veynor follow --pct 2 --max-daily 50 --category Politics
      veynor follow --amount 10 --sides ALL --interval 15
      veynor follow --amount 3 --venues polymarket --venues kalshi
    """
    if amount is None and pct is None:
        amount = 2.0
        click.echo("  No --amount or --pct specified. Defaulting to $2 per trade.")

    if amount is not None and pct is not None:
        click.echo("  Use --amount or --pct, not both.", err=True)
        sys.exit(1)

    from .follower import run_follower
    client = get_client()

    run_follower(
        client=client,
        min_notional=min_notional,
        amount=amount,
        pct=pct,
        category=category,
        max_daily=max_daily,
        interval=interval,
        dry_run=dry_run,
        sides=sides,
        venues=list(venues) if venues else None,
        verbose=verbose,
        echo=click.echo,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
