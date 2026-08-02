import { BinanceProvider } from "./binance.js";
import { TwelveDataProvider } from "./twelvedata.js";
import type { MarketDataProvider } from "./types.js";

export const PROVIDER_IDS = ["binance", "twelvedata"] as const;
export type ProviderId = (typeof PROVIDER_IDS)[number];

const binance = new BinanceProvider();
const twelveDataApiKey = process.env.TWELVE_DATA_API_KEY;
const twelveData = twelveDataApiKey ? new TwelveDataProvider(twelveDataApiKey) : null;

// Crypto pairs on Binance are written as a base+quote concatenation with no
// separator (e.g. BTCUSDT), which is how we distinguish them from stock
// tickers and forex pairs when no provider is specified explicitly.
const CRYPTO_QUOTE_ASSETS = ["USDT", "USDC", "BUSD", "FDUSD", "BTC", "ETH", "BNB"];

function looksLikeCryptoPair(symbol: string): boolean {
  const upper = symbol.toUpperCase();
  return CRYPTO_QUOTE_ASSETS.some((quote) => upper.endsWith(quote) && upper.length > quote.length);
}

export function resolveProvider(symbol: string, requested?: ProviderId): MarketDataProvider {
  if (requested === "binance") return binance;
  if (requested === "twelvedata") {
    if (!twelveData) {
      throw new Error("TWELVE_DATA_API_KEY is not set; cannot use the twelvedata provider for stocks/forex.");
    }
    return twelveData;
  }
  if (looksLikeCryptoPair(symbol)) return binance;
  if (twelveData) return twelveData;
  throw new Error(
    `Could not auto-detect a data provider for symbol "${symbol}". It doesn't look like a crypto pair ` +
      `(e.g. BTCUSDT), and TWELVE_DATA_API_KEY is not set for stocks/forex. Set that env var, or pass ` +
      `provider: "binance" | "twelvedata" explicitly.`,
  );
}
