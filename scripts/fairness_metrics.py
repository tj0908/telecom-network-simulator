#!/usr/bin/env python3
"""Shared metric definitions for the D7 evaluation tooling.

Single source of truth for:
  * Jain's fairness index
  * common-observation-window throughputs (the D7.1 metric: one window
    per run, shared by all flows, so rates sum to at most the link
    capacity)
  * descriptive dispersion (sample mean / standard deviation)
  * relative change between two configurations
  * the histogram P95 rule used by src/multiflow_fairness.cc
    (first bin whose cumulative count reaches 95% of the total;
    the bin's right edge is reported)

Used by scripts/run_bottleneck_matrix.py; verified by
scripts/test_metrics.py. Pure standard library, no side effects.
"""

import math


def jain(values) -> float:
    """Jain's fairness index (sum x)^2 / (n * sum x^2).

    Returns 0.0 for an empty input or all-zero values. A single value
    always yields 1.0. Result lies in [1/n, 1] for non-negative input.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return 0.0
    sq = sum(v * v for v in vals)
    if sq == 0:
        return 0.0
    s = sum(vals)
    return (s * s) / (n * sq)


def common_window(flow_rows):
    """Common observation window for one run.

    flow_rows: iterable of dicts with numeric 'rx_bytes', 'first_tx_s',
    'last_rx_s'. Returns (window_start, window_end, {flow: rate_mbps})
    where the window is [min first_tx, max last_rx] over the run's
    flows and each rate is rx_bytes * 8 / window_length. Flow names are
    taken from the 'flow' key.
    """
    rows = list(flow_rows)
    if not rows:
        raise ValueError("no flow rows")
    w0 = min(float(r["first_tx_s"]) for r in rows)
    w1 = max(float(r["last_rx_s"]) for r in rows)
    wlen = w1 - w0
    if wlen <= 0:
        raise ValueError("non-positive window length")
    rates = {r["flow"]: int(r["rx_bytes"]) * 8 / wlen / 1e6 for r in rows}
    return w0, w1, rates


def mean_std(values):
    """(sample mean, sample standard deviation) with n-1 denominator.

    A single value gives std 0.0. Raises on empty input: dispersion of
    nothing must not silently pass as zero.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        raise ValueError("mean_std of empty input")
    mean = sum(vals) / n
    if n == 1:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return mean, math.sqrt(var)


def pct_change(new: float, reference: float):
    """Relative change in percent: (new - reference) / reference * 100.

    Returns None when the reference is zero (undefined), so callers
    must surface that instead of inventing a number.
    """
    if reference == 0:
        return None
    return (new - reference) / reference * 100.0


def p95_from_histogram(bin_counts, bin_width: float) -> float:
    """P95 under the same rule as the C++ collector: cumulative counts
    over equal-width bins starting at 0; returns the right edge of the
    first bin whose cumulative count reaches 95% of the total.
    Returns 0.0 when there are no samples."""
    total = sum(bin_counts)
    if total == 0:
        return 0.0
    target = 0.95 * total
    cum = 0
    for i, count in enumerate(bin_counts):
        cum += count
        if cum >= target:
            return (i + 1) * bin_width
    return len(bin_counts) * bin_width
