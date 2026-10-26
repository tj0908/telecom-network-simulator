#!/usr/bin/env python3
"""D7: plots for the multi-flow fairness matrix.

Throughput and Jain indices use the COMMON OBSERVATION WINDOW metric
(results/d7_unified_window.csv, added by the D7.1 audit): one window
per run shared by all flows, so the rates sum to at most the 2 Mbps
bottleneck capacity. The original per-flow-span rates remain in
results/d7_metrics.csv / d7_fairness_summary.csv as historical data
but are NOT plotted: their denominators differ per flow, which made
the C/FIFO TCP Jain index read 0.7093 instead of the delivered-volume
value 0.9987. Delays are per-delivered-packet means from
results/d7_metrics.csv (not window-dependent).

Writes:
  results/figures/d7_throughput.png  per-flow throughput, FIFO vs FqCoDel
  results/figures/d7_delay.png       per-flow mean delay (log scale)
  results/figures/d7_fairness.png    Jain indices per group

Labels are English: the default matplotlib font has no CJK glyphs
(same constraint as D4/D5 plots).
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

GROUPS = ["A", "B", "C"]
GROUP_TITLES = {
    "A": "A: TCP x2, no UDP",
    "B": "B: TCP x2 + UDP 500 kbps",
    "C": "C: TCP x2 + UDP 4 Mbps",
}
QUEUES = ["fifo", "fqcodel"]
QUEUE_LABELS = {"fifo": "FIFO (PfifoFast 100p)", "fqcodel": "FqCoDel 100p"}
FLOWS = ["tcp1", "tcp2", "udp"]


def load(name):
    with open(RESULTS / name, newline="") as f:
        return list(csv.DictReader(f))


def flow_panels(flows, field, ylabel, title, outfile, log=False):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    x = np.arange(len(FLOWS))
    width = 0.38
    for ax, group in zip(axes, GROUPS):
        for j, queue in enumerate(QUEUES):
            vals = []
            for flow in FLOWS:
                match = [r for r in flows if r["group"] == group
                         and r["queue"] == queue and r["flow"] == flow]
                vals.append(float(match[0][field]) if match else 0.0)
            bars = ax.bar(x + (j - 0.5) * width, vals, width,
                          label=QUEUE_LABELS[queue])
            ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=1)
        ax.set_title(GROUP_TITLES[group], fontsize=10)
        ax.set_xticks(x, ["TCP 1", "TCP 2", "UDP"])
        ax.grid(axis="y", alpha=0.3)
        if log:
            ax.set_yscale("log")
    axes[0].set_ylabel(ylabel)
    axes[0].legend(fontsize=8)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES / outfile, dpi=150)
    plt.close(fig)
    print(f"wrote {FIGURES / outfile}")


def jain(values):
    n = len(values)
    s = sum(values)
    sq = sum(v * v for v in values)
    return (s * s) / (n * sq) if n and sq else 0.0


def rates_by_run(unified):
    runs = {}
    for r in unified:
        runs.setdefault((r["group"], r["queue"]), {})[r["flow"]] = \
            float(r["unified_throughput_mbps"])
    return runs


def fairness_plot(unified):
    runs = rates_by_run(unified)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    x = np.arange(len(GROUPS))
    width = 0.38
    for j, queue in enumerate(QUEUES):
        vals = [jain([runs[(g, queue)]["tcp1"], runs[(g, queue)]["tcp2"]])
                for g in GROUPS]
        bars = ax.bar(x + (j - 0.5) * width, vals, width,
                      label=f"Jain (TCP flows only) - {QUEUE_LABELS[queue]}")
        ax.bar_label(bars, fmt="%.3f", fontsize=8, padding=1)
    # Jain over all flows (incl. unresponsive UDP) as markers, B/C only.
    for j, queue in enumerate(QUEUES):
        xs, ys = [], []
        for i, g in enumerate(GROUPS):
            rates = runs[(g, queue)]
            if "udp" in rates:
                xs.append(i + (j - 0.5) * width)
                ys.append(jain(list(rates.values())))
        ax.plot(xs, ys, "kD", markersize=5,
                label="Jain (all flows, incl. UDP)" if j == 0 else None)
    ax.set_xticks(x, [GROUP_TITLES[g] for g in GROUPS], fontsize=9)
    ax.set_ylabel("Jain's fairness index (common window)")
    ax.set_ylim(0.3, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title("D7 fairness (common observation window): "
                 "bottleneck 2 Mbps, queue 100p")
    fig.tight_layout()
    fig.savefig(FIGURES / "d7_fairness.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIGURES / 'd7_fairness.png'}")


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    flows = load("d7_metrics.csv")
    unified = load("d7_unified_window.csv")
    flow_panels(unified, "unified_throughput_mbps",
                "IP-layer throughput, common window (Mbps)",
                "D7 per-flow throughput (common observation window)",
                "d7_throughput.png")
    flow_panels(flows, "avg_delay_ms", "Mean end-to-end delay (ms, log scale)",
                "D7 per-flow mean delay by group and queue policy",
                "d7_delay.png", log=True)
    fairness_plot(unified)


if __name__ == "__main__":
    main()
