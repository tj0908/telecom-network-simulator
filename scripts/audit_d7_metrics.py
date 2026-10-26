#!/usr/bin/env python3
"""D7.1 audit: metric-definition and accounting verification for D7.

Reads ONLY the saved D7 artifacts (results/d7_metrics.csv, the per-run
txt logs). It does not rerun any simulation and does not modify D7
inputs. It produces:
  results/d7_unified_window.csv  per-flow rates under a common window
  results/d7_audit.txt           this audit's full printed report

Questions audited:
  1. Why can the sum of per-flow throughputs exceed the 2 Mbps
     bottleneck (C/FIFO 2.1080, C/FqCoDel 2.0491)?
     -> Each flow's published rate divides by ITS OWN firstTx..lastRx
        span. Rates over different intervals are not additive.
        The audit adds a common-window rate per run: one window
        [min firstTx, max lastRx] shared by all flows of the run,
        rate = rxBytes * 8 / window_length. Every received byte crossed
        the bottleneck inside that window, so the sum of common-window
        rates cannot exceed the bottleneck capacity.
  2. Jain indices: the D7 headline indices use the per-flow-span
     rates. The audit recomputes them from common-window rates and
     reports both. The span version stays as the historical result.
  3. Queue counters: sampling position/period and counter sources are
     fixed in src/multiflow_fairness.cc; the audit cross-checks the
     printed sample counts and occupancy means against the CSVs.
  4. End-of-sim accounting per run:
     unreceived (sum tx-rx) = traced bottleneck drops
                            + end residue at the bottleneck
                            + remainder (in flight / queued elsewhere).
     Also cross-checks sum(FlowMonitor lostPackets) against the traced
     bottleneck drops: in this setup every data-flow drop happens at
     the instrumented bottleneck (access links are lossless and their
     queues never drop in these runs), so the two must agree.

Assertions (exit code 1 on any failure):
  * common-window rate sum <= bottleneck capacity (1e-4 rel. tolerance
    for the 0.1 ms timestamp resolution stored in the CSV)
  * unified Jain indices within [1/n, 1]
  * accounting identity holds with 0 <= remainder <= unreceived
  * rx + lost <= tx for every flow
  * sum(lostPackets) == qdisc_dropped + device_dropped per run
  * device queue dropped == 0 in all runs (measured property of D7)
  * occupancy sample count == 1199 and means match the run logs
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
FLOW_CSV = RESULTS / "d7_metrics.csv"
UNIFIED_CSV = RESULTS / "d7_unified_window.csv"
AUDIT_TXT = RESULTS / "d7_audit.txt"
BOTTLENECK_MBPS = 2.0

GROUPS = ["A", "B", "C"]
QUEUES = ["fifo", "fqcodel"]

out_lines = []


def log(msg=""):
    print(msg)
    out_lines.append(msg)


def jain(values):
    n = len(values)
    s = sum(values)
    sq = sum(v * v for v in values)
    return (s * s) / (n * sq) if n and sq else 0.0


def main() -> int:
    flows = list(csv.DictReader(open(FLOW_CSV, newline="")))
    failures = []

    def check(name, ok, detail=""):
        log(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" ({detail})" if detail else ""))
        if not ok:
            failures.append(name)

    runs = {}
    for r in flows:
        runs.setdefault((r["group"], r["queue"]), []).append(r)

    # ---------- 1. per-flow spans (the C runs are the reported case) --
    log("===== 1. per-flow measurement spans =====")
    log("published rate = rxBytes*8 / (lastRx - firstTx), per flow")
    for key in [("C", "fifo"), ("C", "fqcodel")]:
        rows = runs[key]
        log(f"-- {key[0]}/{key[1]} --")
        span_sum = 0.0
        for r in rows:
            span = float(r["last_rx_s"]) - float(r["first_tx_s"])
            span_sum += float(r["throughput_mbps"])
            log(f"  {r['flow']:<5} rxBytes={r['rx_bytes']:>8} "
                f"firstTx={float(r['first_tx_s']):.4f} "
                f"lastRx={float(r['last_rx_s']):.4f} span={span:.4f}s "
                f"rate={float(r['throughput_mbps']):.4f} Mbps")
        log(f"  sum of per-flow-span rates = {span_sum:.4f} Mbps "
            f"(bottleneck {BOTTLENECK_MBPS} Mbps; sum not bounded "
            f"because denominators differ per flow)")

    # ---------- 2. common-window rates + Jain comparison ---------------
    log("\n===== 2. common-window rates (one window per run) =====")
    unified_rows = []
    jain_table = []
    for group in GROUPS:
        for queue in QUEUES:
            rows = runs[(group, queue)]
            w0 = min(float(r["first_tx_s"]) for r in rows)
            w1 = max(float(r["last_rx_s"]) for r in rows)
            wlen = w1 - w0
            rates = {}
            for r in rows:
                rate = int(r["rx_bytes"]) * 8 / wlen / 1e6
                rates[r["flow"]] = rate
                unified_rows.append({
                    "group": group, "queue": queue, "flow": r["flow"],
                    "rx_bytes": r["rx_bytes"],
                    "window_start_s": f"{w0:.4f}", "window_end_s": f"{w1:.4f}",
                    "window_len_s": f"{wlen:.4f}",
                    "unified_throughput_mbps": f"{rate:.4f}",
                    "span_throughput_mbps": r["throughput_mbps"],
                })
            total = sum(rates.values())
            log(f"{group}/{queue}: window [{w0:.4f}, {w1:.4f}] len={wlen:.4f}s "
                f"rates={ {k: round(v, 4) for k, v in rates.items()} } "
                f"sum={total:.4f} Mbps")
            check(f"{group}/{queue} common-window sum <= capacity",
                  total <= BOTTLENECK_MBPS * (1 + 1e-4),
                  f"sum={total:.4f}")
            tcp_rates = [rates[f] for f in ("tcp1", "tcp2")]
            all_rates = list(rates.values())
            span_tcp = [float(r["throughput_mbps"]) for r in rows
                        if r["flow"] in ("tcp1", "tcp2")]
            span_all = [float(r["throughput_mbps"]) for r in rows]
            jt_u, ja_u = jain(tcp_rates), jain(all_rates)
            jt_s, ja_s = jain(span_tcp), jain(span_all)
            jain_table.append((group, queue, jt_s, jt_u, ja_s, ja_u,
                               len(all_rates)))
            check(f"{group}/{queue} jain_unified_tcp in [1/2, 1]",
                  0.5 - 1e-9 <= jt_u <= 1.0 + 1e-9, f"{jt_u:.4f}")
            check(f"{group}/{queue} jain_unified_all in [1/{len(all_rates)}, 1]",
                  1 / len(all_rates) - 1e-9 <= ja_u <= 1.0 + 1e-9,
                  f"{ja_u:.4f}")

    with open(UNIFIED_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(unified_rows[0].keys()),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(unified_rows)
    log("\nwrote results/d7_unified_window.csv")

    log("\n===== 3. Jain indices: per-flow-span vs common-window =====")
    log(f"{'run':<12}{'jain_tcp span':>14}{'jain_tcp win':>14}"
        f"{'jain_all span':>14}{'jain_all win':>14}")
    for g, q, jt_s, jt_u, ja_s, ja_u, _n in jain_table:
        log(f"{g + '/' + q:<12}{jt_s:>14.4f}{jt_u:>14.4f}"
            f"{ja_s:>14.4f}{ja_u:>14.4f}")

    # ---------- 4. accounting verification -----------------------------
    log("\n===== 4. end-of-simulation accounting per run =====")
    for group in GROUPS:
        for queue in QUEUES:
            rows = runs[(group, queue)]
            run = rows[0]
            tot_tx = sum(int(r["tx_packets"]) for r in rows)
            tot_rx = sum(int(r["rx_packets"]) for r in rows)
            unreceived = tot_tx - tot_rx
            qd = int(run["qdisc_dropped"])
            dd = int(run["device_dropped"])
            residual = int(run["qdisc_end"]) + int(run["device_end"])
            inflight = unreceived - qd - dd - residual
            sum_lost = sum(int(r["lost_packets"]) for r in rows)
            log(f"{group}/{queue}: tx={tot_tx} rx={tot_rx} "
                f"unreceived={unreceived} = qdisc_dropped {qd} "
                f"+ device_dropped {dd} + residual {residual} "
                f"(qdisc_end {run['qdisc_end']} + device_end "
                f"{run['device_end']}) + in_flight {inflight}; "
                f"sum(lostPackets)={sum_lost}")
            check(f"{group}/{queue} accounting identity, remainder in range",
                  0 <= inflight <= unreceived,
                  f"in_flight={inflight}")
            check(f"{group}/{queue} sum(lostPackets) == traced bottleneck drops",
                  sum_lost == qd + dd, f"{sum_lost} vs {qd + dd}")
            check(f"{group}/{queue} device queue dropped == 0", dd == 0)
            for r in rows:
                check(f"{group}/{queue}/{r['flow']} rx+lost <= tx",
                      int(r["rx_packets"]) + int(r["lost_packets"])
                      <= int(r["tx_packets"]))

    # ---------- 5. queue sampling cross-check --------------------------
    log("\n===== 5. queue sampling cross-check (run logs vs CSV) =====")
    log("source: src/multiflow_fairness.cc schedules a probe every 10 ms "
        "from t=0.01 s until t=12.0 s -> 1199 samples; the sampling "
        "window therefore includes the ~1 s before flows start at "
        "t=1.0 s (empty queues), which dilutes all means equally.")
    for group in GROUPS:
        for queue in QUEUES:
            txt = (RESULTS / f"d7_{group.lower()}_{queue}.txt").read_text()
            occ = [ln for ln in txt.splitlines()
                   if ln.startswith("queue_occupancy_samples=")][0]
            samples = int(occ.split("=")[1].split()[0])
            run = runs[(group, queue)][0]
            qm_csv = float(run["qdisc_occ_mean"])
            dm_csv = float(run["device_occ_mean"])
            qm_txt = float(occ.split("qdisc_mean=")[1].split()[0])
            dm_txt = float(occ.split("device_mean=")[1].split()[0])
            check(f"{group}/{queue} samples == 1199", samples == 1199,
                  f"{samples}")
            check(f"{group}/{queue} occupancy means match log vs CSV",
                  abs(qm_csv - qm_txt) <= 0.01 and abs(dm_csv - dm_txt) <= 0.01,
                  f"qdisc {qm_csv:.2f}/{qm_txt:.2f} dev {dm_csv:.2f}/{dm_txt:.2f}")

    log("\n===== audit summary =====")
    if failures:
        log(f"{len(failures)} ASSERTION(S) FAILED: {failures}")
    else:
        log("ALL AUDIT ASSERTIONS PASSED")
    AUDIT_TXT.write_text("\n".join(out_lines) + "\n")
    print(f"wrote {AUDIT_TXT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
