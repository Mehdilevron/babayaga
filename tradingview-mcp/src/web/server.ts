import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer, WebSocket } from "ws";
import { chartState, setBroadcaster } from "../state.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, "public");

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
};

const clients = new Set<WebSocket>();

function snapshotMessage() {
  return {
    type: "snapshot" as const,
    symbol: chartState.symbol,
    timeframe: chartState.timeframe,
    candles: chartState.candles,
    shapes: Array.from(chartState.shapes.values()),
  };
}

export function startWebServer(port: number): Promise<number> {
  const server = createServer((req, res) => {
    void (async () => {
      const requestedPath = req.url === "/" ? "/index.html" : (req.url ?? "/index.html");
      const filePath = path.join(PUBLIC_DIR, path.normalize(requestedPath));
      if (!filePath.startsWith(PUBLIC_DIR)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      try {
        const data = await readFile(filePath);
        const ext = path.extname(filePath);
        res.writeHead(200, { "Content-Type": MIME[ext] ?? "application/octet-stream" });
        res.end(data);
      } catch {
        res.writeHead(404);
        res.end("Not found");
      }
    })();
  });

  const wss = new WebSocketServer({ server });
  wss.on("connection", (ws) => {
    clients.add(ws);
    ws.send(JSON.stringify(snapshotMessage()));
    ws.on("close", () => clients.delete(ws));
  });

  setBroadcaster((message) => {
    const payload = JSON.stringify(message);
    for (const ws of clients) {
      if (ws.readyState === WebSocket.OPEN) ws.send(payload);
    }
  });

  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      const addr = server.address();
      resolve(typeof addr === "object" && addr ? addr.port : port);
    });
  });
}
