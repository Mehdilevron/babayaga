import type { Candle, MarketDataProvider, Quote, Timeframe } from "./types.js";

const BASE_URL = "https://api.binance.com/api/v3";

type BinanceKline = [
  number, // open time (ms)
  string, // open
  string, // high
  string, // low
  string, // close
  string, // volume
  number, // close time (ms)
  string, // quote asset volume
  number, // number of trades
  string, // taker buy base asset volume
  string, // taker buy quote asset volume
  string, // ignore
];

export class BinanceProvider implements MarketDataProvider {
  readonly id = "binance";

  async getOhlcv(symbol: string, timeframe: Timeframe, limit: number): Promise<Candle[]> {
    const url = `${BASE_URL}/klines?symbol=${encodeURIComponent(symbol.toUpperCase())}&interval=${timeframe}&limit=${limit}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`Binance klines request failed (${res.status}): ${await res.text()}`);
    }
    const raw = (await res.json()) as BinanceKline[];
    return raw.map((k) => ({
      time: Math.floor(k[0] / 1000),
      open: Number(k[1]),
      high: Number(k[2]),
      low: Number(k[3]),
      close: Number(k[4]),
      volume: Number(k[5]),
    }));
  }

  async getQuote(symbol: string): Promise<Quote> {
    const url = `${BASE_URL}/ticker/price?symbol=${encodeURIComponent(symbol.toUpperCase())}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`Binance price request failed (${res.status}): ${await res.text()}`);
    }
    const data = (await res.json()) as { symbol: string; price: string };
    return {
      symbol: data.symbol,
      price: Number(data.price),
      timestamp: Math.floor(Date.now() / 1000),
    };
  }
}
