#!/usr/bin/env python3
"""D7: multi-flow competition / fairness experiment matrix.

Runs ./multiflow_fairness (dumbbell topology, bottleneck 2 Mbps) for
  group in {A: no UDP, B: UDP 500 kbps, C: UDP 4 Mbps}
  queue in {fifo (PfifoFast 100p), fqcodel (FqCoDel 100p)}
and produces:
  results/d7_metrics.csv            one row per (run, data flow)
  results/d7_fairness_summary.csv   one row per run, with Jain indices
  results/d7_<group>_<queue>.txt   raw program output per run

Jain's fairness index J(x) = (sum x)^2 / (n * sum x^2), computed on
IP-layer throughputs. The primary index covers the two TCP flows only
(jain_tcp). jain_all additionally includes the UDP flow where present;
a constant-rate UDP flow does not back off under congestion, so
jain_all mixes responsive and unresponsive flows and must not be read
as a pure fairness verdict (see docs/d7_multiflow.md).

Validation performed:
  * 6 runs, 16 per-flow rows (A: 2 flows, B/C: 3 flows, x 2 queues)
  * readback in each run's output names the expected queue discipline
  * all metrics non-negative, loss/unreceived within [0, 100] %
  * rx + lost <= tx for every flow
  * Jain indices within [1/n, 1]
  * the whole matrix is rerun and must reproduce identical flow rows

The binary is built automatically if missing. D1-D5 files are untouched.
"""

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "multiflow_fairness"
RESULTS = ROOT / "results"
FLOW_CSV = RESULTS / "d7_metrics.csv"
SUMMARY_CSV = RESULTS / "d7_fairness_summary.csv"

GROUPS = ["A", "B", "C"]
QUEUES = ["fifo", "fqcodel"]
EXPECTED_FLOWS = {"A": {"tcp1", "tcp2"}, "B": {"tcp1", "tcp2", "udp"},
                  "C": {"tcp1", "tcp2", "udp"}}
EXPECTED_QDISC = {"fifo": "PfifoFastQueueDisc", "fqcodel": "FqCoDelQueueDisc"}

BUILD_CMD = (
    "g++ -std=c++17 -O0 -g0 src/multiflow_fairness.cc -o multiflow_fairness "
    "$(pkg-config --cflags --libs ns3-core ns3-network ns3-internet "
    "ns3-point-to-point ns3-applications ns3-flow-monitor ns3-traffic-control)"
)


def ensure_binary() -> None:
    if BIN.exists():
        return
    print("[build] multiflow_fairness binary missing, compiling...")
    subprocess.run(BUILD_CMD, shell=True, cwd=ROOT, check=True)


def run_matrix(flow_csv: Path, save_txt: bool) -> None:
    if flow_csv.exists():
        flow_csv.unlink()
    for group in GROUPS:
        for queue in QUEUES:
            proc = subprocess.run(
                [str(BIN), f"--group={group}", f"--queue={queue}",
                 f"--csvfile={flow_csv}"],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            if save_txt:
                (RESULTS / f"d7_{group.lower()}_{queue}.txt").write_text(proc.stdout)
            print(f"[run] group={group} queue={queue} done")


def jain(values: list) -> float:
    n = len(values)
    s = sum(values)
    sq = sum(v * v for v in values)
    if n == 0 or sq == 0:
        return 0.0
    return (s * s) / (n * sq)


def load_flows(csv_path: Path) -> list:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def build_summary(flows: list) -> list:
    summary = []
    for group in GROUPS:
        for queue in QUEUES:
            rows = [r for r in flows
                    if r["group"] == group and r["queue"] == queue]
            by_flow = {r["flow"]: r for r in rows}
            tcp_thr = [float(by_flow[f]["throughput_mbps"]) for f in ("tcp1", "tcp2")]
            all_thr = tcp_thr + ([float(by_flow["udp"]["throughput_mbps"])]
                                 if "udp" in by_flow else [])
            run = rows[0]
            summary.append({
                "group": group,
                "queue": queue,
                "udp_rate": run["udp_rate"],
                "tcp1_throughput_mbps": f"{tcp_thr[0]:.4f}",
                "tcp2_throughput_mbps": f"{tcp_thr[1]:.4f}",
                "udp_throughput_mbps": (f"{float(by_flow['udp']['throughput_mbps']):.4f}"
                                        if "udp" in by_flow else ""),
                "jain_tcp": f"{jain(tcp_thr):.4f}",
                "jain_all": f"{jain(all_thr):.4f}",
                "flows_in_jain_all": len(all_thr),
                "tcp1_avg_delay_ms": f"{float(by_flow['tcp1']['avg_delay_ms']):.2f}",
                "tcp2_avg_delay_ms": f"{float(by_flow['tcp2']['avg_delay_ms']):.2f}",
                "udp_avg_delay_ms": (f"{float(by_flow['udp']['avg_delay_ms']):.2f}"
                                     if "udp" in by_flow else ""),
                "qdisc_dropped": run["qdisc_dropped"],
                "device_dropped": run["device_dropped"],
                "qdisc_occ_mean": run["qdisc_occ_mean"],
                "device_occ_mean": run["device_occ_mean"],
            })
    return summary


def validate(flows: list, summary: list) -> list:
    errors = []
    if len(flows) != 16:
        errors.append(f"rows: expected 16 flow rows, got {len(flows)}")
    if len(summary) != 6:
        errors.append(f"summary: expected 6 runs, got {len(summary)}")
    for group in GROUPS:
        for queue in QUEUES:
            got = {r["flow"] for r in flows
                   if r["group"] == group and r["queue"] == queue}
            if got != EXPECTED_FLOWS[group]:
                errors.append(f"{group}/{queue}: flows {got} != {EXPECTED_FLOWS[group]}")
            txt = (RESULTS / f"d7_{group.lower()}_{queue}.txt").read_text()
            if EXPECTED_QDISC[queue] not in txt:
                errors.append(f"{group}/{queue}: readback missing {EXPECTED_QDISC[queue]}")
    numeric = ["tx_packets", "rx_packets", "lost_packets", "loss_rate_pct",
               "unreceived_pct", "avg_delay_ms", "rx_bytes", "throughput_mbps"]
    for r in flows:
        tag = f"{r['group']}/{r['queue']}/{r['flow']}"
        for field in numeric:
            try:
                v = float(r[field])
            except (TypeError, ValueError):
                errors.append(f"{tag}: {field} not numeric: {r[field]!r}")
                continue
            if v < 0:
                errors.append(f"{tag}: {field} negative: {v}")
        for pct in ("loss_rate_pct", "unreceived_pct"):
            if not (0.0 <= float(r[pct]) <= 100.0):
                errors.append(f"{tag}: {pct} out of [0,100]: {r[pct]}")
        if int(r["rx_packets"]) + int(r["lost_packets"]) > int(r["tx_packets"]):
            errors.append(f"{tag}: rx+lost exceeds tx")
    for s in summary:
        for key, n in (("jain_tcp", 2), ("jain_all", int(s["flows_in_jain_all"]))):
            v = float(s[key])
            if not (1.0 / n - 1e-9 <= v <= 1.0 + 1e-9):
                errors.append(f"{s['group']}/{s['queue']}: {key}={v} out of "
                              f"[1/{n}, 1]")
    return errors


def main() -> int:
    ensure_binary()
    RESULTS.mkdir(exist_ok=True)

    run_matrix(FLOW_CSV, save_txt=True)
    flows = load_flows(FLOW_CSV)
    summary = build_summary(flows)
    with open(SUMMARY_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(summary)

    errors = validate(flows, summary)

    # Determinism check: rerun the whole matrix, flow rows must match.
    with tempfile.TemporaryDirectory() as td:
        repeat_csv = Path(td) / "repeat.csv"
        run_matrix(repeat_csv, save_txt=False)
        repeat_flows = load_flows(repeat_csv)
    if repeat_flows != flows:
        errors.append("repeatability: repeat run produced different flow rows")

    print("\n===== D7 per-flow results =====")
    print(f"{'run':<14}{'flow':<6}{'tx':>7}{'rx':>7}{'lost':>7}"
          f"{'unrecv%':>9}{'delay_ms':>11}{'thr_Mbps':>10}")
    for r in flows:
        print(f"{r['group'] + '/' + r['queue']:<14}{r['flow']:<6}"
              f"{r['tx_packets']:>7}{r['rx_packets']:>7}{r['lost_packets']:>7}"
              f"{float(r['unreceived_pct']):>9.2f}"
              f"{float(r['avg_delay_ms']):>11.2f}"
              f"{float(r['throughput_mbps']):>10.4f}")

    print("\n===== D7 fairness summary =====")
    print(f"{'run':<14}{'tcp1':>8}{'tcp2':>8}{'udp':>8}"
          f"{'jain_tcp':>10}{'jain_all':>10}{'qdisc_drop':>12}")
    for s in summary:
        print(f"{s['group'] + '/' + s['queue']:<14}"
              f"{float(s['tcp1_throughput_mbps']):>8.4f}"
              f"{float(s['tcp2_throughput_mbps']):>8.4f}"
              f"{(float(s['udp_throughput_mbps']) if s['udp_throughput_mbps'] else 0.0):>8.4f}"
              f"{float(s['jain_tcp']):>10.4f}{float(s['jain_all']):>10.4f}"
              f"{s['qdisc_dropped']:>12}")

    print("\n===== validation =====")
    checks = [
        ("16 flow rows / 6 runs with expected flow sets",
         not any("rows" in e or "flows" in e and "!=" in e for e in errors)),
        ("queue readback matches requested policy in all 6 runs",
         not any("readback" in e for e in errors)),
        ("all metrics non-negative", not any("negative" in e for e in errors)),
        ("loss/unreceived within [0, 100] %",
         not any("out of [0,100]" in e for e in errors)),
        ("rx + lost <= tx for every flow", not any("exceeds" in e for e in errors)),
        ("Jain indices within [1/n, 1]",
         not any("jain" in e.lower() and "out of" in e for e in errors)),
        ("repeat run reproduces identical flow rows",
         not any("repeatability" in e for e in errors)),
    ]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if errors:
        for e in errors:
            print(f"  error: {e}")
        return 1
    print(f"\nwrote {FLOW_CSV}")
    print(f"wrote {SUMMARY_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
