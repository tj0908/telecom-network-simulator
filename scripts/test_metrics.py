#!/usr/bin/env python3
"""Unit tests for scripts/fairness_metrics.py (standard library only;
this environment has no pytest).

Run: python3 scripts/test_metrics.py
Exit code 0 iff every test passes. Each test states the definition it
pins down, so a future change to a metric definition fails loudly here
instead of silently shifting published numbers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fairness_metrics import (common_window, jain, mean_std, pct_change,
                              p95_from_histogram)

FAILURES = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(name)


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def main() -> int:
    # --- Jain index ---
    check("jain of equal values is 1", approx(jain([2.0, 2.0, 2.0]), 1.0))
    check("jain of single value is 1", approx(jain([3.5]), 1.0))
    check("jain [1,3] = 0.8", approx(jain([1.0, 3.0]), 0.8))
    check("jain of zeros is 0 (guard)", jain([0.0, 0.0]) == 0.0)
    check("jain of empty is 0 (guard)", jain([]) == 0.0)
    check("jain [1,2,3] in [1/3, 1]", 1 / 3 <= jain([1.0, 2.0, 3.0]) <= 1.0)
    check("jain [0,4] = 0.5 (one flow starved)",
          approx(jain([0.0, 4.0]), 0.5))

    # --- common window ---
    rows = [
        {"flow": "a", "rx_bytes": 1_000_000, "first_tx_s": 1.0, "last_rx_s": 9.0},
        {"flow": "b", "rx_bytes": 500_000, "first_tx_s": 1.2, "last_rx_s": 11.0},
    ]
    w0, w1, rates = common_window(rows)
    check("window spans min firstTx to max lastRx", (w0, w1) == (1.0, 11.0))
    check("window rates use the shared denominator",
          approx(rates["a"], 0.8) and approx(rates["b"], 0.4),
          f"{rates}")
    # The defining property (D7.1): with a shared window, rates of flows
    # that all crossed one bottleneck cannot sum above its capacity.
    rows_c = [
        {"flow": "tcp1", "rx_bytes": 38916, "first_tx_s": 1.0, "last_rx_s": 3.2419},
        {"flow": "tcp2", "rx_bytes": 41856, "first_tx_s": 1.0, "last_rx_s": 11.9934},
        {"flow": "udp", "rx_bytes": 2631052, "first_tx_s": 1.0021, "last_rx_s": 11.8597},
    ]
    _, _, rates_c = common_window(rows_c)
    check("D7 C/FIFO replay: common-window sum <= 2 Mbps",
          sum(rates_c.values()) <= 2.0, f"sum={sum(rates_c.values()):.4f}")
    check("D7 C/FIFO replay: jain_tcp ~= 0.9987 (the D7.1 correction)",
          approx(jain([rates_c["tcp1"], rates_c["tcp2"]]), 0.9987, tol=5e-4),
          f"{jain([rates_c['tcp1'], rates_c['tcp2']]):.4f}")

    # --- mean / std (sample, n-1) ---
    m, s = mean_std([1, 2, 3, 4, 5])
    check("mean of 1..5 is 3", approx(m, 3.0))
    check("sample std of 1..5 is sqrt(2.5)", approx(s, 2.5 ** 0.5),
          f"{s:.6f}")
    m1, s1 = mean_std([7.5])
    check("single value: std defined as 0", m1 == 7.5 and s1 == 0.0)
    try:
        mean_std([])
        check("empty mean_std raises", False)
    except ValueError:
        check("empty mean_std raises", True)

    # --- pct change ---
    check("pct_change +10%", approx(pct_change(110.0, 100.0), 10.0))
    check("pct_change -40%", approx(pct_change(60.0, 100.0), -40.0))
    check("pct_change with zero reference is None",
          pct_change(5.0, 0.0) is None)

    # --- P95 histogram rule (mirrors the C++ collector) ---
    check("p95 of empty histogram is 0", p95_from_histogram([], 0.5) == 0.0)
    check("p95 all mass in first bin = bin width",
          approx(p95_from_histogram([100], 0.5), 0.5))
    check("p95 uniform [10,10,10] w=1 -> 3.0",
          approx(p95_from_histogram([10, 10, 10], 1.0), 3.0))
    check("p95 [95,5] w=2 -> 2.0 (95% reached in first bin)",
          approx(p95_from_histogram([95, 5], 2.0), 2.0))
    check("p95 [94,6] w=2 -> 4.0 (needs second bin)",
          approx(p95_from_histogram([94, 6], 2.0), 4.0))

    print(f"\n{'ALL TESTS PASSED' if not FAILURES else 'FAILURES: ' + str(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
