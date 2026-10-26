#!/usr/bin/env bash
# D6 final regression: rebuild all programs with the README commands and
# verify that the saved D1-D5 results reproduce exactly.
# Prints a PASS/FAIL line per check; exit code is non-zero on any FAIL.
set -u
cd "$(dirname "$0")/.."

FAILURES=0
pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }
check_eq() { # name expected actual
    if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected: $2 | got: $3)"; fi
}

PKGS="ns3-core ns3-network ns3-internet ns3-point-to-point ns3-applications"
PKGS_FM="$PKGS ns3-flow-monitor ns3-traffic-control"

echo "===== build ====="
g++ -std=c++17 -O0 -g0 src/udp_baseline.cc -o udp_baseline \
    $(pkg-config --cflags --libs $PKGS) 2>/dev/null \
    && pass "build udp_baseline" || fail "build udp_baseline"
g++ -std=c++17 -O0 -g0 src/tcp_udp_compare.cc -o tcp_udp_compare \
    $(pkg-config --cflags --libs $PKGS) 2>/dev/null \
    && pass "build tcp_udp_compare" || fail "build tcp_udp_compare"
g++ -std=c++17 -O0 -g0 src/flow_metrics.cc -o flow_metrics \
    $(pkg-config --cflags --libs $PKGS_FM) 2>/dev/null \
    && pass "build flow_metrics" || fail "build flow_metrics"
g++ -std=c++17 -O0 -g0 src/queue_compare.cc -o queue_compare \
    $(pkg-config --cflags --libs $PKGS_FM) 2>/dev/null \
    && pass "build queue_compare" || fail "build queue_compare"

echo "===== D1 ====="
check_eq "D1 udp_baseline output" \
    "UDP packets received: 100" "$(./udp_baseline)"

echo "===== D2 ====="
./tcp_udp_compare --protocol=tcp --bottleneck=2Mbps > /tmp/reg_d2_tcp.txt
diff -q /tmp/reg_d2_tcp.txt results/d2_tcp_2mbps.txt >/dev/null \
    && pass "D2 tcp@2Mbps reproduces saved result" || fail "D2 tcp@2Mbps diff"
./tcp_udp_compare --protocol=udp --bottleneck=2Mbps > /tmp/reg_d2_udp.txt
diff -q /tmp/reg_d2_udp.txt results/d2_udp_2mbps.txt >/dev/null \
    && pass "D2 udp@2Mbps reproduces saved result" || fail "D2 udp@2Mbps diff"

echo "===== D3 ====="
rm -f /tmp/reg_d3.csv
./flow_metrics --protocol=udp --bottleneck=2Mbps \
    --csvfile=/tmp/reg_d3.csv > /tmp/reg_d3.txt
grep -q "lostPackets=1743" /tmp/reg_d3.txt \
    && pass "D3 udp@2Mbps FlowMonitor lostPackets=1743" || fail "D3 udp@2Mbps metrics"

echo "===== D4 ====="
cp results/d4_metrics.csv /tmp/reg_d4_before.csv
# run_experiments.py exits 1 if any of its 5 validation checks fails
if python3 scripts/run_experiments.py > /tmp/reg_d4_log.txt 2>&1; then
    pass "D4 run_experiments validation"
else
    fail "D4 run_experiments validation"
fi
diff -q /tmp/reg_d4_before.csv results/d4_metrics.csv >/dev/null \
    && pass "D4 metrics identical to saved CSV" || fail "D4 metrics diff"

echo "===== D5 ====="
cp results/d5_metrics.csv /tmp/reg_d5_before.csv
python3 scripts/run_queue_experiments.py > /tmp/reg_d5_log.txt 2>&1 \
    && pass "D5 queue experiments run" || fail "D5 queue experiments run"
diff -q /tmp/reg_d5_before.csv results/d5_metrics.csv >/dev/null \
    && pass "D5 metrics identical to saved CSV" || fail "D5 metrics diff"
grep -q "accounting: unreceived=1776 confirmed_dropped=1743 residual_bottleneck_queue=29" \
    results/d5_default.txt \
    && pass "D5 default accounting reconciles (1743 dropped + 29 residual + 4 in flight)" \
    || fail "D5 default accounting"

echo "===== figures ====="
python3 scripts/plot_results.py > /tmp/reg_plot1.txt 2>&1 \
    && python3 scripts/plot_queue_results.py > /tmp/reg_plot2.txt 2>&1
FIGS=$(ls results/figures/*.png 2>/dev/null | wc -l)
if [ "$FIGS" -ge 6 ]; then pass "figures generated ($FIGS png files)"; else fail "figures count=$FIGS"; fi

echo "===== summary ====="
if [ "$FAILURES" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "$FAILURES CHECK(S) FAILED"
    exit 1
fi
