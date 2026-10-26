// D3: FlowMonitor-based per-flow metrics on the D2 bottleneck topology.
//
// Same 4-node topology and TCP/UDP applications as tcp_udp_compare.cc,
// plus ns-3 FlowMonitor (IP layer) statistics:
//   txPackets / rxPackets / lostPackets / rxBytes / delaySum / jitterSum
// and first/last packet timestamps, so the D2 throughput anomaly
// (UDP 2.1811 Mbps over a 2 Mbps bottleneck) can be checked against
// measured receive windows instead of assumptions.
//
// FlowMonitor counts IP-layer packets/bytes (headers included, ACK and
// retransmission packets form/are part of flows), while PacketSink counts
// application-layer payload bytes only. The two are printed side by side.

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/traffic-control-module.h"

#include <fstream>
#include <iostream>
#include <iomanip>
#include <string>

using namespace ns3;

int main(int argc, char* argv[])
{
    std::string protocol = "tcp";
    std::string bottleneck = "2Mbps";
    std::string delay = "10ms";
    std::string csvFile;

    CommandLine cmd;
    cmd.AddValue("protocol", "tcp or udp", protocol);
    cmd.AddValue("bottleneck", "Middle link rate", bottleneck);
    cmd.AddValue("delay", "Middle link delay", delay);
    cmd.AddValue("csvfile", "Append per-flow metrics to this CSV file", csvFile);
    cmd.Parse(argc, argv);

    if (protocol != "tcp" && protocol != "udp") {
        std::cerr << "Protocol must be tcp or udp\n";
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

    const uint16_t port = 9000;

    std::string socketType =
        protocol == "tcp"
        ? "ns3::TcpSocketFactory"
        : "ns3::UdpSocketFactory";

    PacketSinkHelper sink(
        socketType,
        InetSocketAddress(Ipv4Address::GetAny(), port)
    );

    auto sinkApps = sink.Install(nodes.Get(3));
    sinkApps.Start(Seconds(0.5));
    sinkApps.Stop(Seconds(10.0));

    ApplicationContainer senderApps;

    if (protocol == "tcp") {
        BulkSendHelper sender(
            socketType,
            InetSocketAddress(receiverIf.GetAddress(1), port)
        );
        sender.SetAttribute("MaxBytes", UintegerValue(0));
        sender.SetAttribute("SendSize", UintegerValue(1024));
        senderApps = sender.Install(nodes.Get(0));
    } else {
        OnOffHelper sender(
            socketType,
            InetSocketAddress(receiverIf.GetAddress(1), port)
        );
        sender.SetAttribute("DataRate", StringValue("4Mbps"));
        sender.SetAttribute("PacketSize", UintegerValue(1024));
        sender.SetAttribute(
            "OnTime",
            StringValue("ns3::ConstantRandomVariable[Constant=1]")
        );
        sender.SetAttribute(
            "OffTime",
            StringValue("ns3::ConstantRandomVariable[Constant=0]")
        );
        senderApps = sender.Install(nodes.Get(0));
    }

    senderApps.Start(Seconds(1.0));
    senderApps.Stop(Seconds(9.0));

    // Evidence for queue analysis: bottleneck device (n1 -> n2) queue.
    Ptr<PointToPointNetDevice> bottleneckDev =
        DynamicCast<PointToPointNetDevice>(d12.Get(0));
    std::string queueInfo = "unknown";
    if (bottleneckDev && bottleneckDev->GetQueue()) {
        Ptr<Queue<Packet>> q = bottleneckDev->GetQueue();
        QueueSize qs = q->GetMaxSize();
        queueInfo = q->GetInstanceTypeId().GetName()
                  + " MaxSize=" + std::to_string(qs.GetValue())
                  + (qs.GetUnit() == QueueSizeUnit::PACKETS ? " packets" : " bytes");
    }

    // Evidence for queue analysis: the root queue disc that the traffic
    // control layer (installed by default with the internet stack) puts
    // on the bottleneck device of node 1. Packets queue here, not only
    // in the 100-packet device queue printed above.
    Ptr<TrafficControlLayer> tcLayer = nodes.Get(1)->GetObject<TrafficControlLayer>();
    Ptr<QueueDisc> bottleneckQdisc;
    std::string qdiscInfo = "none";
    if (tcLayer) {
        bottleneckQdisc = tcLayer->GetRootQueueDiscOnDevice(d12.Get(0));
        if (bottleneckQdisc) {
            QueueSizeValue qsv;
            bottleneckQdisc->GetAttribute("MaxSize", qsv);
            qdiscInfo = bottleneckQdisc->GetInstanceTypeId().GetName()
                      + " MaxSize=" + std::to_string(qsv.Get().GetValue())
                      + (qsv.Get().GetUnit() == QueueSizeUnit::PACKETS ? " packets" : " bytes");
        }
    }

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();

    Simulator::Stop(Seconds(10.0));
    Simulator::Run();

    monitor->CheckForLostPackets();

    std::string qdiscEnd = "n/a";
    if (bottleneckQdisc) {
        QueueSize cur = bottleneckQdisc->GetCurrentSize();
        qdiscEnd = "current_size=" + std::to_string(cur.GetValue())
                 + (cur.GetUnit() == QueueSizeUnit::PACKETS ? " packets" : " bytes")
                 + " total_dropped=" + std::to_string(bottleneckQdisc->GetStats().nTotalDroppedPackets)
                 + " total_enqueued=" + std::to_string(bottleneckQdisc->GetStats().nTotalEnqueuedPackets);
    }

    auto receiver = DynamicCast<PacketSink>(sinkApps.Get(0));
    uint64_t sinkBytes = receiver->GetTotalRx();
    double sinkThroughput8s = (sinkBytes * 8.0) / (8.0 * 1000000.0);

    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    auto stats = monitor->GetFlowStats();

    std::ofstream csv;
    if (!csvFile.empty()) {
        bool needHeader = true;
        std::ifstream test(csvFile);
        if (test.good() && test.peek() != std::ifstream::traits_type::eof()) {
            needHeader = false;
        }
        test.close();
        csv.open(csvFile, std::ios::app);
        if (needHeader) {
            csv << "protocol,bottleneck,delay,flow_label,src,dst,ip_proto,"
                   "tx_packets,rx_packets,lost_packets,loss_rate_pct,rx_bytes,"
                   "avg_delay_ms,avg_jitter_ms,first_tx_s,last_tx_s,"
                   "first_rx_s,last_rx_s,rx_span_s,throughput_mbps\n";
        }
    }

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "config: protocol=" << protocol
              << " bottleneck=" << bottleneck
              << " delay=" << delay << "\n";
    std::cout << "bottleneck_queue: " << queueInfo << "\n";
    std::cout << "bottleneck_qdisc: " << qdiscInfo << "\n";
    std::cout << "bottleneck_qdisc_end: " << qdiscEnd << "\n";
    std::cout << "--- FlowMonitor (IP layer) ---\n";

    for (auto& pair : stats) {
        const FlowMonitor::FlowStats& s = pair.second;
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(pair.first);

        std::string label =
            (tuple.destinationPort == port) ? "data" : "reverse";

        double avgDelayMs = s.rxPackets > 0
            ? s.delaySum.GetSeconds() / s.rxPackets * 1000.0 : 0.0;
        double avgJitterMs = s.rxPackets > 1
            ? s.jitterSum.GetSeconds() / (s.rxPackets - 1) * 1000.0 : 0.0;
        double lossPct = s.txPackets > 0
            ? 100.0 * s.lostPackets / s.txPackets : 0.0;
        double span = (s.timeLastRxPacket - s.timeFirstTxPacket).GetSeconds();
        double flowThr = span > 0
            ? s.rxBytes * 8.0 / span / 1000000.0 : 0.0;

        std::cout << "flow " << pair.first << " [" << label << "] "
                  << tuple.sourceAddress << ":" << tuple.sourcePort
                  << " -> " << tuple.destinationAddress << ":" << tuple.destinationPort
                  << " ip_proto=" << (unsigned)tuple.protocol << "\n";
        std::cout << "  txPackets=" << s.txPackets
                  << " rxPackets=" << s.rxPackets
                  << " lostPackets=" << s.lostPackets
                  << " loss_rate_pct=" << lossPct << "\n";
        std::cout << "  rxBytes=" << s.rxBytes
                  << " avg_delay_ms=" << avgDelayMs
                  << " avg_jitter_ms=" << avgJitterMs << "\n";
        std::cout << "  firstTx=" << s.timeFirstTxPacket.GetSeconds()
                  << " lastTx=" << s.timeLastTxPacket.GetSeconds()
                  << " firstRx=" << s.timeFirstRxPacket.GetSeconds()
                  << " lastRx=" << s.timeLastRxPacket.GetSeconds()
                  << " rx_span_s=" << span
                  << " flow_throughput_mbps=" << flowThr << "\n";

        if (csv.is_open()) {
            csv << protocol << "," << bottleneck << "," << delay << ","
                << label << ","
                << tuple.sourceAddress << "," << tuple.destinationAddress << ","
                << (unsigned)tuple.protocol << ","
                << s.txPackets << "," << s.rxPackets << "," << s.lostPackets << ","
                << lossPct << "," << s.rxBytes << ","
                << avgDelayMs << "," << avgJitterMs << ","
                << s.timeFirstTxPacket.GetSeconds() << ","
                << s.timeLastTxPacket.GetSeconds() << ","
                << s.timeFirstRxPacket.GetSeconds() << ","
                << s.timeLastRxPacket.GetSeconds() << ","
                << span << "," << flowThr << "\n";
        }
    }

    std::cout << "--- PacketSink (application layer) ---\n";
    std::cout << "sink_received_bytes=" << sinkBytes
              << " sink_throughput_8s_mbps=" << sinkThroughput8s << "\n";

    Simulator::Destroy();
    return 0;
}
