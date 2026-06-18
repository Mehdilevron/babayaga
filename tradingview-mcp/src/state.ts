import type { Candle, Timeframe } from "./providers/types.js";
import type { ProviderId } from "./providers/index.js";

export interface ShapeBase {
  id: string;
  color: string;
  label?: string;
}

export interface RectangleShape extends ShapeBase {
  type: "rectangle";
  priceHigh: number;
  priceLow: number;
  fromTime?: number; // unix seconds; omitted = earliest loaded candle
  toTime?: number; // unix seconds; omitted = extends to the right edge of the chart
}

export interface LineShape extends ShapeBase {
  type: "line";
  price: number;
}

export type Shape = RectangleShape | LineShape;

export interface ChartState {
  symbol: string;
  timeframe: Timeframe;
  providerId: ProviderId;
  candles: Candle[];
  shapes: Map<string, Shape>;
}

export const chartState: ChartState = {
  symbol: "BTCUSDT",
  timeframe: "1h",
  providerId: "binance",
  candles: [],
  shapes: new Map(),
};

export type BroadcastMessage =
  | { type: "snapshot"; symbol: string; timeframe: Timeframe; candles: Candle[]; shapes: Shape[] }
  | { type: "shape:add"; shape: Shape }
  | { type: "shape:remove"; id: string }
  | { type: "shapes:clear" };

type Broadcaster = (message: BroadcastMessage) => void;

let broadcaster: Broadcaster = () => {};

export function setBroadcaster(fn: Broadcaster): void {
  broadcaster = fn;
}

export function broadcastSnapshot(): void {
  broadcaster({
    type: "snapshot",
    symbol: chartState.symbol,
    timeframe: chartState.timeframe,
    candles: chartState.candles,
    shapes: Array.from(chartState.shapes.values()),
  });
}

export function broadcast(message: BroadcastMessage): void {
  broadcaster(message);
}
