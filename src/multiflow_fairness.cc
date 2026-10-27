// D7: multi-flow competition and fairness on a dumbbell topology.
//
//   L0 --\                       /-- S0
//   L1 ---- R0 === bottleneck === R1 ---- S1
//   L2 --/                       \-- S2
//
// Access links: 10 Mbps / 2 ms. Bottleneck R0->R1: 2 Mbps / 10 ms
// (same bottleneck as D4/D5 so results stay comparable).
//
// Flows (all cross the bottleneck):
//   flow tcp1: L0 -> S0, TCP BulkSend            (destination port 9001)
//   flow tcp2: L1 -> S1, TCP BulkSend            (destination port 9002)
//   flow udp : L2 -> S2, UDP OnOff constant rate (destination port 9003)
//
// Groups (controlled variable: UDP offered load):
//   A  no UDP flow          B  UDP 500 kbps       C  UDP 4 Mbps
// Queue policies (controlled variable, applied to R0->R1 egress only):
//   fifo     PfifoFastQueueDisc MaxSize=100p
//   fqcodel  FqCoDelQueueDisc  MaxSize=100p
// In both cases the PointToPoint device queue stays the default
// DropTail 100p, mirroring the two-layer structure measured in D5:
// only the queue discipline differs, capacities are identical.
//
// Per flow the program reports FlowMonitor (IP layer) tx/rx/lost,
// throughput over the flow's own firstTx..lastRx span, mean delay and
// the unreceived ratio (tx-rx)/tx. NOTE: unreceived is NOT "dropped":
// it also counts packets still queued or in flight at simulation end.
// The bottleneck queue counters of both layers, their end-of-sim
// residue, and an aggregate accounting line are printed so the split
// can be checked like in D6. Reverse-direction (ACK) queues are not
// instrumented; data packets overwhelmingly die at the forward
// bottleneck queue, which is the instrumented one.
//
// Simulation: 12 s; flows run 1.0 s .. 11.0 s (10 s activity window,
// longer than D2-D5 so competing TCP flows can settle).
// Default ns-3 seed: deterministic, repeat runs are identical.

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/traffic-control-module.h"

#include <algorithm>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <map>
#include <string>

using namespace ns3;

namespace {

struct QueueProbe {
    Ptr<QueueDisc> qdisc;
    Ptr<Queue<Packet>> devQueue;
    uint64_t samples = 0;
    uint64_t qdiscSum = 0;
    uint32_t qdiscMax = 0;
    uint64_t devSum = 0;
    uint32_t devMax = 0;
};

void SampleQueue(QueueProbe* probe)
{
    if (Simulator::Now() >= Seconds(12.0)) {
        return;
    }
    uint32_t q = probe->qdisc ? probe->qdisc->GetCurrentSize().GetValue() : 0;
    uint32_t d = probe->devQueue ? probe->devQueue->GetNPackets() : 0;
    probe->samples++;
    probe->qdiscSum += q;
    probe->qdiscMax = std::max(probe->qdiscMax, q);
    probe->devSum += d;
    probe->devMax = std::max(probe->devMax, d);
    Simulator::Schedule(MilliSeconds(10), &SampleQueue, probe);
}

std::string QueueSizeStr(const QueueSize& qs)
{
    return std::to_string(qs.GetValue())
         + (qs.GetUnit() == QueueSizeUnit::PACKETS ? "p" : "B");
}

} // namespace

int main(int argc, char* argv[])
{
    std::string group = "A";       // A | B | C
    std::string queue = "fifo";    // fifo | fqcodel
    std::string bottleneck = "2Mbps";
    uint32_t seed = 0;             // 0 = legacy behaviour (no RNG use)
    std::string csvFile;

    CommandLine cmd;
    cmd.AddValue("group", "A (no UDP) | B (UDP 500kbps) | C (UDP 4Mbps)", group);
    cmd.AddValue("queue", "fifo | fqcodel (bottleneck egress policy)", queue);
    cmd.AddValue("bottleneck", "Bottleneck link rate (default 2Mbps)", bottleneck);
    cmd.AddValue("seed", "0 = legacy deterministic run; >=1 enables seeded "
                         "per-flow start-time jitter in [0, 0.2] s", seed);
    cmd.AddValue("csvfile", "Append per-flow metrics to this CSV file", csvFile);
    cmd.Parse(argc, argv);

    if (group != "A" && group != "B" && group != "C") {
        std::cerr << "Unknown group: " << group << "\n";
        return 1;
    }
    if (queue != "fifo" && queue != "fqcodel") {
        std::cerr << "Unknown queue: " << queue << "\n";
        return 1;
    }
    const bool hasUdp = (group != "A");
    const std::string udpRate = (group == "B") ? "500kbps" : "4Mbps";

    // ---- nodes: 0-2 senders, 3 = R0, 4 = R1, 5-7 receivers ----
    NodeContainer senders, receivers, routers;
    senders.Create(3);
    routers.Create(2);
    receivers.Create(3);
    NodeContainer all = NodeContainer(senders, routers, receivers);

    InternetStackHelper internet;
    internet.Install(all);

    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    access.SetChannelAttribute("Delay", StringValue("2ms"));
    PointToPointHelper middle;
    middle.SetDeviceAttribute("DataRate", StringValue(bottleneck));
    middle.SetChannelAttribute("Delay", StringValue("10ms"));

    Ipv4AddressHelper address;
    NetDeviceContainer bottleneckDevs;
    Ipv4InterfaceContainer receiverIf[3];
    int subnet = 1;
    auto assign = [&](NetDeviceContainer devs) {
        std::string base = "10.1." + std::to_string(subnet++) + ".0";
        address.SetBase(base.c_str(), "255.255.255.0");
        return address.Assign(devs);
    };

    for (int i = 0; i < 3; i++) {
        assign(access.Install(senders.Get(i), routers.Get(0)));
    }
    bottleneckDevs = middle.Install(routers.Get(0), routers.Get(1));
    assign(bottleneckDevs);
    for (int i = 0; i < 3; i++) {
        receiverIf[i] = assign(access.Install(routers.Get(1), receivers.Get(i)));
    }
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // ---- bottleneck queue policy on R0 -> R1 egress ----
    Ptr<PointToPointNetDevice> bottleneckDev =
        DynamicCast<PointToPointNetDevice>(bottleneckDevs.Get(0));
    NetDeviceContainer egressDev(bottleneckDev);
    {
        TrafficControlHelper tch;
        tch.Uninstall(egressDev);
        if (queue == "fifo") {
            tch.SetRootQueueDisc("ns3::PfifoFastQueueDisc",
                                 "MaxSize", QueueSizeValue(QueueSize("100p")));
        } else {
            tch.SetRootQueueDisc("ns3::FqCoDelQueueDisc",
                                 "MaxSize", QueueSizeValue(QueueSize("100p")));
        }
        tch.Install(egressDev);
    }

    // ---- read back actual configuration ----
    Ptr<TrafficControlLayer> tcLayer =
        routers.Get(0)->GetObject<TrafficControlLayer>();
    Ptr<QueueDisc> qdisc = tcLayer->GetRootQueueDiscOnDevice(bottleneckDevs.Get(0));
    std::string qdiscDesc = "none";
    if (qdisc) {
        QueueSizeValue qsv;
        qdisc->GetAttribute("MaxSize", qsv);
        qdiscDesc = qdisc->GetInstanceTypeId().GetName()
                  + " MaxSize=" + QueueSizeStr(qsv.Get());
    }
    Ptr<Queue<Packet>> devQueue = bottleneckDev->GetQueue();
    std::string devQueueDesc = devQueue->GetInstanceTypeId().GetName()
                             + " MaxSize=" + QueueSizeStr(devQueue->GetMaxSize());

    // ---- optional seeded start-time jitter (upgrade phase 2) ----
    // Legacy mode (seed == 0): RNG is never touched and every flow
    // starts at exactly 1.0 s, reproducing the saved D7 results.
    // Seeded mode: RngSeedManager Seed is fixed at 1 and the run number
    // is the seed; one UniformRandomVariable on a dedicated stream
    // draws one start offset per flow from [0, 0.2] s. This jitter is
    // the ONLY stochastic element of the seeded experiments: it
    // perturbs the phase alignment between the competing flows.
    // Stop times are unchanged (11.0 s for every flow).
    double startOffset[3] = {0.0, 0.0, 0.0};
    if (seed > 0) {
        RngSeedManager::SetSeed(1);
        RngSeedManager::SetRun(seed);
        Ptr<UniformRandomVariable> urv = CreateObject<UniformRandomVariable>();
        urv->SetStream(100);
        for (int i = 0; i < 3; i++) {
            startOffset[i] = urv->GetValue(0.0, 0.2);
        }
    }

    // ---- applications ----
    const uint16_t ports[3] = {9001, 9002, 9003};
    for (int i = 0; i < 3; i++) {
        bool isUdp = (i == 2);
        std::string socketType =
            isUdp ? "ns3::UdpSocketFactory" : "ns3::TcpSocketFactory";
        PacketSinkHelper sink(socketType,
                              InetSocketAddress(Ipv4Address::GetAny(), ports[i]));
        auto sinkApp = sink.Install(receivers.Get(i));
        sinkApp.Start(Seconds(0.5));
        sinkApp.Stop(Seconds(12.0));

        if (isUdp && !hasUdp) {
            continue; // group A: no UDP flow at all
        }
        ApplicationContainer senderApp;
        InetSocketAddress dst(receiverIf[i].GetAddress(1), ports[i]);
        if (isUdp) {
            OnOffHelper sender(socketType, dst);
            sender.SetAttribute("DataRate", StringValue(udpRate));
            sender.SetAttribute("PacketSize", UintegerValue(1024));
            sender.SetAttribute("OnTime",
                                StringValue("ns3::ConstantRandomVariable[Constant=1]"));
            sender.SetAttribute("OffTime",
                                StringValue("ns3::ConstantRandomVariable[Constant=0]"));
            senderApp = sender.Install(senders.Get(i));
        } else {
            BulkSendHelper sender(socketType, dst);
            sender.SetAttribute("MaxBytes", UintegerValue(0));
            sender.SetAttribute("SendSize", UintegerValue(1024));
            senderApp = sender.Install(senders.Get(i));
        }
        senderApp.Start(Seconds(1.0 + startOffset[i]));
        senderApp.Stop(Seconds(11.0));
    }

    QueueProbe probe;
    probe.qdisc = qdisc;
    probe.devQueue = devQueue;

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
    // Collect the per-flow delay histogram so a P95 can be derived.
    // Bin width 0.5 ms: the reported P95 is the right edge of the first
    // bin whose cumulative count reaches 95% of received packets, i.e.
    // an approximation with at most one bin width (0.5 ms) of error.
    monitor->SetAttribute("DelayBinWidth", DoubleValue(0.0005));

    Simulator::Schedule(MilliSeconds(10), &SampleQueue, &probe);
    Simulator::Stop(Seconds(12.0));
    Simulator::Run();
    monitor->CheckForLostPackets();

    // ---- bottleneck queue counters (both layers, forward direction) ----
    auto qstats = qdisc->GetStats();
    uint64_t qdiscEnqueued = qstats.nTotalEnqueuedPackets;
    uint64_t qdiscDropped = qstats.nTotalDroppedPackets;
    uint32_t devReceived = devQueue->GetTotalReceivedPackets();
    uint32_t devDropped = devQueue->GetTotalDroppedPackets();
    uint32_t qdiscEnd = qdisc->GetCurrentSize().GetValue();
    uint32_t devEnd = devQueue->GetNPackets();

    // ---- per-flow metrics (data flows identified by destination port) ----
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    auto stats = monitor->GetFlowStats();

    struct Row {
        std::string flow, protocol;
        uint64_t tx = 0, rx = 0, lost = 0, rxBytes = 0;
        double lossPct = 0, unreceivedPct = 0, avgDelayMs = 0, thr = 0;
        double firstTx = 0, lastRx = 0;
        double p95DelayMs = 0;
    };
    std::map<uint16_t, Row> rows;
    rows[9001] = {"tcp1", "tcp"};
    rows[9002] = {"tcp2", "tcp"};
    if (hasUdp) {
        rows[9003] = {"udp", "udp"};
    }
    for (auto& pair : stats) {
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(pair.first);
        auto it = rows.find(tuple.destinationPort);
        if (it == rows.end()) {
            continue;
        }
        const FlowMonitor::FlowStats& s = pair.second;
        Row& r = it->second;
        r.tx = s.txPackets;
        r.rx = s.rxPackets;
        r.lost = s.lostPackets;
        r.rxBytes = s.rxBytes;
        r.lossPct = s.txPackets > 0 ? 100.0 * s.lostPackets / s.txPackets : 0.0;
        r.unreceivedPct =
            s.txPackets > 0 ? 100.0 * (s.txPackets - s.rxPackets) / s.txPackets : 0.0;
        r.avgDelayMs =
            s.rxPackets > 0 ? s.delaySum.GetSeconds() / s.rxPackets * 1000.0 : 0.0;
        r.firstTx = s.timeFirstTxPacket.GetSeconds();
        r.lastRx = s.timeLastRxPacket.GetSeconds();
        double span = (s.timeLastRxPacket - s.timeFirstTxPacket).GetSeconds();
        r.thr = span > 0 ? s.rxBytes * 8.0 / span / 1000000.0 : 0.0;
        // P95 of per-packet end-to-end delay from the delay histogram
        // (bin width 0.5 ms, set via DelayBinWidth above).
        const Histogram& hist = s.delayHistogram;
        uint64_t histTotal = 0;
        for (uint32_t b = 0; b < hist.GetNBins(); b++) {
            histTotal += hist.GetBinCount(b);
        }
        if (histTotal > 0) {
            double target = 0.95 * histTotal;
            uint64_t cum = 0;
            for (uint32_t b = 0; b < hist.GetNBins(); b++) {
                cum += hist.GetBinCount(b);
                if (cum >= target) {
                    r.p95DelayMs = hist.GetBinEnd(b) * 1000.0;
                    break;
                }
            }
        }
    }

    double qdiscMean = probe.samples ? (double)probe.qdiscSum / probe.samples : 0.0;
    double devMean = probe.samples ? (double)probe.devSum / probe.samples : 0.0;

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "group=" << group << " queue=" << queue
              << " udp_rate=" << (hasUdp ? udpRate : "none")
              << " bottleneck=" << bottleneck << "\n";
    if (seed > 0) {
        std::cout << "seed=" << seed << " start_offsets_s="
                  << startOffset[0] << "," << startOffset[1] << ","
                  << startOffset[2] << "\n";
    }
    std::cout << "actual_qdisc: " << qdiscDesc << "\n";
    std::cout << "actual_device_queue: " << devQueueDesc << "\n";
    uint64_t totTx = 0, totRx = 0;
    for (auto& kv : rows) {
        const Row& r = kv.second;
        totTx += r.tx;
        totRx += r.rx;
        std::cout << "flow=" << r.flow << " protocol=" << r.protocol
                  << " txPackets=" << r.tx << " rxPackets=" << r.rx
                  << " lostPackets=" << r.lost
                  << " loss_rate_pct=" << r.lossPct
                  << " unreceived_pct=" << r.unreceivedPct
                  << " avg_delay_ms=" << r.avgDelayMs
                  << " p95_delay_ms=" << r.p95DelayMs
                  << " rxBytes=" << r.rxBytes
                  << " throughput_mbps=" << r.thr
                  << " firstTx=" << r.firstTx << " lastRx=" << r.lastRx << "\n";
    }
    std::cout << "qdisc_counters: enqueued=" << qdiscEnqueued
              << " dropped=" << qdiscDropped << "\n";
    std::cout << "device_queue_counters: received=" << devReceived
              << " dropped=" << devDropped << "\n";
    std::cout << "queue_occupancy_samples=" << probe.samples
              << " qdisc_max=" << probe.qdiscMax << " qdisc_mean=" << qdiscMean
              << " device_max=" << probe.devMax << " device_mean=" << devMean << "\n";
    // Aggregate accounting over the forward data flows (same split as D6):
    // unreceived = traced drops at the bottleneck + end residue there +
    // remainder still in flight / queued elsewhere at simulation end.
    uint64_t unreceived = totTx - totRx;
    uint64_t confirmedDropped = qdiscDropped + devDropped;
    uint64_t residual = qdiscEnd + devEnd;
    int64_t inFlight = (int64_t)unreceived - (int64_t)confirmedDropped
                     - (int64_t)residual;
    std::cout << "accounting: unreceived_total=" << unreceived
              << " confirmed_dropped_bottleneck=" << confirmedDropped
              << " residual_bottleneck_queue=" << residual
              << " (qdisc_end=" << qdiscEnd << " device_end=" << devEnd << ")"
              << " in_flight_or_elsewhere=" << inFlight << "\n";

    if (!csvFile.empty()) {
        bool needHeader = true;
        std::ifstream test(csvFile);
        if (test.good() && test.peek() != std::ifstream::traits_type::eof()) {
            needHeader = false;
        }
        test.close();
        std::ofstream csv(csvFile, std::ios::app);
        if (needHeader) {
            csv << "group,queue,udp_rate,flow,protocol,tx_packets,rx_packets,"
                   "lost_packets,loss_rate_pct,unreceived_pct,avg_delay_ms,"
                   "rx_bytes,throughput_mbps,first_tx_s,last_rx_s,"
                   "qdisc,device_queue,qdisc_enqueued,qdisc_dropped,"
                   "device_received,device_dropped,qdisc_occ_mean,qdisc_occ_max,"
                   "device_occ_mean,device_occ_max,qdisc_end,device_end,"
                   "p95_delay_ms,seed,bottleneck,start_offset_s\n";
        }
        size_t flowIdx = 0;
        for (auto& kv : rows) {
            const Row& r = kv.second;
            csv << group << "," << queue << "," << (hasUdp ? udpRate : "none")
                << "," << r.flow << "," << r.protocol << ","
                << r.tx << "," << r.rx << "," << r.lost << ","
                << r.lossPct << "," << r.unreceivedPct << "," << r.avgDelayMs
                << "," << r.rxBytes << "," << r.thr << ","
                << r.firstTx << "," << r.lastRx << ","
                << qdiscDesc << "," << devQueueDesc << ","
                << qdiscEnqueued << "," << qdiscDropped << ","
                << devReceived << "," << devDropped << ","
                << qdiscMean << "," << probe.qdiscMax << ","
                << devMean << "," << probe.devMax << ","
                << qdiscEnd << "," << devEnd << ","
                << r.p95DelayMs << "," << seed << "," << bottleneck << ","
                << startOffset[flowIdx++] << "\n";
        }
    }

    Simulator::Destroy();
    return 0;
}
