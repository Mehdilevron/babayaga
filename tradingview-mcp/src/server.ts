import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import open from "open";
import { resolveProvider, PROVIDER_IDS, type ProviderId } from "./providers/index.js";
import { TIMEFRAMES, type Timeframe } from "./providers/types.js";
import { chartState, broadcast, broadcastSnapshot, type Shape } from "./state.js";
import { startWebServer } from "./web/server.js";

const DEFAULT_CANDLE_LIMIT = 300;

const timeframeSchema = z.enum(TIMEFRAMES as [Timeframe, ...Timeframe[]]);
const providerSchema = z.enum([...PROVIDER_IDS] as [ProviderId, ...ProviderId[]]);

async function refreshChart(limit = DEFAULT_CANDLE_LIMIT) {
  const provider = resolveProvider(chartState.symbol, chartState.providerId);
  chartState.providerId = provider.id as ProviderId;
  chartState.candles = await provider.getOhlcv(chartState.symbol, chartState.timeframe, limit);
  broadcastSnapshot();
}

const server = new McpServer({ name: "tradingview-mcp", version: "0.1.0" });

server.tool(
  "chart_set_symbol",
  "Set the symbol shown on the chart and used by data tools. Auto-detects crypto (e.g. BTCUSDT) vs " +
    "stocks/forex (requires TWELVE_DATA_API_KEY) unless provider is given explicitly. Refetches and " +
    "redraws the chart immediately.",
  {
    symbol: z.string().describe('Ticker/pair, e.g. "BTCUSDT", "AAPL", "EUR/USD"'),
    provider: providerSchema.optional().describe("Force a specific data provider instead of auto-detecting"),
  },
  async ({ symbol, provider }) => {
    chartState.symbol = symbol;
    if (provider) chartState.providerId = provider;
    else chartState.providerId = resolveProvider(symbol).id as ProviderId;
    await refreshChart();
    const latest = chartState.candles.at(-1);
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ symbol: chartState.symbol, timeframe: chartState.timeframe, providerId: chartState.providerId, latestCandle: latest ?? null }),
        },
      ],
    };
  },
);

server.tool(
  "chart_set_timeframe",
  "Change the chart's timeframe and refetch OHLCV data for the current symbol.",
  { timeframe: timeframeSchema },
  async ({ timeframe }) => {
    chartState.timeframe = timeframe;
    await refreshChart();
    const latest = chartState.candles.at(-1);
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ symbol: chartState.symbol, timeframe: chartState.timeframe, latestCandle: latest ?? null }),
        },
      ],
    };
  },
);

server.tool(
  "chart_get_state",
  "Get the chart's current symbol, timeframe, provider, and all drawn shapes.",
  {},
  async () => ({
    content: [
      {
        type: "text",
        text: JSON.stringify({
          symbol: chartState.symbol,
          timeframe: chartState.timeframe,
          providerId: chartState.providerId,
          candleCount: chartState.candles.length,
          shapes: Array.from(chartState.shapes.values()),
        }),
      },
    ],
  }),
);

server.tool(
  "data_get_ohlcv",
  "Fetch OHLCV candles for the current chart symbol/timeframe (or override either) and update the chart.",
  {
    symbol: z.string().optional().describe("Override the current symbol for this fetch"),
    timeframe: timeframeSchema.optional().describe("Override the current timeframe for this fetch"),
    limit: z.number().int().min(1).max(1000).default(DEFAULT_CANDLE_LIMIT).describe("Number of candles to fetch"),
  },
  async ({ symbol, timeframe, limit }) => {
    if (symbol) {
      chartState.symbol = symbol;
      chartState.providerId = resolveProvider(symbol).id as ProviderId;
    }
    if (timeframe) chartState.timeframe = timeframe;
    await refreshChart(limit);
    return {
      content: [{ type: "text", text: JSON.stringify(chartState.candles) }],
    };
  },
);

server.tool(
  "quote_get",
  "Get the latest price for a symbol (defaults to the current chart symbol). Does not change the chart.",
  {
    symbol: z.string().optional(),
    provider: providerSchema.optional(),
  },
  async ({ symbol, provider }) => {
    const targetSymbol = symbol ?? chartState.symbol;
    const resolved = resolveProvider(targetSymbol, provider);
    const quote = await resolved.getQuote(targetSymbol);
    return { content: [{ type: "text", text: JSON.stringify(quote) }] };
  },
);

server.tool(
  "draw_shape",
  "Draw a shape on the chart: a horizontal price line (e.g. a target or key level) or a rectangle " +
    "spanning a price range (e.g. a fair value gap / supply-demand zone). Color accepts any CSS color " +
    'string (e.g. "red", "#22c55e"). Returns the shape id for later removal.',
  {
    type: z.enum(["line", "rectangle"]),
    color: z.string().default("#3b82f6").describe('CSS color, e.g. "red", "green", "gray", "#3b82f6"'),
    label: z.string().optional(),
    price: z.number().optional().describe("Required when type is 'line': the price level"),
    priceHigh: z.number().optional().describe("Required when type is 'rectangle': the top of the zone"),
    priceLow: z.number().optional().describe("Required when type is 'rectangle': the bottom of the zone"),
    fromTime: z.number().int().optional().describe("Rectangle only, unix seconds. Omit to start at the earliest loaded candle."),
    toTime: z.number().int().optional().describe("Rectangle only, unix seconds. Omit to extend to the chart's right edge."),
  },
  async ({ type, color, label, price, priceHigh, priceLow, fromTime, toTime }) => {
    const id = randomUUID();
    let shape: Shape;
    if (type === "line") {
      if (price === undefined) throw new Error("price is required when type is 'line'");
      shape = { id, type: "line", color, label, price };
    } else {
      if (priceHigh === undefined || priceLow === undefined) {
        throw new Error("priceHigh and priceLow are required when type is 'rectangle'");
      }
      shape = { id, type: "rectangle", color, label, priceHigh, priceLow, fromTime, toTime };
    }
    chartState.shapes.set(id, shape);
    broadcast({ type: "shape:add", shape });
    return { content: [{ type: "text", text: JSON.stringify({ id }) }] };
  },
);

server.tool(
  "chart_clear_shapes",
  "Remove shapes from the chart. Omit ids to clear all shapes.",
  { ids: z.array(z.string()).optional() },
  async ({ ids }) => {
    if (!ids || ids.length === 0) {
      chartState.shapes.clear();
      broadcast({ type: "shapes:clear" });
    } else {
      for (const id of ids) {
        chartState.shapes.delete(id);
        broadcast({ type: "shape:remove", id });
      }
    }
    return { content: [{ type: "text", text: JSON.stringify({ remaining: chartState.shapes.size }) }] };
  },
);

async function main() {
  const port = Number(process.env.PORT ?? 0);
  const actualPort = await startWebServer(port);
  const chartUrl = `http://127.0.0.1:${actualPort}`;
  console.error(`[tradingview-mcp] chart UI at ${chartUrl}`);

  await refreshChart().catch((err) => {
    console.error(`[tradingview-mcp] initial chart load failed: ${(err as Error).message}`);
  });

  if (process.env.TRADINGVIEW_MCP_NO_OPEN !== "1") {
    open(chartUrl).catch((err) => {
      console.error(`[tradingview-mcp] could not auto-open browser: ${(err as Error).message}`);
    });
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
