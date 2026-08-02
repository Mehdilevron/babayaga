export type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d";

export const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

export interface Candle {
  time: number; // unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Quote {
  symbol: string;
  price: number;
  timestamp: number; // unix seconds
}

export interface MarketDataProvider {
  readonly id: string;
  getOhlcv(symbol: string, timeframe: Timeframe, limit: number): Promise<Candle[]>;
  getQuote(symbol: string): Promise<Quote>;
}
