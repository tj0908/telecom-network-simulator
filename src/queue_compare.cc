// D5: queue management / bufferbloat comparison on the D2-D4 topology.
//
// Fixed load: UDP OnOff at 4 Mbps into a 2 Mbps bottleneck (n1 -> n2).
// Only the bottleneck egress queue configuration changes per scenario:
//
//   default     untouched system defaults (whatever the stack installs)
//   fqcodel100  root qdisc replaced by FqCoDelQueueDisc, MaxSize=100p
//   fifo100     root qdisc replaced by PfifoFastQueueDisc, MaxSize=100p
//   devq100     root qdisc removed; device DropTail queue only (100p)
//   devq10      root qdisc removed; device DropTail queue MaxSize=10p
//
// For every run the program reads back the ACTUAL configuration from the
// stack (TrafficControl root qdisc on the bottleneck device + the device
// queue), samples both queues' occupancy every 10 ms, and afterwards
// reports drop counters of BOTH layers next to FlowMonitor's lostPackets,
// so the layer at which packets die is measured, not assumed.

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
#include <string>

using namespace ns3;

namespace {

struct QueueProbe {
    Ptr<QueueDisc> qdisc;          // may be null (qdisc removed)
    Ptr<Queue<Packet>> devQueue;   // device queue of bottleneck device
    uint64_t samples = 0;
    uint64_t qdiscSum = 0;
    uint32_t qdiscMax = 0;
    uint64_t devSum = 0;
    uint32_t devMax = 0;
};

void SampleQueue(QueueProbe* probe)
{
    if (Simulator::Now() >= Seconds(10.0)) {
        return;
    }
    uint32_t q = 0;
    if (probe->qdisc) {
        q = probe->qdisc->GetCurrentSize().GetValue();
    }
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
    std::string protocol = "udp";
    std::string bottleneck = "2Mbps";
    std::string delay = "10ms";
    std::string scenario = "default";
    std::string csvFile;

    CommandLine cmd;
    cmd.AddValue("protocol", "tcp or udp", protocol);
    cmd.AddValue("bottleneck", "Middle link rate", bottleneck);
    cmd.AddValue("delay", "Middle link delay", delay);
    cmd.AddValue("scenario", "default|fqcodel100|fifo100|devq100|devq10", scenario);
    cmd.AddValue("csvfile", "Append metrics to this CSV file", csvFile);
    cmd.Parse(argc, argv);

    if (protocol != "tcp" && protocol != "udp") {
        std::cerr << "Protocol must be tcp or udp\n";
        return 1;
    }
    if (scenario != "default" && scenario != "fqcodel100" && scenario != "fifo100"
        && scenario != "devq100" && scenario != "devq10") {
        std::cerr << "Unknown scenario: " << scenario << "\n";
        return 1;
    }

    NodeContainer nodes;
    nodes.Create(4);

    InternetStackHelper internet;
    internet.Install(nodes);

    PointToPointHelper edge;
    edge.SetDeviceAttribute("DataRate", StringValue("10Mbps"));
    edge.SetChannelAttribute("Delay", StringValue("2ms"));

    PointToPointHelper middle;
    middle.SetDeviceAttribute("DataRate", StringValue(bottleneck));
    middle.SetChannelAttribute("Delay", StringValue(delay));

    NodeContainer n01(nodes.Get(0), nodes.Get(1));
    NodeContainer n12(nodes.Get(1), nodes.Get(2));
    NodeContainer n23(nodes.Get(2), nodes.Get(3));

    auto d01 = edge.Install(n01);
    auto d12 = middle.Install(n12);
    auto d23 = edge.Install(n23);

    Ipv4AddressHelper address;
    address.SetBase("10.1.1.0", "255.255.255.0");
    address.Assign(d01);
    address.SetBase("10.1.2.0", "255.255.255.0");
    address.Assign(d12);
    address.SetBase("10.1.3.0", "255.255.255.0");
    auto receiverIf = address.Assign(d23);

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // ---- bottleneck queue configuration (egress of n1 towards n2) ----
    Ptr<PointToPointNetDevice> bottleneckDev =
        DynamicCast<PointToPointNetDevice>(d12.Get(0));
    NetDeviceContainer bottleneckDevs(bottleneckDev);

    if (scenario == "fqcodel100" || scenario == "fifo100"
        || scenario == "devq100" || scenario == "devq10") {
        TrafficControlHelper tch;
        tch.Uninstall(bottleneckDevs);
        if (scenario == "fqcodel100") {
            tch.SetRootQueueDisc(
                "ns3::FqCoDelQueueDisc",
                "MaxSize", QueueSizeValue(QueueSize("100p")));
            tch.Install(bottleneckDevs);
        } else if (scenario == "fifo100") {
            tch.SetRootQueueDisc(
                "ns3::PfifoFastQueueDisc",
                "MaxSize", QueueSizeValue(QueueSize("100p")));
            tch.Install(bottleneckDevs);
        } else if (scenario == "devq10") {
            bottleneckDev->GetQueue()->SetMaxSize(QueueSize("10p"));
        }
        // devq100: nothing more; the default 100p device queue remains.
    }

    // ---- read back the actual configuration ----
    Ptr<TrafficControlLayer> tcLayer = nodes.Get(1)->GetObject<TrafficControlLayer>();
    Ptr<QueueDisc> qdisc;
    std::string qdiscDesc = "none";
    if (tcLayer) {
        qdisc = tcLayer->GetRootQueueDiscOnDevice(d12.Get(0));
        if (qdisc) {
            QueueSizeValue qsv;
            qdisc->GetAttribute("MaxSize", qsv);
            qdiscDesc = qdisc->GetInstanceTypeId().GetName()
                      + " MaxSize=" + QueueSizeStr(qsv.Get());
        }
    }
    Ptr<Queue<Packet>> devQueue = bottleneckDev->GetQueue();
    std::string devQueueDesc = devQueue->GetInstanceTypeId().GetName()
                             + " MaxSize=" + QueueSizeStr(devQueue->GetMaxSize());

    // ---- applications (same as D3/D4) ----
    const uint16_t port = 9000;
    std::string socketType =
        protocol == "tcp" ? "ns3::TcpSocketFactory" : "ns3::UdpSocketFactory";

    PacketSinkHelper sink(socketType, InetSocketAddress(Ipv4Address::GetAny(), port));
    auto sinkApps = sink.Install(nodes.Get(3));
    sinkApps.Start(Seconds(0.5));
    sinkApps.Stop(Seconds(10.0));

    ApplicationContainer senderApps;
    if (protocol == "tcp") {
        BulkSendHelper sender(socketType, InetSocketAddress(receiverIf.GetAddress(1), port));
        sender.SetAttribute("MaxBytes", UintegerValue(0));
        sender.SetAttribute("SendSize", UintegerValue(1024));
        senderApps = sender.Install(nodes.Get(0));
    } else {
        OnOffHelper sender(socketType, InetSocketAddress(receiverIf.GetAddress(1), port));
        sender.SetAttribute("DataRate", StringValue("4Mbps"));
        sender.SetAttribute("PacketSize", UintegerValue(1024));
        sender.SetAttribute("OnTime", StringValue("ns3::ConstantRandomVariable[Constant=1]"));
        sender.SetAttribute("OffTime", StringValue("ns3::ConstantRandomVariable[Constant=0]"));
        senderApps = sender.Install(nodes.Get(0));
    }
    senderApps.Start(Seconds(1.0));
    senderApps.Stop(Seconds(9.0));

    QueueProbe probe;
    probe.qdisc = qdisc;
    probe.devQueue = devQueue;

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();

    Simulator::Schedule(MilliSeconds(10), &SampleQueue, &probe);
    Simulator::Stop(Seconds(10.0));
    Simulator::Run();
    monitor->CheckForLostPackets();

    // ---- drop counters of both layers ----
    uint64_t qdiscEnqueued = 0, qdiscDropped = 0;
    bool hasQdisc = static_cast<bool>(qdisc);
    if (qdisc) {
        auto st = qdisc->GetStats();
        qdiscEnqueued = st.nTotalEnqueuedPackets;
        qdiscDropped = st.nTotalDroppedPackets;
    }
    // ns-3 3.41 QueueBase has no GetStats(); it exposes individual
    // counters, including a before-enqueue / after-dequeue drop split.
    uint32_t devReceived = devQueue->GetTotalReceivedPackets();
    uint32_t devDropped = devQueue->GetTotalDroppedPackets();
    uint32_t devDroppedBeforeEnqueue = devQueue->GetTotalDroppedPacketsBeforeEnqueue();
    // End-of-simulation residue at the bottleneck (for the D6 accounting
    // of unreceived = confirmed drops + queued residue + in flight).
    uint32_t qdiscEndSize = qdisc ? qdisc->GetCurrentSize().GetValue() : 0;
    uint32_t devEndSize = devQueue->GetNPackets();

    // ---- FlowMonitor data flow ----
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    auto stats = monitor->GetFlowStats();

    uint64_t tx = 0, rx = 0, lost = 0, rxBytes = 0;
    double avgDelayMs = 0, avgJitterMs = 0, lossPct = 0, span = 0, thr = 0;
    double firstTx = 0, lastRx = 0;
    for (auto& pair : stats) {
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(pair.first);
        if (tuple.destinationPort != port) {
            continue; // data flow only
        }
        const FlowMonitor::FlowStats& s = pair.second;
        tx = s.txPackets;
        rx = s.rxPackets;
        lost = s.lostPackets;
        rxBytes = s.rxBytes;
        avgDelayMs = rx > 0 ? s.delaySum.GetSeconds() / rx * 1000.0 : 0.0;
        avgJitterMs = rx > 1 ? s.jitterSum.GetSeconds() / (rx - 1) * 1000.0 : 0.0;
        lossPct = tx > 0 ? 100.0 * lost / tx : 0.0;
        firstTx = s.timeFirstTxPacket.GetSeconds();
        lastRx = s.timeLastRxPacket.GetSeconds();
        span = (s.timeLastRxPacket - s.timeFirstTxPacket).GetSeconds();
        thr = span > 0 ? rxBytes * 8.0 / span / 1000000.0 : 0.0;
    }

    double qdiscMean = probe.samples ? (double)probe.qdiscSum / probe.samples : 0.0;
    double devMean = probe.samples ? (double)probe.devSum / probe.samples : 0.0;

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "scenario=" << scenario << " protocol=" << protocol
              << " bottleneck=" << bottleneck << " delay=" << delay << "\n";
    std::cout << "actual_qdisc: " << qdiscDesc << "\n";
    std::cout << "actual_device_queue: " << devQueueDesc << "\n";
    std::cout << "flowmonitor: txPackets=" << tx << " rxPackets=" << rx
              << " lostPackets=" << lost << " loss_rate_pct=" << lossPct
              << " rxBytes=" << rxBytes << "\n";
    std::cout << "flowmonitor: avg_delay_ms=" << avgDelayMs
              << " avg_jitter_ms=" << avgJitterMs
              << " firstTx=" << firstTx << " lastRx=" << lastRx
              << " rx_span_s=" << span
              << " throughput_mbps=" << thr << "\n";
    std::cout << "qdisc_counters: present=" << (hasQdisc ? "yes" : "no")
              << " enqueued=" << qdiscEnqueued
              << " dropped=" << qdiscDropped << "\n";
    std::cout << "device_queue_counters: received=" << devReceived
              << " dropped=" << devDropped
              << " dropped_before_enqueue=" << devDroppedBeforeEnqueue << "\n";
    std::cout << "queue_occupancy_samples=" << probe.samples
              << " qdisc_max=" << probe.qdiscMax << " qdisc_mean=" << qdiscMean
              << " device_max=" << probe.devMax << " device_mean=" << devMean << "\n";
    // D6 accounting: tx - rx ("unreceived") is NOT the same as drops.
    // Split it into traced drops, packets still queued at the bottleneck
    // when the simulation ended, and a remainder that was in flight on
    // links or in downstream queues at that moment.
    uint64_t unreceived = tx - rx;
    uint64_t confirmedDropped = qdiscDropped + devDropped;
    uint64_t residualBottleneck = qdiscEndSize + devEndSize;
    int64_t inFlightOrDownstream =
        (int64_t)unreceived - (int64_t)confirmedDropped - (int64_t)residualBottleneck;
    std::cout << "accounting: unreceived=" << unreceived
              << " confirmed_dropped=" << confirmedDropped
              << " residual_bottleneck_queue=" << residualBottleneck
              << " (qdisc_end=" << qdiscEndSize
              << " device_end=" << devEndSize << ")"
              << " in_flight_or_downstream=" << inFlightOrDownstream << "\n";

    if (!csvFile.empty()) {
        bool needHeader = true;
        std::ifstream test(csvFile);
        if (test.good() && test.peek() != std::ifstream::traits_type::eof()) {
            needHeader = false;
        }
        test.close();
        std::ofstream csv(csvFile, std::ios::app);
        if (needHeader) {
            csv << "scenario,protocol,bottleneck,qdisc,device_queue,"
                   "tx_packets,rx_packets,lost_packets,loss_rate_pct,rx_bytes,"
                   "avg_delay_ms,avg_jitter_ms,throughput_mbps,"
                   "qdisc_enqueued,qdisc_dropped,device_received,device_dropped,"
                   "qdisc_occ_max,qdisc_occ_mean,device_occ_max,device_occ_mean,"
                   "first_tx_s,last_rx_s,rx_span_s\n";
        }
        csv << scenario << "," << protocol << "," << bottleneck << ","
            << qdiscDesc << "," << devQueueDesc << ","
            << tx << "," << rx << "," << lost << "," << lossPct << "," << rxBytes << ","
            << avgDelayMs << "," << avgJitterMs << "," << thr << ","
            << qdiscEnqueued << "," << qdiscDropped << ","
            << devReceived << "," << devDropped << ","
            << probe.qdiscMax << "," << qdiscMean << ","
            << probe.devMax << "," << devMean << ","
            << firstTx << "," << lastRx << "," << span << "\n";
    }

    Simulator::Destroy();
    return 0;
}
