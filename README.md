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

Search markets by keyword across both venues.

```python
results = client.search("fed rate", venue="all", limit=10)
# Returns: { summary, polymarket: [...], kalshi: [...], meta }
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

## Use in a Jupyter notebook

```python
import veynor, pandas as pd

client = veynor.Client()
data   = client.whales(min_notional=15_000, limit=50)
df     = pd.DataFrame(data["trades"])
df[["market", "side", "notional", "platform"]].sort_values("notional", ascending=False)
```

---

## Links

- [Register for an API key](https://veynor.xyz/agents)
- [MCP server](https://mcp.veynor.xyz) — connect directly from Claude Desktop or OpenClaw
- [Web app](https://veynor.xyz) — whale feed, smart money signals, trade interface
