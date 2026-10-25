import datetime
import lzma
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dukascopy as dk  # noqa: E402

DAY = datetime.date(2025, 10, 6)


def bi5(rows):
    return lzma.compress(b"".join(struct.pack(">5if", *r) for r in rows), format=lzma.FORMAT_ALONE)


class Decode(unittest.TestCase):
    def test_fields_and_scaling(self):
        # sec, open, close, low, high, volume (gold point = 1000)
        raw = bi5([(0, 2650100, 2650900, 2649800, 2651200, 1.5), (60, 2650900, 2650900, 2650900, 2650900, 0.0)])
        out = dk.decode(raw, DAY, 1000)
        self.assertEqual(len(out), 1)  # the no-tick minute is dropped
        t, o, h, l, c = out[0]
        self.assertEqual(t, datetime.datetime(2025, 10, 6, tzinfo=datetime.timezone.utc))
        self.assertEqual((o, h, l, c), (2650.1, 2651.2, 2649.8, 2650.9))

    def test_wrong_field_order_fails_loudly(self):
        raw = bi5([(0, 2650100, 2651200, 2650900, 2649800, 1.0)])  # high in the close slot
        with self.assertRaises(ValueError):
            dk.decode(raw, DAY, 1000)

    def test_empty_file_is_no_data(self):
        self.assertEqual(dk.decode(b"", DAY, 1000), [])


class FiveMinutes(unittest.TestCase):
    def test_aggregates_to_new_york_5m(self):
        base = datetime.datetime(2025, 10, 6, 12, 30, tzinfo=datetime.timezone.utc)  # 8:30 New York
        rows = [(base + datetime.timedelta(minutes=m), 10 + m, 11 + m, 9 + m, 10.5 + m) for m in range(7)]
        bars = dk.to5m(rows)
        self.assertEqual(len(bars), 2)
        t, o, h, l, c = bars[0]
        self.assertEqual((t.hour, t.minute), (8, 30))
        self.assertEqual((o, h, l, c), (10, 15, 9, 14.5))


if __name__ == "__main__":
    unittest.main()
