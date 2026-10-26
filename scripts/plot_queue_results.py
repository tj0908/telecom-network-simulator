#!/usr/bin/env python3
"""D5: plot queue-management comparison figures from results/d5_metrics.csv.

Produces in results/figures/:
  d5_throughput.png
  d5_loss_rate.png
  d5_avg_delay.png (log scale)

Labels are in English because the default matplotlib fonts have no CJK
glyphs. Run src/queue_compare for the five scenarios first.
"""

import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "results" / "d5_metrics.csv"
FIG_DIR = ROOT / "results" / "figures"

SCENARIOS = ["default", "fqcodel100", "fifo100", "devq100", "devq10"]
LABELS = {
    "default": "default\nFqCoDel 10240p",
    "fqcodel100": "fqcodel-100\nFqCoDel 100p",
    "fifo100": "fifo-100\nPfifoFast 100p",
    "devq100": "devq-100\nDropTail 100p",
    "devq10": "devq-10\nDropTail 10p",
}
COLOR = "#1f77b4"


def load():
    if not CSV_PATH.exists():
        sys.exit(f"{CSV_PATH} not found; run queue_compare experiments first")
    with open(CSV_PATH, newline="") as f:
        rows = {r["scenario"]: r for r in csv.DictReader(f)}
    missing = [s for s in SCENARIOS if s not in rows]
    if missing:
        sys.exit(f"missing scenarios in CSV: {missing}")
    return rows


def bar(rows, field, ylabel, title, filename, log=False, fmt="{:.2f}"):
    vals = [float(rows[s][field]) for s in SCENARIOS]
    fig, ax = plt.subplots(figsize=(8, 4.4))
    bars = ax.bar([LABELS[s] for s in SCENARIOS], vals, color=COLOR)
    ax.bar_label(bars, labels=[fmt.format(v) for v in vals], padding=2, fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if log:
        ax.set_yscale("log")
    ax.grid(axis="y", alpha=0.3, which="both")
    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / filename
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    rows = load()
    # Effective loss from delivered counts, NOT FlowMonitor lostPackets:
    # in the no-qdisc scenarios the traffic-control layer discards packets
    # without a traced drop event, and lostPackets reads 0 there while
    # (tx - rx) shows the real loss. (tx - rx) is the only loss metric
    # that is comparable across all five scenarios.
    for r in rows.values():
        tx = float(r["tx_packets"])
        rx = float(r["rx_packets"])
        r["effective_loss_pct"] = (tx - rx) / tx * 100.0 if tx else 0.0
    bar(rows, "throughput_mbps", "Throughput (Mbps, IP layer)",
        "Queue strategy: throughput (UDP 4 Mbps into 2 Mbps bottleneck)",
        "d5_throughput.png")
    bar(rows, "effective_loss_pct", "Unreceived ratio ((tx-rx)/tx, %)",
        "Queue strategy: unreceived packet ratio",
        "d5_loss_rate.png")
    bar(rows, "avg_delay_ms", "Average end-to-end delay (ms, log scale)",
        "Queue strategy: average delay",
        "d5_avg_delay.png", log=True, fmt="{:.1f}")


if __name__ == "__main__":
    main()
