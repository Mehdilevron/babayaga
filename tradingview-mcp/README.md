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
