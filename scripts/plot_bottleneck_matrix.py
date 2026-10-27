#!/usr/bin/env python3
"""Phase 3 plots: FIFO vs FqCoDel across bottleneck bandwidths.

Reads results/eval_matrix_summary.csv (means +/- sample std over the
5 start-jitter seeds) and writes:
  results/figures/eval_throughput.png  TCP total and UDP throughput
  results/figures/eval_p95_delay.png   P95 end-to-end delay
  results/figures/eval_loss_rate.png   FlowMonitor loss rates
  results/figures/eval_fairness.png    Jain indices (common window)

Error bars are the sample standard deviation across seeds (descriptive
dispersion of the jitter seeds, not a confidence interval).
English labels: default matplotlib font has no CJK glyphs.
"""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

BWS = ["2Mbps", "5Mbps", "10Mbps"]
QUEUES = ["fifo", "fqcodel"]
LABELS = {"fifo": "FIFO (PfifoFast 100p)", "fqcodel": "FqCoDel 100p"}


def load_summary():
    rows = list(csv.DictReader(open(RESULTS / "eval_matrix_summary.csv",
                                    newline="")))
    return {(r["queue"], r["bottleneck"]): r for r in rows}


def series(summary, metric):
    """{queue: (means[3], stds[3])} ordered by BWS."""
    out = {}
    for q in QUEUES:
        out[q] = ([float(summary[(q, bw)][f"{metric}_mean"]) for bw in BWS],
                  [float(summary[(q, bw)][f"{metric}_std"]) for bw in BWS])
    return out


def two_panels(summary, metric_a, metric_b, titles, ylabel, outfile,
               log=False, footnote=None):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    x = np.arange(len(BWS))
    width = 0.38
    for ax, metric, title in zip(axes, (metric_a, metric_b), titles):
        data = series(summary, metric)
        for j, q in enumerate(QUEUES):
            means, stds = data[q]
            bars = ax.bar(x + (j - 0.5) * width, means, width,
                          yerr=stds, capsize=3, label=LABELS[q],
                          error_kw={"lw": 0.8})
            ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=1)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(x, BWS)
        ax.grid(axis="y", alpha=0.3)
        if log:
            ax.set_yscale("log")
    axes[0].set_ylabel(ylabel)
    axes[0].legend(fontsize=8)
    fig.suptitle("FIFO vs FqCoDel, group C mixed traffic "
                 "(mean +/- std, 5 jitter seeds)", fontsize=11)
    if footnote:
        fig.text(0.5, 0.005, footnote, ha="center", fontsize=8,
                 style="italic")
    fig.tight_layout()
    fig.savefig(FIGURES / outfile, dpi=150)
    plt.close(fig)
    print(f"wrote {FIGURES / outfile}")


def fairness(summary):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    x = np.arange(len(BWS))
    width = 0.38
    tcp = series(summary, "jain_tcp")
    for j, q in enumerate(QUEUES):
        means, stds = tcp[q]
        bars = ax.bar(x + (j - 0.5) * width, means, width, yerr=stds,
                      capsize=3, label=f"Jain TCP-only - {LABELS[q]}",
                      error_kw={"lw": 0.8})
        ax.bar_label(bars, fmt="%.3f", fontsize=8, padding=1)
    allj = series(summary, "jain_all")
    for j, q in enumerate(QUEUES):
        means, _ = allj[q]
        ax.plot(x + (j - 0.5) * width, means, "kD", markersize=5,
                label="Jain all flows (incl. UDP)" if j == 0 else None)
    ax.set_xticks(x, BWS)
    ax.set_ylabel("Jain index (common window)")
    ax.set_ylim(0.3, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title("Fairness: FIFO vs FqCoDel by bottleneck bandwidth")
    fig.tight_layout()
    fig.savefig(FIGURES / "eval_fairness.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIGURES / 'eval_fairness.png'}")


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    summary = load_summary()
    two_panels(summary, "tcp_total_thr", "udp_thr",
               ("TCP total throughput (2 flows)", "UDP throughput"),
               "Mbps (common window)", "eval_throughput.png")
    two_panels(summary, "tcp_p95_delay", "udp_p95_delay",
               ("TCP P95 delay (mean of 2 flows)", "UDP P95 delay"),
               "ms (log scale)", "eval_p95_delay.png", log=True,
               footnote="P95 from FlowMonitor delay histogram "
                        "(bin width 0.5 ms, first bin reaching 95% "
                        "cumulative count, right edge reported)")
    two_panels(summary, "tcp_loss_pct", "udp_loss_pct",
               ("TCP loss rate (pooled, IP layer)",
                "UDP loss rate (IP layer)"),
               "% of transmitted packets", "eval_loss_rate.png")
    fairness(summary)


if __name__ == "__main__":
    main()
