#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"

#include <iostream>
#include <iomanip>
#include <string>

using namespace ns3;

int main(int argc, char* argv[])
{
    std::string protocol = "tcp";
    std::string bottleneck = "2Mbps";
    std::string delay = "10ms";

    CommandLine cmd;
    cmd.AddValue("protocol", "tcp or udp", protocol);
    cmd.AddValue("bottleneck", "Middle link rate", bottleneck);
    cmd.AddValue("delay", "Middle link delay", delay);
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

    Simulator::Stop(Seconds(10.0));
    Simulator::Run();

    auto receiver =
        DynamicCast<PacketSink>(sinkApps.Get(0));

    uint64_t bytes = receiver->GetTotalRx();

    double throughputMbps =
        (bytes * 8.0) / (8.0 * 1000000.0);

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "protocol=" << protocol << "\n";
    std::cout << "bottleneck=" << bottleneck << "\n";
    std::cout << "delay=" << delay << "\n";
    std::cout << "received_bytes=" << bytes << "\n";
    std::cout << "throughput_mbps=" << throughputMbps << "\n";

    Simulator::Destroy();
    return 0;
}
