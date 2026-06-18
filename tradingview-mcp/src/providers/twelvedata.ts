import type { Candle, MarketDataProvider, Quote, Timeframe } from "./types.js";

const BASE_URL = "https://api.twelvedata.com";

const INTERVAL_MAP: Record<Timeframe, string> = {
  "1m": "1min",
  "5m": "5min",
  "15m": "15min",
  "30m": "30min",
  "1h": "1h",
  "4h": "4h",
  "1d": "1day",
};

interface TwelveDataSeriesPoint {
  datetime: string; // "YYYY-MM-DD HH:mm:ss" or "YYYY-MM-DD", always UTC (we request timezone=UTC)
  open: string;
  high: string;
  low: string;
  close: string;
  volume?: string;
}

function parseUtcDateTime(value: string): number {
  const [datePart, timePart = "00:00:00"] = value.split(" ");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute, second] = timePart.split(":").map(Number);
  return Math.floor(Date.UTC(year, month - 1, day, hour, minute, second) / 1000);
}

export class TwelveDataProvider implements MarketDataProvider {
  readonly id = "twelvedata";

  constructor(private readonly apiKey: string) {}

  async getOhlcv(symbol: string, timeframe: Timeframe, limit: number): Promise<Candle[]> {
    const url = `${BASE_URL}/time_series?symbol=${encodeURIComponent(symbol)}&interval=${INTERVAL_MAP[timeframe]}&outputsize=${limit}&timezone=UTC&apikey=${this.apiKey}`;
    const res = await fetch(url);
    const data = (await res.json()) as { status?: string; message?: string; values?: TwelveDataSeriesPoint[] };
    if (!res.ok || data.status === "error") {
      throw new Error(`Twelve Data time_series request failed: ${data.message ?? res.statusText}`);
    }
    const values = data.values ?? [];
    // Twelve Data returns newest-first; chart libraries expect oldest-first.
    return values
      .map((v) => ({
        time: parseUtcDateTime(v.datetime),
        open: Number(v.open),
        high: Number(v.high),
        low: Number(v.low),
        close: Number(v.close),
        volume: Number(v.volume ?? 0),
      }))
      .sort((a, b) => a.time - b.time);
  }

  async getQuote(symbol: string): Promise<Quote> {
    const url = `${BASE_URL}/price?symbol=${encodeURIComponent(symbol)}&apikey=${this.apiKey}`;
    const res = await fetch(url);
    const data = (await res.json()) as { status?: string; message?: string; price?: string };
    if (!res.ok || data.status === "error" || data.price === undefined) {
      throw new Error(`Twelve Data price request failed: ${data.message ?? res.statusText}`);
    }
    return {
      symbol,
      price: Number(data.price),
      timestamp: Math.floor(Date.now() / 1000),
    };
  }
}
