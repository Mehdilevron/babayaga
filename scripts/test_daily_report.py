import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_report as dr  # noqa: E402

D = datetime.date(2026, 1, 5)


def bar(o, h, l, c):
    return (D, o, h, l, c)


class Simulate(unittest.TestCase):
    # order placed after day 0: entry 100, stop 98, target 104 (2R)
    base = [bar(99, 100, 98, 99.5)]

    def run_buy(self, *days):
        return dr.simulate(self.base + [bar(*d) for d in days] + [bar(100, 100, 100, 100)] * 12,
                           0, "BUY", 100.0, 98.0, 104.0)

    def test_target(self):
        self.assertEqual(self.run_buy((99, 101, 98.5, 100.5), (100.5, 104.5, 100, 104)), (2.0, 2))

    def test_not_triggered(self):
        self.assertEqual(self.run_buy((99, 99.9, 98.5, 99.5))[0], None)

    def test_gap_fill_at_open(self):
        r, _ = self.run_buy((101, 104.2, 100.5, 104))  # fill 101, risk 3, target 104
        self.assertAlmostEqual(r, 1.0)

    def test_gap_past_target_skipped(self):
        self.assertEqual(self.run_buy((104.5, 105, 104, 104.8))[0], None)

    def test_stop_on_trigger_day(self):
        self.assertEqual(self.run_buy((99, 101, 97, 97.5)), (-1.0, 1))

    def test_both_same_day_counts_as_loss(self):
        r, j = self.run_buy((99, 101, 98.5, 100.5), (100.5, 104.5, 97.9, 101))
        self.assertEqual((r, j), (-1.0, 2))

    def test_gap_through_stop_exits_at_open(self):
        r, _ = self.run_buy((99, 101, 98.5, 100.5), (97, 97.5, 96, 97))
        self.assertAlmostEqual(r, -1.5)

    def test_time_exit_after_hold_days(self):
        days = [(99, 101, 99, 100)] + [(100, 101, 99, 101)] * 12
        r, j = dr.simulate(self.base + [bar(*d) for d in days], 0, "BUY", 100.0, 98.0, 104.0)
        self.assertEqual(j, dr.HOLD_DAYS)
        self.assertAlmostEqual(r, 0.5)  # closed at 101

    def test_still_open_has_no_result(self):
        b = self.base + [bar(99, 101, 99, 100)] + [bar(100, 101, 99, 100)] * 3
        self.assertEqual(dr.simulate(b, 0, "BUY", 100.0, 98.0, 104.0)[0], None)

    def test_sell_mirror(self):
        b = [bar(101, 102, 100, 100.5), bar(101, 101.5, 99, 99.5), bar(99.5, 100, 95.5, 96)]
        b += [bar(96, 96, 96, 96)] * 12
        self.assertEqual(dr.simulate(b, 0, "SELL", 100.0, 102.0, 96.0), (2.0, 2))


class Indicators(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(dr.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_rsi_all_up(self):
        self.assertEqual(dr.rsi(list(range(1, 20)))[-1], 100.0)

    def test_signal(self):
        c, s20, s50, r = [10], [9], [8], [55]
        self.assertEqual(dr.signal(0, c, s20, s50, r), "BUY")
        self.assertEqual(dr.signal(0, [7], [8], [9], [45]), "SELL")
        self.assertEqual(dr.signal(0, [10], [9], [8], [75]), None)


class Filter(unittest.TestCase):
    def x(self, trades, won, avg_r, side="BUY"):
        return {"side": side, "trades": trades, "won": won, "avg_r": avg_r}

    def test_passes_only_with_enough_trades_wins_and_profit(self):
        self.assertTrue(dr.strong(self.x(20, 16, 0.4)))         # 80%, 20 trades
        self.assertFalse(dr.strong(self.x(20, 15, 0.4)))        # 75%
        self.assertFalse(dr.strong(self.x(10, 9, 0.4)))         # too few trades
        self.assertFalse(dr.strong(self.x(20, 17, -0.1)))       # wins but loses money
        self.assertFalse(dr.strong(self.x(20, 17, 0.4, None)))  # no setup today
        self.assertFalse(dr.strong(None))

    def test_reason_for_hiding(self):
        self.assertEqual(dr.filtered_out(self.x(39, 21, 0.55)), "Setup hidden: past win rate 54% (needs 80%+)")
        self.assertEqual(dr.filtered_out(self.x(9, 9, 1.0)), "Setup hidden: only 9 past trades (needs 15+)")


class Calendar(unittest.TestCase):
    T = datetime.datetime(2026, 10, 29, 12, 30, tzinfo=datetime.timezone.utc)

    def test_movers_kept_noise_dropped(self):
        keep = ["Fed Funds Tgt Rate", "Core PCE Price Index YY*", "Non-Farm Payrolls",
                "CPI YY *", "PPI QQ", "GDP Flash QQ SA", "BoC Rate Decision"]
        drop = ["MBA 30-Yr Mortgage Rate", "Dallas Fed PCE*", "ISM Manuf Employment Idx",
                "CPI Index*", "Consumer Confidence*"]
        for t in keep:
            self.assertTrue(dr.HIGH_IMPACT.search(t) and not dr.NOT_IMPACT.search(t), t)
        for t in drop:
            self.assertFalse(dr.HIGH_IMPACT.search(t) and not dr.NOT_IMPACT.search(t), t)

    def test_group_lists_biggest_first(self):
        ev = [(self.T, "USD", "🇺🇸", dr.clean(n), "", "") for n in
              ("Cont Jobless Clm", "Initial Jobless Clm", "Core PCE Price Index MM *", "GDP Advance")]
        line = dr.event_lines(ev)[0]
        self.assertIn("Core PCE Price Index MM · GDP Advance · Initial jobless claims (+1 more)", line)

    def test_single_event_shows_forecast_and_previous(self):
        ev = [(self.T, "USD", "🇺🇸", "CPI m/m", "0.3%", "0.4%")]
        self.assertEqual(dr.event_lines(ev)[1], "   forecast 0.3% · previous 0.4%")

    def test_news_warning_matches_pair_currencies(self):
        ev = [(self.T, "JPY", "🇯🇵", "BOJ rate", "", ""), (self.T, "EUR", "🇪🇺", "ECB rate", "", "")]
        self.assertIn("EUR ECB rate", dr.news_warning("EUR/USD", ev))
        self.assertIsNone(dr.news_warning("Gold", ev))  # gold and stocks watch USD

    def test_window(self):
        ev = [(self.T, "USD", "🇺🇸", "x", "", "")]
        self.assertEqual(dr.window(ev, self.T - datetime.timedelta(hours=1), 36), ev)
        self.assertEqual(dr.window(ev, self.T + datetime.timedelta(hours=1), 36), [])


class Split(unittest.TestCase):
    def test_short_message_is_one_part(self):
        self.assertEqual(dr.split("T", "hello"), [("T", "hello")])

    def test_long_message_splits_on_blank_lines(self):
        text = "\n\n".join(["x" * 1000] * 9)
        parts = dr.split("T", text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p.encode()) <= dr.MAX_BYTES for _, p in parts))
        self.assertEqual("\n\n".join(p for _, p in parts), text)
        self.assertEqual(parts[0][0], "T (1/%d)" % len(parts))


if __name__ == "__main__":
    unittest.main()
