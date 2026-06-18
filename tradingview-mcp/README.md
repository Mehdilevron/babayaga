# tradingview-mcp

An MCP server for chart analysis. It exposes tools to read OHLCV candles and
quotes for crypto/stocks/forex, and to draw shapes (price lines, zones) on a
chart — backed by a self-hosted page using TradingView's open-source
[Lightweight Charts](https://github.com/tradingview/lightweight-charts)
library, rendered locally in your browser.

This does **not** automate the tradingview.com website. It hosts its own
chart fed by real market data, which gives full programmatic control (no
canvas-scraping, no fragile mouse-coordinate automation) at the cost of not
being the literal tradingview.com UI/your saved layouts.

## Data sources

- **Crypto** — Binance's public REST API. No API key needed. Symbols like
  `BTCUSDT`, `ETHUSDT` are auto-detected by their quote-asset suffix.
- **Stocks / forex** — [Twelve Data](https://twelvedata.com/). Requires an
  API key (free tier available) in the `TWELVE_DATA_API_KEY` env var.
  Symbols like `AAPL` or `EUR/USD` are routed here automatically once the
  key is set.

You can also force a provider explicitly via the `provider` argument on the
relevant tools, instead of relying on auto-detection.

## Setup

```bash
cd tradingview-mcp
npm install
npm run build
```

Try it standalone first (opens the chart in your browser, then waits for an
MCP client on stdio — press Ctrl+C to stop):

```bash
npm start
```

Optional environment variables:

| Variable | Purpose |
| --- | --- |
| `TWELVE_DATA_API_KEY` | Enables the stocks/forex provider |
| `PORT` | Fixed port for the chart's local web server (default: random free port) |
| `TRADINGVIEW_MCP_NO_OPEN=1` | Don't auto-open a browser tab on startup |

## Adding to Claude Code

```bash
claude mcp add tradingview -- node /absolute/path/to/tradingview-mcp/dist/server.js
```

Or in `.mcp.json`:

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["/absolute/path/to/tradingview-mcp/dist/server.js"],
      "env": {
        "TWELVE_DATA_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Tools

| Tool | Description |
| --- | --- |
| `chart_set_symbol` | Set the symbol; auto-detects provider unless one is given. Refetches and redraws. |
| `chart_set_timeframe` | Change timeframe (`1m`,`5m`,`15m`,`30m`,`1h`,`4h`,`1d`); refetches and redraws. |
| `chart_get_state` | Current symbol, timeframe, provider, and all drawn shapes. |
| `data_get_ohlcv` | Fetch OHLCV candles for the current (or overridden) symbol/timeframe. |
| `quote_get` | Latest price for a symbol; doesn't touch the chart. |
| `draw_shape` | Draw a `line` (horizontal price level) or `rectangle` (price zone) on the chart. |
| `chart_clear_shapes` | Remove specific shapes by id, or all of them. |

`draw_shape` is intentionally generic — colors are plain CSS color strings
with no built-in trading-strategy semantics. If you want red/green/gray for
bearish/bullish/mitigated zones, pick those colors yourself when calling the
tool.

## Automated alerts

`scripts/check_signal.sh` runs a one-shot top-down ICT/Smart Money Concepts
analysis (4h → 1h → 30m → 15m → 5m/1m) via the Claude Code CLI against this
server's tools, and sends an [ntfy.sh](https://ntfy.sh) push notification
when a BUY/SELL signal with confirmed lower-timeframe entry is found. It's
meant to run periodically (cron/launchd/Task Scheduler) on a machine that
has the `claude` CLI and this MCP server configured.

This performs technical chart-pattern analysis only — it does not place
trades and is not financial advice. Verify any signal yourself.

### One-time setup

1. Register a *separate* MCP server entry for background use. Use `-e` (not
   a bare shell prefix — that only affects the `mcp add` command itself, not
   future spawns) to persist `TRADINGVIEW_MCP_NO_OPEN=1` so each run doesn't
   pop a browser tab, and a fixed `PORT` so you can leave one browser tab
   open and watch it update on every run instead of getting a fresh random
   port each time:

   ```bash
   claude mcp add tradingview-bg -e TRADINGVIEW_MCP_NO_OPEN=1 -e PORT=4488 -- node /absolute/path/to/tradingview-mcp/dist/server.js
   ```

   Then open `http://127.0.0.1:4488` once and leave the tab open. `chart.js`
   reconnects automatically and re-fetches a full snapshot (candles + any
   drawn shapes) on every reconnect, so that tab will show each run's key
   level / liquidity magnet / inversion FVG drawings as the background
   server process is started and exits for each cron invocation.

2. Pick your own ntfy.sh topic name — don't reuse one from documentation,
   since anyone who knows a public topic name can read messages sent to it
   — and subscribe to it in the [ntfy app](https://ntfy.sh/app) or via
   `ntfy subscribe <topic>`.

3. Run it manually once to confirm it works:

   ```bash
   export NTFY_TOPIC=my-own-random-slug
   ./scripts/check_signal.sh
   ```

   Check `scripts/signal_check.log` for the result, and the browser tab from
   step 1 for the drawn shapes.

4. Schedule it, e.g. every 15 minutes via cron:

   ```
   */15 * * * * NTFY_TOPIC=my-own-random-slug /absolute/path/to/tradingview-mcp/scripts/check_signal.sh
   ```

### Environment variables

| Variable | Purpose |
| --- | --- |
| `NTFY_TOPIC` | **Required.** Your own ntfy.sh topic name. |
| `SYMBOL` | Symbol to analyze (default: `BTCUSDT`). |
| `MCP_SERVER_NAME` | Name the background MCP server was registered under (default: `tradingview-bg`). |
| `CLAUDE_BIN` | Path to the `claude` CLI (default: `claude`). |
| `LOG_FILE` | Path to the log file (default: `scripts/signal_check.log` next to the script). |

The script only finalizes a BUY/SELL signal once a 15m liquidity sweep, an
active (non-mitigated) inversion FVG, and a lower-timeframe (5m or 1m) entry
trigger all confirm it — otherwise it logs `signal=NONE` and exits without
notifying.

## Architecture

```
src/
  server.ts          MCP server entrypoint (stdio transport) + tool definitions
  state.ts           In-memory chart state (symbol/timeframe/candles/shapes) + WS broadcast
  providers/
    types.ts         Candle/Quote/MarketDataProvider interfaces
    binance.ts        Crypto provider (no API key)
    twelvedata.ts      Stocks/forex provider (needs TWELVE_DATA_API_KEY)
    index.ts           Provider auto-detection
  web/
    server.ts          Local HTTP + WebSocket server
    public/
      index.html        Chart page
      chart.js          Lightweight Charts rendering + shape overlays
```

Tool calls fetch data directly from the provider and push it to any
connected browser tab(s) over WebSocket — the server, not the browser, is
the source of truth for chart state.
