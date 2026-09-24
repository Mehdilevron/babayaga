# BabaYaga OS — agent instructions

**Read `MISSION.md` first.** It is the project's permanent memory: the owner's
standing configuration ($2,000 capital, $150 latching hard stop), what is
proven vs unproven, and the iron rules. Do not weaken the safety guards, do
not claim a guaranteed-win strategy exists, and never judge a strategy by the
synthetic simulator — only by out-of-sample results on real data
(`scripts/research.py`) followed by demo tracking.

Practical notes:
- Pure stdlib core; `pytest` for tests (`python3 -m pytest -q`). Keep it green.
- Dashboard: `python3 -m babayaga.dashboard` (paper sim only; `--realistic`,
  `--strategy`, `--max-loss`, random seed per run).
- Real-data pipeline: `scripts/fetch_history.py` → `scripts/research.py` →
  `babayaga.backtest`.
- Live/demo trading: `examples/run_exness.py` on a Windows VPS via MetaTrader 5
  (see `docs/exness-vps.md`). `CONFIRM_LIVE` is typed by the owner only.
