"""Download one year of gold minute data into the cache, without testing.

    python3 fetch_gold.py 1   # the latest year
    python3 fetch_gold.py 2   # the year before it
Run both at once to halve the time; each skips days the other already has."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dukascopy  # noqa: E402

year = int(sys.argv[1])
end = datetime.date.today() - datetime.timedelta(days=1) - datetime.timedelta(days=365 * (year - 1))
start = end - datetime.timedelta(days=364 if year == 1 else 365)
failed = dukascopy.download("XAUUSD", start, end)
if failed:
    failed = dukascopy.download("XAUUSD", start, end, pause=3.0)
print("YEAR %d DONE (%s to %s), %d days refused" % (year, start, end, len(failed)), file=sys.stderr)
