"""Tests for the weekly-brief window-selection logic.

Regression target: a weekly synth run on Monday (day 1 of the new ISO week)
was synthesizing the brand-new current week (one daily fetch, ~6 items)
instead of the just-completed previous week (~90 items). See the W23 brief
(10 items shown) vs W23's actual 92 collected items.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_sources import choose_week_window  # noqa: E402


def check(label, got, want):
    status = "PASS" if got == want else "FAIL"
    print(f"[{status}] {label}: got={got!r} want={want!r}")
    return got == want


def main():
    results = []
    # The exact bug: Monday, current week has only today's fetch, previous week is full.
    results.append(check("monday_prefers_completed_week", choose_week_window(1, 6, 92), "previous"))
    # Monday but no prior-week data at all → don't return an empty previous window.
    results.append(check("monday_no_prev_falls_to_current", choose_week_window(1, 0, 0), "current"))
    # Busy mid-week → use the current week as it accumulates.
    results.append(check("wednesday_uses_current", choose_week_window(3, 50, 92), "current"))
    # Sparse non-Monday with a richer previous week → fall back (legacy behavior preserved).
    results.append(check("sparse_friday_falls_back", choose_week_window(5, 2, 80), "previous"))
    # Rich current week late in the week → current, even if previous was bigger.
    results.append(check("rich_friday_uses_current", choose_week_window(5, 40, 10), "current"))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
