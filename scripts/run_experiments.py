#!/usr/bin/env python3
"""D4: automated TCP/UDP x bottleneck experiment matrix.

Runs the D3 FlowMonitor binary (./flow_metrics) for
  protocol  in {tcp, udp}
  bottleneck in {2Mbps, 5Mbps, 10Mbps}
and produces:
  results/d4_metrics_all_flows.csv  raw per-flow rows (incl. TCP ACK flow)
  results/d4_metrics.csv            one data-flow row per experiment (6 rows)

Validation performed:
  * exactly 6 data rows, one per (protocol, bottleneck) combination
  * all metrics non-negative, loss rate within [0, 100] %
  * the whole matrix is run a second time and must reproduce identical
    data rows (ns-3 runs are deterministic with the default seed)

The compiled binary is built automatically if it is missing.
D1-D3 result files are never touched.
"""

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "flow_metrics"
RESULTS = ROOT / "results"
RAW_CSV = RESULTS / "d4_metrics_all_flows.csv"
FINAL_CSV = RESULTS / "d4_metrics.csv"

PROTOCOLS = ["tcp", "udp"]
BOTTLENECKS = ["2Mbps", "5Mbps", "10Mbps"]

BUILD_CMD = (
    "g++ -std=c++17 -O0 -g0 src/flow_metrics.cc -o flow_metrics "
    "$(pkg-config --cflags --libs ns3-core ns3-network ns3-internet "
    "ns3-point-to-point ns3-applications ns3-flow-monitor ns3-traffic-control)"
)

FINAL_FIELDS = [
    "protocol", "bottleneck",
    "tx_packets", "rx_packets", "lost_packets", "loss_rate_pct",
    "avg_delay_ms", "avg_jitter_ms", "rx_bytes", "throughput_mbps",
]


def ensure_binary() -> None:
    if BIN.exists():
        return
    print("[build] flow_metrics binary missing, compiling...")
    subprocess.run(BUILD_CMD, shell=True, cwd=ROOT, check=True)


def run_matrix(csv_path: Path) -> None:
    if csv_path.exists():
        csv_path.unlink()
    for proto in PROTOCOLS:
        for bw in BOTTLENECKS:
            subprocess.run(
                [str(BIN), f"--protocol={proto}", f"--bottleneck={bw}",
                 f"--csvfile={csv_path}"],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            print(f"[run] protocol={proto} bottleneck={bw} done")


def data_rows(csv_path: Path) -> list:
    with open(csv_path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["flow_label"] == "data"]
    rows.sort(key=lambda r: (r["protocol"], float(r["bottleneck"][:-4])))
    return rows


def write_final(rows: list) -> None:
    with open(FINAL_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FINAL_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FINAL_FIELDS})


def validate(rows: list) -> list:
    """Return a list of validation error strings (empty == all passed)."""
    errors = []
    if len(rows) != len(PROTOCOLS) * len(BOTTLENECKS):
        errors.append(f"expected 6 data rows, got {len(rows)}")
    combos = {(r["protocol"], r["bottleneck"]) for r in rows}
    expected = {(p, b) for p in PROTOCOLS for b in BOTTLENECKS}
    if combos != expected:
        errors.append(f"combination mismatch: missing {expected - combos}, extra {combos - expected}")
    numeric = ["tx_packets", "rx_packets", "lost_packets", "loss_rate_pct",
               "avg_delay_ms", "avg_jitter_ms", "rx_bytes", "throughput_mbps"]
    for r in rows:
        tag = f"{r['protocol']}@{r['bottleneck']}"
        for field in numeric:
            try:
                v = float(r[field])
            except (TypeError, ValueError):
                errors.append(f"{tag}: {field} not numeric: {r[field]!r}")
                continue
            if v < 0:
                errors.append(f"{tag}: {field} negative: {v}")
        loss = float(r["loss_rate_pct"])
        if not (0.0 <= loss <= 100.0):
            errors.append(f"{tag}: loss_rate_pct out of [0,100]: {loss}")
        if int(r["rx_packets"]) + int(r["lost_packets"]) > int(r["tx_packets"]):
            errors.append(f"{tag}: rx+lost exceeds tx")
    return errors


def main() -> int:
    ensure_binary()
    RESULTS.mkdir(exist_ok=True)

    run_matrix(RAW_CSV)
    rows = data_rows(RAW_CSV)
    write_final(rows)

    errors = validate(rows)

    # Determinism check: rerun the full matrix and compare data rows.
    with tempfile.TemporaryDirectory() as td:
        repeat_csv = Path(td) / "repeat.csv"
        run_matrix(repeat_csv)
        repeat_rows = data_rows(repeat_csv)
    key = lambda r: tuple(r[k] for k in FINAL_FIELDS)
    if [key(r) for r in repeat_rows] != [key(r) for r in rows]:
        errors.append("repeat run produced different data rows")

    print("\n===== D4 experiment matrix (data flows) =====")
    print(f"{'proto':<6}{'bottleneck':<12}{'tx':>7}{'rx':>7}{'lost':>7}"
          f"{'loss%':>9}{'delay_ms':>11}{'thr_Mbps':>10}")
    for r in rows:
        print(f"{r['protocol']:<6}{r['bottleneck']:<12}{r['tx_packets']:>7}"
              f"{r['rx_packets']:>7}{r['lost_packets']:>7}"
              f"{float(r['loss_rate_pct']):>9.2f}{float(r['avg_delay_ms']):>11.2f}"
              f"{float(r['throughput_mbps']):>10.4f}")

    print("\n===== validation =====")
    checks = [
        ("row count == 6 and all combinations present",
         not any("rows" in e or "combination" in e for e in errors)),
        ("all metrics non-negative", not any("negative" in e for e in errors)),
        ("loss rate within [0, 100] %", not any("out of [0,100]" in e for e in errors)),
        ("rx + lost <= tx for every row", not any("exceeds" in e for e in errors)),
        ("repeat run reproduces identical rows",
         not any("repeat run" in e for e in errors)),
    ]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if errors:
        for e in errors:
            print(f"  error: {e}")
        return 1
    print(f"\nwrote {FINAL_CSV}")
    print(f"wrote {RAW_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
