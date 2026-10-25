# Strategy lab results (run 2026-10-25)

All tests include trading costs, use only closed bars for decisions, count a bar
that hits both stop and target as a loss, and pool several markets. The engine
was checked with random entries: 7,660 trades, zero costs, 50% won, average
0.00R. Costs alone turn that into roughly -0.1R to -0.3R on small intraday
ranges.

Markets for the intraday tests: gold futures, EUR/USD, GBP/USD, USD/JPY,
AUD/USD, S&P 500 futures, Nasdaq futures.

## Intraday, 5-minute bars, Aug 16 - Oct 23 2026 (about 48 sessions)

| strategy | trades | win | avg | max drawdown |
|---|---|---|---|---|
| ORB 8:30 ET, 15 min range, 1R | 378 | 43% | -0.25R | 95R |
| ORB 8:30 ET, 30 min range, 1R | 375 | 47% | -0.11R | 41R |
| ORB 8:30 ET, 30 min, 1R, with daily trend only | 135 | 53% | -0.03R | 12R |
| ORB 8:30 ET, 30 min, 0.5R, with daily trend only | 135 | 62% | -0.12R | 17R |
| ORB 9:30 ET, 15 min range, 1R | 377 | 44% | -0.22R | 89R |
| Yesterday's high/low sweep fade, 1R | 231 | 45% | -0.40R | 99R |
| Yesterday's high/low breakout, 2R | 255 | 40% | -0.12R | 39R |
| ICT 4-step model (sweep, CISD, iFVG), 2R | 317 | 34% | -0.19R | 73R |
| ICT model, target = opposite liquidity | 310 | 28% | -0.11R | 65R |

Gold alone: ORB 8:30 (1R) +0.04R and the ICT model (2R) +0.13R, on only 47 and
37 trades. That is within luck (one standard error is about 0.2R), so neither
is proven.

## Support/resistance on 1-hour bars, June 2024 - Oct 2026

| strategy | trades | win | avg |
|---|---|---|---|
| Yesterday's high/low sweep fade, 1R | 2,438 | 46% | -0.19R |
| Yesterday's high/low breakout, 2R | 2,785 | 44% | -0.08R |

## Daily RSI(2) pullback, 2005 - 2026 (the one that held up)

Buy at the close when the close is above the 200-day average and RSI(2) is
under 10 (or 5); sell at the close when the close is above the 5-day average.
No stop. Cost 0.05% a trade.

| market | trades | win | avg trade | worst trade | 2005-15 / 2016-26 avg |
|---|---|---|---|---|---|
| SPY | 177 | 72% | +0.40% | -10.2% | +0.28% / +0.51% |
| QQQ | 190 | 67% | +0.43% | -8.1% | +0.38% / +0.48% |
| IWM | 162 | 69% | +0.27% | -13.3% | +0.33% / +0.20% |
| DIA | 187 | 72% | +0.24% | -9.5% | +0.20% / +0.27% |
| GLD | 140 | 73% | +0.35% | -10.2% | +0.32% / +0.37% |

As one account split over the five (no leverage):

| version | trades | win | per year | max drawdown | time in market |
|---|---|---|---|---|---|
| RSI(2) < 10 | 856 | 71% | 2.7% | 12% | 12% |
| RSI(2) < 5 | 454 | 76% | 2.0% | 11% | 6% |
| Buy and hold SPY (price only) | - | - | 8.8% | 56% | 100% |

## Re-run

    python3 run.py        # intraday table
    python3 run2.py       # engine check, filters, gold only, RSI(2) per market
    python3 portfolio.py  # RSI(2) as one account
