"""A live web dashboard that subscribes to the OS event bus.

Runs a dependency-free web server (stdlib ``http.server``) that streams the
trading OS's event stream to the browser over Server-Sent Events (SSE). The
dashboard is just another *observer* on the bus — it subscribes to the same
topics agents publish to and forwards them to connected browsers. This is a
concrete demonstration that the "live coordination" layer is real and taps into
the running system without touching any trading logic.

    python -m babayaga.dashboard --port 8765 --steps 600 --interval 0.05

Then open http://127.0.0.1:8765 to watch equity, positions, agent signals and
fills update in real time. Paper trading only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import queue
import threading
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from babayaga.config import Config
from babayaga.kernel.events import Topic
from babayaga.os import TradingOS

log = logging.getLogger("babayaga.dashboard")

_STREAM_TOPICS = (Topic.TICK, Topic.SIGNAL, Topic.DECISION, Topic.FILL, Topic.ACCOUNT)


def _to_payload(topic: Topic, message: Any) -> dict:
    """Convert an event-bus message into a JSON-serialisable dict."""

    def clean(v: Any) -> Any:
        if isinstance(v, Enum):
            return v.value
        if is_dataclass(v) and not isinstance(v, type):
            return {k: clean(val) for k, val in asdict(v).items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, dict):
            return {k: clean(val) for k, val in v.items()}
        return v

    body = clean(message)
    # Drop the heavy nested signal list from decisions for the wire.
    if isinstance(body, dict):
        body.pop("contributing", None)
    return {"topic": topic.value, "data": body}


class _Broadcaster:
    """Fans events out to every connected SSE client via thread-safe queues."""

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self.history: list[dict] = []  # small replay buffer for late joiners

    def register(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._clients.add(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, event: dict) -> None:
        if event["topic"] == Topic.ACCOUNT.value:
            self.history.append(event)
            self.history[:] = self.history[-500:]
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow client; drop rather than block the loop


class _Handler(BaseHTTPRequestHandler):
    broadcaster: _Broadcaster = None  # type: ignore[assignment]

    def log_message(self, *args: Any) -> None:  # silence default logging
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/":
            self._serve_html()
        elif self.path.split("?")[0] == "/events":
            self._serve_events()
        else:
            self.send_error(404)

    def _serve_html(self) -> None:
        body = _INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.broadcaster.register()
        try:
            # Replay recent account history so a late joiner sees a curve.
            for event in list(self.broadcaster.history):
                self._write_event(event)
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")  # comment ping
                    self.wfile.flush()
                    continue
                self._write_event(event)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.broadcaster.unregister(q)

    def _write_event(self, event: dict) -> None:
        payload = json.dumps(event, separators=(",", ":"))
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


class Dashboard:
    """Attaches to a :class:`TradingOS` and serves a live view of its bus."""

    def __init__(self, os_: TradingOS, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.os = os_
        self.host = host
        self.port = port
        self.broadcaster = _Broadcaster()
        for topic in _STREAM_TOPICS:
            self.os.on(topic, self._make_forwarder(topic))
        handler = type("BoundHandler", (_Handler,), {"broadcaster": self.broadcaster})
        # If the requested port is already in use (e.g. a previous dashboard is
        # still running), walk forward to the next free port instead of dying
        # with "Address already in use". self.port is updated to the real one.
        last_err: OSError | None = None
        for candidate in range(port, port + 20):
            try:
                self._server = ThreadingHTTPServer((host, candidate), handler)
                self.port = candidate
                break
            except OSError as exc:  # port busy -> try the next one
                last_err = exc
        else:
            raise OSError(
                f"no free port in {port}..{port + 19} on {host}. "
                f"Close the other dashboard, or pass --port. ({last_err})"
            )
        self._server.daemon_threads = True

    def _make_forwarder(self, topic: Topic):
        def forward(message: Any) -> None:
            self.broadcaster.publish(_to_payload(topic, message))
        return forward

    def serve_forever_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        return t

    def shutdown(self) -> None:
        self._server.shutdown()


_INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BabaYaga OS — Live</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
         background:#0b0f14; color:#cdd6e4; }
  header { padding:14px 20px; border-bottom:1px solid #1c2430;
           display:flex; align-items:baseline; gap:14px; }
  header h1 { margin:0; font-size:16px; color:#e8eef7; letter-spacing:.5px; }
  header .badge { font-size:11px; padding:2px 8px; border-radius:10px;
                  background:#182231; color:#7fd1b0; }
  .wrap { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:16px; }
  @media (max-width:820px){ .wrap{ grid-template-columns:1fr; } }
  .card { background:#0f151d; border:1px solid #1c2430; border-radius:10px; padding:14px; }
  .card h2 { margin:0 0 10px; font-size:12px; text-transform:uppercase;
             letter-spacing:1px; color:#6b7a90; }
  .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
  .stat { background:#0b1119; border:1px solid #1a2330; border-radius:8px; padding:10px; }
  .stat .k { font-size:10px; color:#6b7a90; text-transform:uppercase; }
  .stat .v { font-size:18px; color:#e8eef7; margin-top:3px; }
  .pos { color:#7fd1b0; } .neg { color:#f2889b; }
  canvas { width:100%; height:180px; display:block; }
  .log { height:280px; overflow:auto; font-size:12px; }
  .log div { padding:2px 0; border-bottom:1px solid #141c26; white-space:nowrap;
             overflow:hidden; text-overflow:ellipsis; }
  .tick { color:#5a6b82; } .sig { color:#8ab4ff; } .dec { color:#e6c07b; }
  .fill { color:#7fd1b0; } .flat { color:#6b7a90; }
  footer { padding:10px 20px; color:#5a6b82; font-size:11px;
           border-top:1px solid #1c2430; }
</style></head>
<body>
<header>
  <h1>🐺 BabaYaga OS</h1>
  <span class="badge" id="conn">connecting…</span>
  <span class="badge" style="background:#241a24;color:#e6a0c0">PAPER — simulated</span>
  <span class="badge" id="halt" style="display:none;background:#3a1420;color:#ff8f9f">⛔ TRADING HALTED — loss limit / drawdown breaker</span>
</header>
<div class="wrap">
  <div class="card">
    <h2>Account</h2>
    <div class="stats">
      <div class="stat"><div class="k">Equity</div><div class="v" id="equity">—</div></div>
      <div class="stat"><div class="k">Realized P&L</div><div class="v" id="realized">—</div></div>
      <div class="stat"><div class="k">Unrealized</div><div class="v" id="unreal">—</div></div>
      <div class="stat"><div class="k">Open pos.</div><div class="v" id="open">—</div></div>
      <div class="stat"><div class="k">Return</div><div class="v" id="ret">—</div></div>
      <div class="stat"><div class="k">Ticks</div><div class="v" id="ticks">0</div></div>
    </div>
    <h2 style="margin-top:14px">Equity curve</h2>
    <canvas id="chart" width="600" height="180"></canvas>
  </div>
  <div class="card">
    <h2>Live event stream (kernel bus)</h2>
    <div class="log" id="log"></div>
  </div>
</div>
<footer>Every line above is a message read off the OS event bus. No real orders are placed.</footer>
<script>
const $ = id => document.getElementById(id);
const fmt = (n,d=2) => Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
let start=null, equity=[], tickCount=0;
const log = $('log');
function addLog(cls, text){
  const d=document.createElement('div'); d.className=cls; d.textContent=text;
  log.prepend(d); while(log.childElementCount>200) log.removeChild(log.lastChild);
}
function drawChart(){
  const c=$('chart'), ctx=c.getContext('2d'); const w=c.width,h=c.height;
  ctx.clearRect(0,0,w,h); if(equity.length<2) return;
  const min=Math.min(...equity), max=Math.max(...equity), rng=(max-min)||1;
  ctx.strokeStyle='#7fd1b0'; ctx.lineWidth=1.5; ctx.beginPath();
  equity.forEach((v,i)=>{ const x=i/(equity.length-1)*w; const y=h-((v-min)/rng)*(h-10)-5;
    i?ctx.lineTo(x,y):ctx.moveTo(x,y); }); ctx.stroke();
  ctx.strokeStyle='#1c2430'; ctx.beginPath();
  const y0=h-((start-min)/rng)*(h-10)-5; ctx.moveTo(0,y0); ctx.lineTo(w,y0); ctx.stroke();
}
const es = new EventSource('/events');
es.onopen = ()=>{ $('conn').textContent='● live'; $('conn').style.color='#7fd1b0'; };
es.onerror = ()=>{ $('conn').textContent='○ disconnected'; $('conn').style.color='#f2889b'; };
es.onmessage = e => {
  const {topic,data} = JSON.parse(e.data);
  if(topic==='account'){
    if(start===null) start=data.equity;
    equity.push(data.equity); if(equity.length>600) equity.shift();
    $('equity').textContent='$'+fmt(data.equity);
    const rp=data.realized_pnl, up=data.unrealized_pnl;
    $('realized').textContent='$'+fmt(rp); $('realized').className='v '+(rp>=0?'pos':'neg');
    $('unreal').textContent='$'+fmt(up); $('unreal').className='v '+(up>=0?'pos':'neg');
    $('open').textContent=data.open_positions;
    const r=(data.equity-start)/start*100;
    $('ret').textContent=fmt(r)+'%'; $('ret').className='v '+(r>=0?'pos':'neg');
    $('halt').style.display = data.halted ? 'inline' : 'none';
    drawChart();
  } else if(topic==='tick'){
    tickCount++; $('ticks').textContent=tickCount;
  } else if(topic==='signal'){
    addLog('sig',`SIGNAL ${data.agent} ${data.symbol} ${data.side.toUpperCase()} (${fmt(data.confidence,2)}) — ${data.rationale}`);
  } else if(topic==='decision'){
    if(data.side!=='flat') addLog('dec',`DECIDE ${data.side.toUpperCase()} ${data.symbol} — ${data.rationale}`);
  } else if(topic==='fill'){
    addLog('fill',`FILL   ${data.side.toUpperCase()} ${fmt(data.size,0)} ${data.symbol} @ ${fmt(data.price,5)} (${data.order_reason})`);
  }
};
</script>
</body></html>"""


def _lan_ips() -> list[str]:
    """Best-effort list of this machine's LAN IPv4 addresses."""
    import socket

    ips: list[str] = []
    # Primary outbound interface (doesn't actually send traffic).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    # Anything else resolvable for the hostname.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def _print_access_banner(host: str, port: int) -> None:
    print(f"BabaYaga dashboard live  (paper, simulated)")
    if host in ("0.0.0.0", "::"):
        print(f"  On this machine : http://127.0.0.1:{port}")
        lan = _lan_ips()
        if lan:
            print("  On your network : " + "  ".join(f"http://{ip}:{port}" for ip in lan))
            print("  (open the network URL from your phone/laptop on the same Wi-Fi)")
        else:
            print("  On your network : http://<this-machine-ip>:" + str(port))
        print("  ⚠  Bound to 0.0.0.0 — reachable by any device on your network. "
              "It's paper-only and read-only, but don't expose it to the public internet.")
    else:
        print(f"  URL             : http://{host}:{port}")
        if host in ("127.0.0.1", "localhost"):
            print("  (local only — pass --host 0.0.0.0 to reach it from other devices)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="babayaga.dashboard", description="BabaYaga live dashboard")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address; use 0.0.0.0 to allow other devices on your network")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--symbol",
        default="EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD",
        help="one or more instruments, comma-separated (the bot scans them all)",
    )
    p.add_argument("--cash", type=float, default=1000.0, help="starting account balance")
    p.add_argument("--steps", type=int, default=0, help="number of bars; 0 = run nonstop (24/7)")
    p.add_argument("--seed", type=int, default=None,
                   help="simulation seed; default = random each run (a fixed seed replays "
                        "the exact same market — and the same result — every time)")
    p.add_argument("--max-loss", type=float, default=150.0, dest="max_loss",
                   help="LATCHING hard stop: lose this much and the bot flattens and stops "
                        "until restarted (0 disables)")
    p.add_argument("--interval", type=float, default=0.08, help="seconds between bars")
    p.add_argument("--memory", default=":memory:",
                   help="SQLite path for persistent memory (e.g. babayaga.sqlite), or :memory:")
    p.add_argument("--max-ticks", type=int, default=100_000, dest="max_ticks",
                   help="cap on retained ticks/signals for nonstop runs; trades are never pruned")
    p.add_argument("--realistic", action="store_true",
                   help="~real-account mode: real spreads + slippage, weak drift, flip cooldown")
    p.add_argument("--strategy", choices=("trend", "meanrev"), default="trend",
                   help="strategy preset; 'meanrev' is the research pick on real daily FX "
                        "(note: this simulator's synthetic drift favors 'trend')")
    p.add_argument("--no-browser", action="store_true", dest="no_browser",
                   help="do not auto-open a web browser at the dashboard URL")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    symbols = tuple(s.strip() for s in args.symbol.split(",") if s.strip())
    if args.seed is None:
        import random as _random

        args.seed = _random.randrange(1_000_000)
        print(f"seed: {args.seed}  (new random market this run; pass --seed {args.seed} to replay it)")
    # Realistic mode makes the simulator behave ~like a real account: realistic
    # per-pair spreads (already default), added slippage, weak trend (drift), and
    # a flip cooldown so every reversal isn't free. Expect a far soberer curve.
    realistic = getattr(args, "realistic", False)
    cfg = Config(
        symbols=symbols,
        starting_cash=args.cash,
        sim_steps=args.steps,
        sim_seed=args.seed,
        sim_interval=args.interval,
        memory_path=args.memory,
        # Bound the firehose so a nonstop, ultra-fast run stays memory-safe.
        # Trades (fills) are never pruned — every trade is remembered.
        memory_max_ticks=args.max_ticks,
        memory_max_signals=args.max_ticks,
        memory_max_decisions=args.max_ticks,
        slippage=0.00003 if realistic else 0.0,
        sim_drift_scale=0.2 if realistic else 1.0,
        flip_cooldown_bars=3 if realistic else 0,
        hard_stop_loss=args.max_loss if args.max_loss > 0 else None,
    )
    if args.max_loss > 0:
        print(f"hard stop: lose ${args.max_loss:.0f} -> flatten everything and halt until restart")
    from babayaga.agents.presets import strategy_preset

    preset_risk, preset_specs = strategy_preset(args.strategy)
    cfg.risk = preset_risk
    if realistic:
        print("REALISTIC MODE: real spreads + slippage, weak drift, flip cooldown. "
              "Closest thing to a real account.")
    print(f"Strategy preset: {args.strategy}"
          + ("  (research pick on real daily FX — note this synthetic sim's drift "
             "favors 'trend', so judge meanrev on real data, not here)"
             if args.strategy == "meanrev" else ""))
    os_ = TradingOS(cfg)
    os_.coordinator.specialists = preset_specs
    dash = Dashboard(os_, host=args.host, port=args.port)
    if dash.port != args.port:
        print(f"Port {args.port} was busy — serving on {dash.port} instead.")
    dash.serve_forever_in_thread()
    _print_access_banner(args.host, dash.port)
    # Auto-open a browser so "the dashboard doesn't open" can't happen. Uses the
    # loopback address even when bound to 0.0.0.0 (that isn't a browsable host).
    if not args.no_browser:
        open_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        url = f"http://{open_host}:{dash.port}"
        try:
            import webbrowser
            if webbrowser.open(url):
                print(f"Opening {url} in your browser…")
            else:
                print(f"Could not auto-open a browser — go to {url} manually.")
        except Exception:
            print(f"Could not auto-open a browser — go to {url} manually.")
    print("Ctrl-C to stop.")
    try:
        asyncio.run(os_.run())
        print("Simulation complete — dashboard still serving final state. Ctrl-C to exit.")
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        dash.shutdown()
        os_.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
