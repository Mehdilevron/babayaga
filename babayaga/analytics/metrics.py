"""Performance metrics computed from an equity curve and trade ledger."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class PerformanceSummary:
    start_equity: float
    end_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    num_trades: int
    win_rate_pct: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "start_equity": round(self.start_equity, 2),
            "end_equity": round(self.end_equity, 2),
            "total_return_pct": round(self.total_return_pct, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "sharpe": round(self.sharpe, 3),
            "num_trades": self.num_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
        }


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _sharpe(equity: Sequence[float]) -> float:
    if len(equity) < 3:
        return 0.0
    rets = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] != 0
    ]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    if std == 0:
        return 0.0
    # Annualised assuming the equity curve is sampled per bar; the constant is a
    # convention, not a claim about calendar time.
    return (mean / std) * (252 ** 0.5)


def performance_summary(
    equity_curve: Sequence[float],
    realized_pnls: Sequence[float] = (),
) -> PerformanceSummary:
    if not equity_curve:
        return PerformanceSummary(0, 0, 0, 0, 0, 0, 0)
    start = equity_curve[0]
    end = equity_curve[-1]
    total_return = ((end - start) / start * 100.0) if start else 0.0
    wins = sum(1 for p in realized_pnls if p > 0)
    win_rate = (wins / len(realized_pnls) * 100.0) if realized_pnls else 0.0
    return PerformanceSummary(
        start_equity=start,
        end_equity=end,
        total_return_pct=total_return,
        max_drawdown_pct=_max_drawdown(equity_curve),
        sharpe=_sharpe(equity_curve),
        num_trades=len(realized_pnls),
        win_rate_pct=win_rate,
    )
