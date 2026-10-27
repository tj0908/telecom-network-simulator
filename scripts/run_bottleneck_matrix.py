#!/usr/bin/env python3
"""Phase 3 (upgrade): controlled FIFO vs FqCoDel comparison matrix.

Configuration space (30 runs):
  queue      in {fifo, fqcodel}        (PfifoFast / FqCoDel, both 100p)
  bottleneck in {2Mbps, 5Mbps, 10Mbps}
  seed       in {1..5}                 (start-time jitter seeds)
  scenario   fixed: D7 group C (2x TCP BulkSend + UDP OnOff 4 Mbps)

Everything else matches D7: dumbbell topology, access links
10 Mbps/2 ms, bottleneck delay 10 ms, flows stop at 11 s, sim 12 s,
device queue DropTail 100p under both policies.

About the seeds: the base simulation is deterministic. The ONLY
stochastic element is the per-flow start offset in [0, 0.2] s drawn
from the run's seed (see src/multiflow_fairness.cc). The 5 seeds are
therefore 5 phase alignments of the same scenario, NOT 5 independent
network samples; dispersion is reported descriptively (sample mean
and sample standard deviation) and no significance claims are made.

Outputs:
  results/eval_matrix_raw.csv      one row per (run, flow), 90 rows
  results/eval_matrix_summary.csv  one row per (queue, bottleneck):
                                   mean +/- sample std over the 5 seeds

All throughputs in the summary use the D7.1 common observation window.
Loss rate is FlowMonitor lostPackets / txPackets (IP layer); the TCP
aggregate loss pools both flows' packets. Per-run TCP delay/P95 first
average the two TCP flows, then seeds are aggregated.
"""

import csv
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fairness_metrics import common_window, jain, mean_std, pct_change

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "multiflow_fairness"
RESULTS = ROOT / "results"
RAW_CSV = RESULTS / "eval_matrix_raw.csv"
SUMMARY_CSV = RESULTS / "eval_matrix_summary.csv"

QUEUES = ["fifo", "fqcodel"]
BOTTLENECKS = ["2Mbps", "5Mbps", "10Mbps"]
SEEDS = [1, 2, 3, 4, 5]
GROUP = "C"

BUILD_CMD = (
    "g++ -std=c++17 -O0 -g0 src/multiflow_fairness.cc -o multiflow_fairness "
    "$(pkg-config --cflags --libs ns3-core ns3-network ns3-internet "
    "ns3-point-to-point ns3-applications ns3-flow-monitor ns3-traffic-control)"
)

RAW_FIELDS = [
    "queue", "bottleneck", "seed", "flow", "protocol",
    "tx_packets", "rx_packets", "lost_packets", "loss_rate_pct",
    "unreceived_pct", "avg_delay_ms", "p95_delay_ms", "rx_bytes",
    "span_throughput_mbps", "unified_throughput_mbps",
    "first_tx_s", "last_rx_s", "start_offset_s", "window_len_s",
    "wall_time_s",
]


def ensure_binary() -> None:
    if BIN.exists():
        return
    print("[build] multiflow_fairness binary missing, compiling...")
    subprocess.run(BUILD_CMD, shell=True, cwd=ROOT, check=True)


def run_once(queue: str, bw: str, seed: int, tmp_csv: Path):
    if tmp_csv.exists():
        tmp_csv.unlink()
    t0 = time.perf_counter()
    subprocess.run(
        [str(BIN), f"--group={GROUP}", f"--queue={queue}",
         f"--bottleneck={bw}", f"--seed={seed}", f"--csvfile={tmp_csv}"],
        cwd=ROOT, check=True, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    rows = list(csv.DictReader(open(tmp_csv, newline="")))
    return rows, wall


def collect() -> list:
    raw = []
    with tempfile.TemporaryDirectory() as td:
        tmp_csv = Path(td) / "run.csv"
        for queue in QUEUES:
            for bw in BOTTLENECKS:
                for seed in SEEDS:
                    rows, wall = run_once(queue, bw, seed, tmp_csv)
                    w0, w1, rates = common_window(rows)
                    wlen = w1 - w0
                    for r in rows:
                        raw.append({
                            "queue": queue, "bottleneck": bw, "seed": seed,
                            "flow": r["flow"], "protocol": r["protocol"],
                            "tx_packets": r["tx_packets"],
                            "rx_packets": r["rx_packets"],
                            "lost_packets": r["lost_packets"],
                            "loss_rate_pct": r["loss_rate_pct"],
                            "unreceived_pct": r["unreceived_pct"],
                            "avg_delay_ms": r["avg_delay_ms"],
                            "p95_delay_ms": r["p95_delay_ms"],
                            "rx_bytes": r["rx_bytes"],
                            "span_throughput_mbps": r["throughput_mbps"],
                            "unified_throughput_mbps":
                                f"{rates[r['flow']]:.4f}",
                            "first_tx_s": r["first_tx_s"],
                            "last_rx_s": r["last_rx_s"],
                            "start_offset_s": r["start_offset_s"],
                            "window_len_s": f"{wlen:.4f}",
                            "wall_time_s": f"{wall:.3f}",
                        })
                    print(f"[run] queue={queue} bottleneck={bw} seed={seed} "
                          f"wall={wall:.2f}s")
    return raw


def per_run_records(raw: list) -> list:
    """Aggregate each (queue, bottleneck, seed) run into one record."""
    records = []
    keys = {(r["queue"], r["bottleneck"], int(r["seed"])) for r in raw}
    for queue, bw, seed in sorted(keys):
        rows = [r for r in raw if r["queue"] == queue
                and r["bottleneck"] == bw and int(r["seed"]) == seed]
        by = {r["flow"]: r for r in rows}
        tcp = [by["tcp1"], by["tcp2"]]
        rates = {f: float(by[f]["unified_throughput_mbps"])
                 for f in ("tcp1", "tcp2", "udp")}
        records.append({
            "queue": queue, "bottleneck": bw, "seed": seed,
            "tcp_total_thr": rates["tcp1"] + rates["tcp2"],
            "udp_thr": rates["udp"],
            "total_thr": sum(rates.values()),
            "tcp_avg_delay": sum(float(r["avg_delay_ms"]) for r in tcp) / 2,
            "tcp_p95_delay": sum(float(r["p95_delay_ms"]) for r in tcp) / 2,
            "udp_avg_delay": float(by["udp"]["avg_delay_ms"]),
            "udp_p95_delay": float(by["udp"]["p95_delay_ms"]),
            "tcp_loss_pct": 100.0 * sum(int(r["lost_packets"]) for r in tcp)
                            / sum(int(r["tx_packets"]) for r in tcp),
            "udp_loss_pct": float(by["udp"]["loss_rate_pct"]),
            "jain_tcp": jain([rates["tcp1"], rates["tcp2"]]),
            "jain_all": jain(list(rates.values())),
            "wall_time_s": float(rows[0]["wall_time_s"]),
        })
    return records


AGG_METRICS = ["tcp_total_thr", "udp_thr", "total_thr", "tcp_avg_delay",
               "tcp_p95_delay", "udp_avg_delay", "udp_p95_delay",
               "tcp_loss_pct", "udp_loss_pct", "jain_tcp", "jain_all",
               "wall_time_s"]


def summarize(records: list) -> list:
    summary = []
    for queue in QUEUES:
        for bw in BOTTLENECKS:
            recs = [r for r in records
                    if r["queue"] == queue and r["bottleneck"] == bw]
            row = {"queue": queue, "bottleneck": bw, "n_seeds": len(recs)}
            for metric in AGG_METRICS:
                mean, std = mean_std([r[metric] for r in recs])
                row[f"{metric}_mean"] = f"{mean:.4f}"
                row[f"{metric}_std"] = f"{std:.4f}"
            summary.append(row)
    return summary


def validate(raw: list, records: list) -> list:
    errors = []
    if len(raw) != 90:
        errors.append(f"expected 90 raw rows, got {len(raw)}")
    if len(records) != 30:
        errors.append(f"expected 30 run records, got {len(records)}")
    for rec in records:
        cap = float(rec["bottleneck"][:-4])
        if rec["total_thr"] > cap * (1 + 1e-4):
            errors.append(f"{rec['queue']}/{rec['bottleneck']}/seed{rec['seed']}: "
                          f"unified total {rec['total_thr']:.4f} > capacity {cap}")
        for key in ("jain_tcp", "jain_all"):
            if not (0.0 <= rec[key] <= 1.0 + 1e-9):
                errors.append(f"{rec['queue']}/{rec['bottleneck']}: {key} out of range")
    return errors


def main() -> int:
    ensure_binary()
    RESULTS.mkdir(exist_ok=True)
    raw = collect()
    with open(RAW_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(raw)
    records = per_run_records(raw)
    summary = summarize(records)
    with open(SUMMARY_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(summary)

    errors = validate(raw, records)

    # Determinism of the seeded path: repeat one run, rows must match.
    with tempfile.TemporaryDirectory() as td:
        again, _ = run_once("fifo", "2Mbps", 1, Path(td) / "again.csv")
    first = [r for r in raw if r["queue"] == "fifo"
             and r["bottleneck"] == "2Mbps" and int(r["seed"]) == 1]
    key = lambda r: (r["flow"], r["tx_packets"], r["rx_packets"],
                     r["lost_packets"], r["rx_bytes"], r["p95_delay_ms"])
    if sorted(key(r) for r in again) != sorted(key(r) for r in first):
        errors.append("seeded repeat run differs (seed=1 fifo 2Mbps)")

    print("\n===== summary (mean +/- std over 5 jitter seeds) =====")
    print(f"{'config':<18}{'tcp_thr':>14}{'udp_thr':>14}{'tcp_avgD':>14}"
          f"{'tcp_p95D':>14}{'tcp_loss%':>11}{'jain_tcp':>10}")
    for s in summary:
        print(f"{s['queue'] + '/' + s['bottleneck']:<18}"
              f"{float(s['tcp_total_thr_mean']):>7.3f}±{float(s['tcp_total_thr_std']):.3f}"
              f"{float(s['udp_thr_mean']):>7.3f}±{float(s['udp_thr_std']):.3f}"
              f"{float(s['tcp_avg_delay_mean']):>8.1f}±{float(s['tcp_avg_delay_std']):.1f}"
              f"{float(s['tcp_p95_delay_mean']):>8.1f}±{float(s['tcp_p95_delay_std']):.1f}"
              f"{float(s['tcp_loss_pct_mean']):>7.2f}±{float(s['tcp_loss_pct_std']):.2f}"
              f"{float(s['jain_tcp_mean']):>10.4f}")

    print("\n===== validation =====")
    checks = [
        ("90 raw rows / 30 run records",
         not any("rows" in e or "records" in e for e in errors)),
        ("unified total throughput <= bottleneck capacity in all runs",
         not any("capacity" in e for e in errors)),
        ("Jain indices within [0, 1]", not any("out of range" in e for e in errors)),
        ("seeded repeat run identical (seed=1, fifo, 2Mbps)",
         not any("repeat run" in e for e in errors)),
    ]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if errors:
        for e in errors:
            print(f"  error: {e}")
        return 1
    print(f"\nwrote {RAW_CSV}")
    print(f"wrote {SUMMARY_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
