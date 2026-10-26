#!/usr/bin/env python3
"""D4: plot TCP/UDP comparison figures from results/d4_metrics.csv.

Produces in results/figures/:
  throughput.png   IP-layer throughput vs bottleneck bandwidth
  loss_rate.png    packet loss rate vs bottleneck bandwidth
  avg_delay.png    average end-to-end delay vs bottleneck bandwidth
                   (log scale: congested and uncongested delays differ
                   by two orders of magnitude)

Labels are in English because the default matplotlib fonts have no CJK
glyphs. Run scripts/run_experiments.py first to generate the CSV.
"""

import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "results" / "d4_metrics.csv"
FIG_DIR = ROOT / "results" / "figures"

BOTTLENECKS = ["2Mbps", "5Mbps", "10Mbps"]
PROTOCOLS = ["tcp", "udp"]
COLORS = {"tcp": "#1f77b4", "udp": "#d62728"}


def load():
    if not CSV_PATH.exists():
        sys.exit(f"{CSV_PATH} not found; run scripts/run_experiments.py first")
    with open(CSV_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    data = {(r["protocol"], r["bottleneck"]): r for r in rows}
    return data


def grouped_bar(data, field, ylabel, title, filename, log=False, fmt="{:.2f}"):
    x = range(len(BOTTLENECKS))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for i, proto in enumerate(PROTOCOLS):
        vals = [float(data[(proto, bw)][field]) for bw in BOTTLENECKS]
        bars = ax.bar([xi + (i - 0.5) * width for xi in x], vals,
                      width=width, label=proto.upper(), color=COLORS[proto])
        ax.bar_label(bars, labels=[fmt.format(v) for v in vals],
                     padding=2, fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"bottleneck {bw}" for bw in BOTTLENECKS])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if log:
        ax.set_yscale("log")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, which="both")
    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / filename
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    data = load()
    grouped_bar(data, "throughput_mbps", "Throughput (Mbps, IP layer)",
                "TCP vs UDP throughput", "throughput.png", fmt="{:.2f}")
    grouped_bar(data, "loss_rate_pct", "Packet loss rate (%)",
                "TCP vs UDP packet loss rate", "loss_rate.png", fmt="{:.2f}")
    grouped_bar(data, "avg_delay_ms", "Average end-to-end delay (ms, log scale)",
                "TCP vs UDP average delay", "avg_delay.png", log=True, fmt="{:.1f}")


if __name__ == "__main__":
    main()
