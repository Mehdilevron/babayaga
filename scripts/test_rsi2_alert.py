import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi2_alert as ra  # noqa: E402


def series(closes, start=datetime.date(2005, 1, 3)):
    return [(start + datetime.timedelta(days=i), c) for i, c in enumerate(closes)]


UP = [100 + i * 0.5 for i in range(250)]  # steady uptrend: far above the 200-day average


class Rule(unittest.TestCase):
    def test_rsi2_all_up_and_down(self):
        self.assertEqual(ra.rsi2([1, 2, 3, 4])[-1], 100.0)
        self.assertEqual(ra.rsi2([4, 3, 2, 1])[-1], 0.0)

    def test_buy_on_sharp_dip_in_uptrend(self):
        x = ra.decide(series(UP + [UP[-1] - 1]), UP[-1] - 3)  # two down days
        self.assertEqual(x["action"], "BUY")
        self.assertLess(x["rsi"], 10)

    def test_no_buy_below_200_day_average(self):
        down = [300 - i * 0.5 for i in range(250)]
        self.assertIsNone(ra.decide(series(down + [down[-1] - 1]), down[-1] - 3)["action"])

    def test_open_position_is_rebuilt_then_sold_above_5_day_average(self):
        closes = UP + [UP[-1] - 1, UP[-1] - 3]  # the rule bought at the last close
        pos, _ = ra.replay(series(closes))
        self.assertEqual(pos[1], UP[-1] - 3)
        hold = ra.decide(series(closes), UP[-1] - 4)
        self.assertEqual(hold["action"], "HOLD")
        sell = ra.decide(series(closes), UP[-1] + 2)
        self.assertEqual(sell["action"], "SELL")

    def test_closed_trades_are_counted_with_cost(self):
        closes = UP + [UP[-1] - 1, UP[-1] - 3, UP[-1] + 2]
        pos, trades = ra.replay(series(closes))
        self.assertIsNone(pos)
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades[0], (UP[-1] + 2) / (UP[-1] - 3) - 1 - ra.COST)


class Market(unittest.TestCase):
    def meta(self, start, end):
        return {"currentTradingPeriod": {"regular": {"start": start.timestamp(), "end": end.timestamp()}}}

    def test_states(self):
        day = datetime.datetime(2026, 10, 26, tzinfo=ra.NY)
        o, c = day.replace(hour=9, minute=30), day.replace(hour=16)
        self.assertEqual(ra.market_state(self.meta(o, c), day.replace(hour=15, minute=40)), "open")
        early = day.replace(hour=13)
        self.assertEqual(ra.market_state(self.meta(o, early), day.replace(hour=15, minute=40)), "closed-early")
        friday = o - datetime.timedelta(days=3)
        self.assertEqual(ra.market_state(self.meta(friday, friday.replace(hour=16)),
                                         day.replace(hour=15, minute=40)), "closed")


if __name__ == "__main__":
    unittest.main()
