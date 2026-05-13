# veynor

Python client for the [Veynor](https://veynor.xyz) prediction market intelligence API.

Cross-venue data and trading across Kalshi and Polymarket: whale trades, smart money signals, arb opportunities, market search, price history, and order execution — in a single `import`.

```python
pip install veynor
```

---

## Quickstart

```python
import veynor

client = veynor.Client(api_key="vey_sk_...")

# Whale trades across both venues
whales = client.whales(venue="all", min_notional=10_000)
for t in whales["trades"]:
    print(t["platform"], t["market"], t["side"], f"${t['notional']:,.0f}")

# Arb opportunities between Kalshi and Polymarket
arb = client.signals(signal_type="arb_opportunities")
for opp in arb["arb_opportunities"]:
    print(opp)
```

Get a free API key at [veynor.xyz/agents](https://veynor.xyz/agents).

---

## Authentication

Pass your key directly or via environment variable:

```python
# Option 1: direct
client = veynor.Client(api_key="vey_sk_...")

# Option 2: environment variable
# export VEYNOR_API_KEY=vey_sk_...
client = veynor.Client()
```

---

## Methods

### `client.whales()`

Recent large trades across Kalshi and Polymarket.

```python
whales = client.whales(
    venue="all",           # "all" | "kalshi" | "polymarket"
    min_notional=8_000,    # minimum trade size in USD
    category="Politics",   # "All" | "Sports" | "Politics" | "Other"
    limit=20,
)
# Returns: { summary, trades: [...], meta }
```

### `client.top_markets()`

Top markets by 24-hour volume.

```python
markets = client.top_markets(
    venue="all",
    category="All",
    limit=10,
)
# Returns: { summary, kalshi: [...], polymarket: [...], meta }
```

### `client.search()`

Search markets by keyword across both venues. Results include current YES price, 24-hour volume, end date, spread, and liquidity.

```python
results = client.search("fed rate", venue="all", limit=10)
# Returns: { summary, polymarket: [...], kalshi: [...], meta }
# Each market includes: title, yes_price, volume_24h, end_date, spread_cents, liquidity, url
```

### `client.market()`

Full details for a specific market.

```python
# Polymarket: use condition ID
m = client.market("polymarket", "0x1234...")

# Kalshi: use ticker
m = client.market("kalshi", "KXNBA-25-LAL")

# Returns: { summary, market: {...}, meta }
```

### `client.signals()`

Alpha signals: wide spreads, price movers, cross-venue arb.

```python
signals = client.signals(
    signal_type="all",   # "all" | "wide_spreads" | "price_movers" | "arb_opportunities"
    limit=10,
)
# Returns: { summary, wide_spreads, price_movers, arb_opportunities, meta }
```

### `client.positions()`

Open positions for a Polymarket wallet address. No private key required.

```python
for p in client.positions("0xabc..."):
    print(p["title"], p["cashPnl"])
```

### `client.pulse()`

AI-synthesized plain-English market briefing. Covers top markets by volume, whale activity, price movers, volume spikes, and wide spreads in a single call. Synthesis is powered by Claude Haiku on the server — no LLM setup needed on your end.

```python
pulse = client.pulse(
    venue="all",         # "all" | "kalshi" | "polymarket"
    category="All",      # "All" | "Sports" | "Politics" | "Other"
)
print(pulse["summary"])
# Returns: { summary (plain-English briefing), highlights, meta }
```

### `client.usage()`

Check your credit balance. Always free.

```python
u = client.usage()
print(u["tier"], u["credits_remaining"])
```

---

## Credit costs

| Method            | Credits |
|-------------------|---------|
| `whales()`        | 2       |
| `top_markets()`   | 1       |
| `search()`        | 1       |
| `market()`        | 1       |
| `signals()`       | 3       |
| `price_history()` | 1       |
| `pulse()`         | 5       |
| `usage()`         | 0       |

Free tier: 100 credits/month. Upgrade at [veynor.xyz/agents](https://veynor.xyz/agents).

---

## Exceptions

```python
from veynor import VeynorError, AuthError, RateLimitError

try:
    whales = client.whales()
except AuthError:
    print("Invalid or expired API key")
except RateLimitError:
    print("Rate limit hit — slow down or upgrade tier")
except VeynorError as e:
    print(f"API error {e.status_code}: {e}")
```

---

## REST API

All SDK methods map directly to REST endpoints at `https://api.veynor.xyz`. Pass your key via `X-API-Key` header.

```bash
# Whale trades
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/whale-trades?min_notional=10000&limit=10"

# Top markets by 24h volume
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/top?limit=10"

# Search markets
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/search?q=fed+rate"

# Specific market
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/polymarket/0x1234..."
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/kalshi/KXNBA-25-LAL"

# Price history (~1h rolling, 60s snapshots)
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/polymarket/0x1234.../history"
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/kalshi/KXNBA-25-LAL/history"

# Alpha signals
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/signals?signal_type=arb_opportunities"

# Market pulse (AI-synthesized briefing)
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/pulse" | jq .summary

# Credit usage
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/usage"
```

| Endpoint | Params | Credits |
|----------|--------|---------|
| `GET /v1/whale-trades` | `venue`, `min_notional`, `category`, `limit` | 2 |
| `GET /v1/markets/top` | `venue`, `category`, `limit` | 1 |
| `GET /v1/markets/search` | `q` (required), `venue`, `limit` | 1 |
| `GET /v1/markets/:venue/:id` | — | 1 |
| `GET /v1/markets/:venue/:id/history` | — | 1 |
| `GET /v1/signals` | `signal_type`, `limit` | 3 |
| `GET /v1/pulse` | `venue`, `category` | 5 |
| `POST /v1/credentials/kalshi` | `kalshi_key_id`, `private_key` | 0 |
| `GET /v1/credentials/kalshi` | — | 0 |
| `DELETE /v1/credentials/kalshi` | — | 0 |
| `POST /v1/trade/kalshi` | `ticker`, `action`, `side`, `count`, `price` | 2 |
| `POST /v1/trade/submit` | `order`, `signature`, `wallet` | 2 |
| `GET /v1/usage` | — | 0 |

---

## CLI

Every API method is also available as a shell command. Set your key once:

```bash
export VEYNOR_API_KEY=vey_sk_...
```

### Search markets

```bash
veynor search "fed rate"
veynor search "bitcoin" --limit 20
veynor search "election" --venue kalshi
```

Output shows YES price, 24-hour volume, and platform for each result:

```
  [polymarket]  YES  62¢  $  1,234,567/24h  Will the Fed cut rates in June?
  [kalshi]      YES  58¢  $    412,300/24h  Fed rate cut — June 2025
```

Add `--json` for machine-readable output:

```bash
veynor search --json "bitcoin" | jq '.results[].yes_price'
```

### Whale trades

```bash
veynor whales
veynor whales --min-notional 50000
veynor whales --venue kalshi --limit 5
```

### Top markets

```bash
veynor top
veynor top --venue polymarket --limit 20
```

### Signals

```bash
veynor signals                          # all signals
veynor signals --type wide_spreads
veynor signals --type arb_opportunities
veynor signals --type price_movers
```

### Market detail

```bash
veynor market polymarket <condition_id>
veynor market kalshi KXNBA-25-LAL
veynor market kalshi KXNBA-25-LAL --json
```

### Market pulse

A plain-English briefing synthesized from live data — top markets, whale activity, price movers, volume spikes, and wide spreads in one shot:

```bash
veynor pulse
veynor pulse --venue kalshi
veynor pulse --category Sports
```

Sample output:

```
  Prediction Market Pulse — Wed May 13 2026
  Data as of: 2026-05-13 14:14:54

  Tennis markets are the real action right now: Pol Martin Tiffon collapsed
  66.5¢ in the last hour to 6.5¢ while Chris Rodesch surged 59¢ on Kalshi,
  indicating live match developments. Whale activity is NO-heavy at $178K
  total notional, anchored by a $34K Manchester City bet...

  Top markets
    Will Bitcoin hit $150k by June 30, 2026?           $5.8M  (POLYMARKET)
    Hantavirus pandemic in 2026?                       $1.1M  (POLYMARKET)
    Starmer out by May 15, 2026?                       $1.1M  (POLYMARKET)
  Whale flow     10 trades  $178K total  NO-heavy
  Biggest mover  Will Pol Martin Tiffon win the match…           -66.5¢ (1h)
  Volume spike   New York Yankees vs. Baltimore Orioles          164.8× ratio
  Wide spread    Will Lillestrøm SK vs. Viking FK end in a draw?  bid/ask 12¢ / 51¢

  5 credits used · veynor.xyz/agents to upgrade
```

### Credit usage

```bash
veynor usage
```

---

## Use in a Jupyter notebook

```python
import veynor, pandas as pd

client = veynor.Client()
data   = client.whales(min_notional=15_000, limit=50)
df     = pd.DataFrame(data["trades"])
df[["market", "side", "notional", "platform"]].sort_values("notional", ascending=False)
```

---

## Kalshi order execution

Place orders on Kalshi directly using your personal API key pair. All signing happens locally — your private key never leaves your machine.

### 1. Install trade dependencies

```bash
pip install veynor[trade]
```

This adds `cryptography` (for RSA signing) on top of the base install.

### 2. Generate a key pair and register it

```bash
# Generate RSA key pair
openssl genrsa -out kalshi_key.pem 2048
openssl rsa -in kalshi_key.pem -pubout   # copy this output
```

Paste the public key at [kalshi.com/profile/api-keys](https://kalshi.com/profile/api-keys) and copy the resulting Key ID (a UUID).

### 3. Set credentials

```bash
export KALSHI_API_KEY_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi_key.pem
```

Or pass the PEM text directly:

```bash
export KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
```

### 4. Trade

```python
from veynor import KalshiTrader

trader = KalshiTrader()   # reads env vars automatically

# Account
print(trader.get_balance())    # { cash_usd, cash_cents, ... }
print(trader.get_positions())  # open positions

# Market buy — spend $50 on YES
result = trader.market_buy("KXNBA-25JUL05-T204", side="YES", amount_usd=50.0)
print(result["order_id"], result["status"])

# Limit buy — 100 contracts at 65¢
result = trader.limit_buy("KXNBA-25JUL05-T204", side="YES", price=0.65, count=100)

# Buy NO side
result = trader.limit_buy("KXNBA-25JUL05-T204", side="NO", price=0.40, count=50)

# Market sell
result = trader.market_sell("KXNBA-25JUL05-T204", side="YES", count=100)

# Limit sell
result = trader.limit_sell("KXNBA-25JUL05-T204", side="YES", price=0.72, count=100)

# Cancel an open order
trader.cancel_order(order_id)

# Open orders
orders = trader.get_open_orders()
orders = trader.get_open_orders(ticker="KXNBA-25JUL05-T204")
```

### Via the REST API

Register credentials once (encrypted at rest — never returned in any response):

```bash
curl -X POST https://api.veynor.xyz/v1/credentials/kalshi \
  -H "X-API-Key: vey_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "kalshi_key_id": "your-uuid",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n..."
  }'

# Check status
curl -H "X-API-Key: vey_sk_..." \
  https://api.veynor.xyz/v1/credentials/kalshi

# Remove stored credentials
curl -X DELETE -H "X-API-Key: vey_sk_..." \
  https://api.veynor.xyz/v1/credentials/kalshi
```

Then place orders against your own Kalshi account:

```bash
# Limit buy — 100 YES contracts at 65¢
curl -X POST https://api.veynor.xyz/v1/trade/kalshi \
  -H "X-API-Key: vey_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"ticker": "KXNBA-25JUL05-T204", "action": "buy", "side": "YES", "count": 100, "price": 0.65}'

# Market sell
curl -X POST https://api.veynor.xyz/v1/trade/kalshi \
  -H "X-API-Key: vey_sk_..." \
  -d '{"ticker": "KXNBA-25JUL05-T204", "action": "sell", "side": "YES", "count": 100, "order_type": "market"}'
```

Each user's trades execute on their own Kalshi account. Credentials are AES-256-GCM encrypted at rest and scoped to your Veynor API key.

### Errors and troubleshooting

| Error | Fix |
|-------|-----|
| `No Kalshi credentials registered` | Call `POST /v1/credentials/kalshi` or set env vars |
| `cryptography package not installed` | Run `pip install veynor[trade]` |
| `Kalshi API error (401)` | Check that your Key ID matches the registered public key |
| `Kalshi API error (403)` | API key may be read-only — enable trading in Kalshi dashboard |

---

## Polymarket order execution

Place orders on Polymarket directly from Python. All signing happens locally — your private key never leaves your machine and is never sent to Veynor's servers.

Supports Polymarket V2 (live April 28, 2026): native EIP-712 signing, pUSD collateral, proxy wallet and plain EOA flows.

### 1. Install trade dependencies

```bash
pip install veynor[trade]
```

### 2. Set credentials

```bash
export POLYMARKET_PRIVATE_KEY=0x...   # required — your EOA private key
export POLYMARKET_ADDRESS=0x...       # optional — proxy wallet address (Magic users)
```

If you set `POLYMARKET_ADDRESS`, orders are placed via your proxy wallet (signatureType 1). Without it, your EOA signs directly (signatureType 0).

### 3. Trade

```bash
# Check pUSD balance
veynor trade balance

# Open positions
veynor trade positions

# Market buy $50 of YES shares
veynor trade buy <token_id> --amount 50

# Neg-risk market (most multi-outcome markets)
veynor trade buy <token_id> --amount 50 --neg-risk

# Sell 100 shares
veynor trade sell <token_id> --shares 100

# Copy the latest whale trade
veynor trade copy
veynor trade copy --min-notional 50000 --amount 200 --yes
```

### Python API

```python
from veynor import PolymarketTrader

trader = PolymarketTrader()
print(trader.get_balance())

result = trader.market_buy(token_id, amount_usdc=50.0, neg_risk=True)
result = trader.limit_buy(token_id, price=0.72, size=10.0)
result = trader.market_sell(token_id, amount_shares=10.0)
result = trader.limit_sell(token_id, price=0.80, size=10.0)
orders = trader.get_open_orders()
trader.cancel_order(order_id)
```

### Via the REST API (no-custody relay)

Sign the order with your wallet, pass the signature to Veynor. Your private key never touches our servers:

```bash
curl -X POST https://api.veynor.xyz/v1/trade/submit \
  -H "X-API-Key: vey_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "order":     { ...eip712_order_fields... },
    "signature": "0x...",
    "wallet":    "0x...",
    "order_type": "GTC"
  }'
```

### Errors and troubleshooting

| Error | Fix |
|-------|-----|
| `No private key found` | Set `POLYMARKET_PRIVATE_KEY` |
| `Failed to derive API credentials` | Key must be a valid hex string starting with `0x` |
| `Trading requires extra packages` | Run `pip install veynor[trade]` |
| `Trading restricted in your region` | Polymarket geo-blocks certain IPs — use a non-restricted server |
| Order status `unmatched` | Insufficient liquidity — try a smaller amount |

---

## What's new in v1.4.2

- **Market pulse** — `client.pulse()` and `veynor pulse` CLI command. AI-synthesized plain-English briefing covering top markets, whale flow, price movers, volume spikes, and wide spreads. Powered by Claude Haiku on the server. 5 credits.
- **Stale market filtering** — pulse and signals automatically exclude markets past their close time so no expired data surfaces as actionable.
- **Data freshness tracking** — pulse response includes `meta.data_freshness` so you always know how old the underlying scanner data is.

## What's new in v1.4.1

- **Kalshi trading** — `KalshiTrader` with market/limit orders on YES and NO, cancel, positions, balance. RSA key pair auth, non-custodial.
- **Price history endpoint** — `GET /v1/markets/:venue/:id/history` returns rolling ~1h of 60-second price snapshots with computed 5m/15m/1h moves.
- **Market index enriched** — search results now include `end_date`, `spread_cents`, and `liquidity` on every market.
- **Polymarket signed-order relay** — `POST /v1/trade/submit` for agents that sign locally and route through Veynor for builder attribution.
- **Per-user credential storage** — Kalshi keys stored AES-256-GCM encrypted per Veynor API key. Each user trades their own account.

---

## Links

- [Register for an API key](https://veynor.xyz/agents)
- [MCP server](https://mcp.veynor.xyz) — connect directly from Claude Desktop or Cursor
- [Web app](https://veynor.xyz) — whale feed, signals, trade interface
