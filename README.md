# veynor

Python client for the [Veynor](https://veynor.xyz) prediction market intelligence API.

Cross-venue data across Kalshi and Polymarket: whale trades, smart money signals, arb opportunities, and market search — in a single `import`.

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

Search markets by keyword across both venues. Results include current YES price and 24-hour volume.

```python
results = client.search("fed rate", venue="all", limit=10)
# Returns: { summary, polymarket: [...], kalshi: [...], meta }
# Each market includes: title, yes_price (0–1), volume_24h, url, platform
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

### `client.usage()`

Check your credit balance. Always free.

```python
u = client.usage()
print(u["tier"], u["credits_remaining"])
```

---

## Credit costs

| Method          | Credits |
|-----------------|---------|
| `whales()`      | 2       |
| `top_markets()` | 1       |
| `search()`      | 1       |
| `market()`      | 1       |
| `signals()`     | 3       |
| `usage()`       | 0       |

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
  "https://api.veynor.xyz/v1/whale-trades?min_notional=10000&venue=all&limit=10"

# Top markets by 24h volume
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/top?venue=all&limit=10"

# Price movers (biggest moves in last hour)
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/signals?signal_type=price_movers&limit=10"

# Arb opportunities across venues
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/signals?signal_type=arb_opportunities"

# Search markets
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/search?q=fed+rate"

# Specific market (Polymarket condition ID or Kalshi ticker)
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/polymarket/0x1234..."
curl -s -H "X-API-Key: vey_sk_..." \
  "https://api.veynor.xyz/v1/markets/kalshi/KXNBA-25-LAL"

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
| `GET /v1/signals` | `signal_type`, `limit` | 3 |
| `GET /v1/usage` | — | 0 |

`signal_type` options: `price_movers`, `wide_spreads`, `arb_opportunities`, `all`

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

Add `--json` before the query for machine-readable output (useful for piping):

```bash
veynor search --json "bitcoin" | python3 -m json.tool
veynor search --json "nba" | jq '.results[].yes_price'
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

## Polymarket order execution (optional)

The `trade` commands let you place market orders on Polymarket directly from the CLI. All signing happens locally. Your private key is never sent to Veynor's servers.

### 1. Install trade dependencies

```bash
pip install veynor[trade]
```

This adds `py-clob-client` and `eth-account` on top of the base install.

### 2. Get your private key from Polymarket

Go to [polymarket.com](https://polymarket.com), open your profile settings, and find the **Private Key** section. The steps are the same regardless of how you signed up.

**If you signed up with email (Magic wallet):**
Polymarket walks you through exporting your key via Magic.link. Settings > Private Key > sign into Magic.link > copy the key shown.

**If you connected MetaMask or another external wallet:**
Export the key directly from your wallet app. MetaMask: Settings > Accounts > Account details > Show private key.

Once you have it, store it in your shell environment. Never in code, never committed to git:

```bash
export POLYMARKET_PRIVATE_KEY=0x...
```

Add that line to `~/.zshrc` or `~/.bash_profile` to persist it across sessions.

> The CLOB client derives your API credentials from the key locally on each run. Nothing is stored or sent to Veynor.

### 3. Trade

```bash
# Check your USDC balance on Polygon
veynor trade balance

# List open positions
veynor trade positions

# Buy $50 of YES shares on a market
# TOKEN_ID is the outcome token address — find it with:
#   veynor market polymarket <condition_id> --json
veynor trade buy 0xabc123... --amount 50

# Sell 100 shares
veynor trade sell 0xabc123... --shares 100

# Mirror the latest whale trade (1% of their notional by default)
veynor trade copy

# Copy a specific whale size, custom amount
veynor trade copy --min-notional 50000 --amount 200 --yes
```

All trade commands prompt for confirmation before executing. Pass `--yes` to skip.

### Finding token IDs

Each Polymarket outcome (YES/NO) has a token ID (a Polygon address). Get it from the market detail:

```bash
veynor market polymarket <condition_id> --json | python3 -m json.tool
```

Or from the Polymarket UI: open a market, inspect the URL or the API response.

### Errors and troubleshooting

| Error | Fix |
|-------|-----|
| `No private key found` | Set `POLYMARKET_PRIVATE_KEY` in your shell |
| `Failed to derive API credentials` | Check that your key is a valid hex private key starting with `0x` |
| `Trading requires extra packages` | Run `pip install veynor[trade]` |
| Order status `unmatched` | Insufficient liquidity at market price — try a smaller amount |

---

## Links

- [Register for an API key](https://veynor.xyz/agents)
- [MCP server](https://mcp.veynor.xyz) — connect directly from Claude Desktop or Cursor
- [Web app](https://veynor.xyz) — whale feed, smart money signals, trade interface
