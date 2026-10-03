/*
 * DAMA-MLO revision scenario (COMNET-D-26-05038, major revision).
 *
 * Wi-Fi 7 (802.11be) wireless mesh network: a 3x3 grid of mesh access points
 * (MAPs), a wireless backhaul to three wired gateway MAPs, and a new station
 * N5 that must associate with MAP 1 or MAP 4. MAP 4 hosts a slow station N4
 * that can trigger the CSMA/CA performance anomaly.
 *
 * Differences from scratch/user-association-wmn.cc (the original submission
 * scenario, kept unchanged so the submitted numbers stay reproducible):
 *  - one propagation model for everything: log-distance path loss, so RSSI,
 *    SNR, and the delivered rate are physically consistent;
 *  - fast stations use SNR-driven rate selection (IdealWifiManager, up to
 *    EHT MCS 13); the slow station N4 keeps a fixed rate (the anomaly source);
 *  - link modes: "slo" (all single-link on 5 GHz), "mlo" (all multi-link),
 *    "mloConfined" (all multi-link except the slow station, which is a
 *    single-link 5 GHz device);
 *  - measured per-link AP channel utilization (busy-time fraction), the
 *    quantity an AP advertises in the BSS Load element;
 *  - access-delay vs backhaul-delay split from per-node flow probes;
 *  - steady-state measurement window after a warm-up period;
 *  - backhaul channel width/band and traffic direction are configurable.
 *
 * Output: machine-readable "R <key> <value>" lines on stdout.
 */

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/multi-model-spectrum-channel.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/wifi-module.h"

#include <cmath>
#include <iomanip>
#include <map>
#include <sstream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("DamaMloV2");

namespace
{

/**
 * Airtime accumulator for one PHY, clipped to a measurement window.
 */
struct AirtimeAcc
{
    double t0{0};   ///< window start (s)
    double t1{0};   ///< window end (s)
    double busy{0}; ///< TX + RX + CCA_BUSY time inside the window (s)
    double tx{0};   ///< TX time inside the window (s)
};

/**
 * PHY state trace sink.
 *
 * @param acc accumulator to update
 * @param start state start time
 * @param duration state duration
 * @param state PHY state
 */
void
OnPhyState(AirtimeAcc* acc, Time start, Time duration, WifiPhyState state)
{
    double s = start.GetSeconds();
    double e = s + duration.GetSeconds();
    double lo = std::max(s, acc->t0);
    double hi = std::min(e, acc->t1);
    if (hi <= lo)
    {
        return;
    }
    double d = hi - lo;
    if (state == WifiPhyState::TX)
    {
        acc->tx += d;
        acc->busy += d;
    }
    else if (state == WifiPhyState::RX || state == WifiPhyState::CCA_BUSY)
    {
        acc->busy += d;
    }
}

/**
 * Per-station data-frame MCS histogram.
 */
struct McsAcc
{
    std::map<std::string, uint64_t> count; ///< mode name -> frames
};

/**
 * PHY TX trace sink: count data frames (>= 1000 bytes) per mode.
 *
 * @param acc accumulator
 * @param packet transmitted packet
 * @param mode transmission mode
 * @param preamble preamble type
 * @param power power level
 */
void
OnPhyTx(McsAcc* acc, Ptr<const Packet> packet, WifiMode mode, WifiPreamble preamble, uint8_t power)
{
    if (packet->GetSize() >= 1000)
    {
        acc->count[mode.GetUniqueName()]++;
    }
}

/**
 * Free-space reference loss at 1 m.
 *
 * @param freqHz carrier frequency (Hz)
 * @return loss in dB
 */
double
RefLossDb(double freqHz)
{
    return 20.0 * std::log10(4.0 * M_PI * freqHz / 299792458.0);
}

/**
 * Build a spectrum channel with log-distance (or range) propagation.
 *
 * @param useRange true for the legacy range model
 * @param exponent path-loss exponent
 * @param freqHz carrier frequency for the reference loss
 * @param range max range for the range model (m)
 * @return the channel
 */
Ptr<MultiModelSpectrumChannel>
MakeChannel(bool useRange, double exponent, double freqHz, double range)
{
    Ptr<MultiModelSpectrumChannel> ch = CreateObject<MultiModelSpectrumChannel>();
    ch->SetPropagationDelayModel(CreateObject<ConstantSpeedPropagationDelayModel>());
    if (useRange)
    {
        Ptr<RangePropagationLossModel> loss = CreateObject<RangePropagationLossModel>();
        loss->SetAttribute("MaxRange", DoubleValue(range));
        ch->AddPropagationLossModel(loss);
    }
    else
    {
        Ptr<LogDistancePropagationLossModel> loss = CreateObject<LogDistancePropagationLossModel>();
        loss->SetAttribute("Exponent", DoubleValue(exponent));
        loss->SetAttribute("ReferenceDistance", DoubleValue(1.0));
        loss->SetAttribute("ReferenceLoss", DoubleValue(RefLossDb(freqHz)));
        ch->AddPropagationLossModel(loss);
    }
    return ch;
}

/// Snapshot of one flow's counters.
struct FlowSnap
{
    uint64_t rxBytes{0};   ///< received bytes
    uint64_t rxPackets{0}; ///< received packets
    uint64_t txPackets{0}; ///< transmitted packets
    uint64_t lost{0};      ///< lost packets
    double delaySum{0};    ///< end-to-end delay sum (s)
    double probeDelay{0};  ///< delay-from-first-probe sum at the serving MAP (s)
    uint64_t probePkts{0}; ///< packets seen by the serving-MAP probe
};

} // namespace

int
main(int argc, char* argv[])
{
    uint32_t scenario = 1; // 0: no N5 (pre-association measurement), 1: N5->MAP1, 2: N5->MAP4
    double n5X = 70.0;
    double n5Y = 225.0;
    double n4X = 120.0;
    std::string n4Rate = "EhtMcs0";
    std::string fastRate = "ideal"; // "ideal" or a fixed mode, e.g. EhtMcs7
    std::string linkMode = "mlo";   // slo | mlo | mloConfined
    std::string prop = "logdist";   // logdist | range
    double accessExp = 2.5;
    double backhaulExp = 2.0;
    double txPower = 20.0;
    uint32_t backhaulWidth = 80;
    std::string backhaulBand = "5"; // "5" or "6"
    bool useTcp = true;
    bool downlink = false;
    double simTime = 25.0;
    double warmup = 5.0;
    uint32_t extraMap1 = 0;
    uint32_t extraMap4 = 0;
    uint32_t extraMap1Slow = 0;
    uint32_t extraMap4Slow = 0;
    uint32_t rngRun = 1;
    bool tputTrace = false;
    bool allAps = false; // also run (idle) access APs on MAPs 2,3,5..9
    double staDist = 20.0; // distance of N1/N2/N3 from their MAP (m)
    std::string newSta;    // arriving stations "x:y:map,x:y:map,..." (map = 1 or 4)

    CommandLine cmd(__FILE__);
    cmd.AddValue("scenario", "0: no N5, 1: N5 on MAP 1, 2: N5 on MAP 4", scenario);
    cmd.AddValue("n5X", "N5 x coordinate (m)", n5X);
    cmd.AddValue("n5Y", "N5 y coordinate (m)", n5Y);
    cmd.AddValue("n4X", "N4 x coordinate (m); N4 is at y=150", n4X);
    cmd.AddValue("n4Rate", "fixed data mode of the slow station N4", n4Rate);
    cmd.AddValue("fastRate", "fast-station rate: 'ideal' or a fixed EHT mode", fastRate);
    cmd.AddValue("linkMode", "slo | mlo | mloConfined", linkMode);
    cmd.AddValue("prop", "logdist | range", prop);
    cmd.AddValue("accessExp", "access-link path-loss exponent", accessExp);
    cmd.AddValue("backhaulExp", "backhaul path-loss exponent", backhaulExp);
    cmd.AddValue("txPower", "transmit power of every device (dBm)", txPower);
    cmd.AddValue("backhaulWidth", "backhaul channel width (MHz): 20, 40, 80, 160", backhaulWidth);
    cmd.AddValue("backhaulBand", "backhaul band: 5 or 6 (GHz)", backhaulBand);
    cmd.AddValue("useTcp", "TCP BulkSend (true) or saturated UDP OnOff (false)", useTcp);
    cmd.AddValue("downlink", "traffic from the server to the stations instead of uplink", downlink);
    cmd.AddValue("simTime", "end of traffic and measurement (s)", simTime);
    cmd.AddValue("warmup", "start of the measurement window (s)", warmup);
    cmd.AddValue("extraMap1", "extra fast stations on MAP 1", extraMap1);
    cmd.AddValue("extraMap4", "extra fast stations on MAP 4", extraMap4);
    cmd.AddValue("extraMap1Slow", "extra slow stations on MAP 1", extraMap1Slow);
    cmd.AddValue("extraMap4Slow", "extra slow stations on MAP 4", extraMap4Slow);
    cmd.AddValue("rngRun", "independent replication number", rngRun);
    cmd.AddValue("tputTrace", "print per-second aggregate throughput", tputTrace);
    cmd.AddValue("allAps", "also install idle access APs on the MAPs without stations", allAps);
    cmd.AddValue("staDist", "distance of N1, N2, N3 from their MAP (m)", staDist);
    cmd.AddValue("newSta", "arriving fast stations as x:y:map list (map 1 or 4)", newSta);
    cmd.Parse(argc, argv);

    RngSeedManager::SetRun(rngRun);

    NS_ABORT_MSG_IF(scenario > 2, "scenario must be 0, 1 or 2");
    NS_ABORT_MSG_IF(linkMode != "slo" && linkMode != "mlo" && linkMode != "mloConfined",
                    "linkMode must be slo, mlo or mloConfined");
    NS_ABORT_MSG_IF(warmup >= simTime, "warmup must be < simTime");
    NS_ABORT_MSG_IF(extraMap1 > 40 || extraMap4 > 40 || extraMap1Slow > 40 || extraMap4Slow > 40,
                    "extra station counts must be <= 40");

    Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(1448));
    Config::SetDefault("ns3::TcpSocket::ConnTimeout", TimeValue(MilliSeconds(200)));
    Config::SetDefault("ns3::TcpSocket::ConnCount", UintegerValue(30));
    Config::SetDefault("ns3::WifiMacQueue::MaxSize", QueueSizeValue(QueueSize("1000p")));

    const bool useRange = (prop == "range");
    const bool sloAll = (linkMode == "slo");
    const bool confineSlow = (linkMode == "mloConfined");

    // ---------------------------------------------------------------- nodes
    NodeContainer meshNodes;
    meshNodes.Create(9); // node ids 0..8 = MAP 1..9
    NodeContainer wiredNodes;
    wiredNodes.Create(2); // 9 = gateway, 10 = server
    NodeContainer clientN1N2;
    clientN1N2.Create(2); // 11, 12
    NodeContainer clientN3N4;
    clientN3N4.Create(2); // 13, 14
    NodeContainer clientN5;
    clientN5.Create(1); // 15

    MobilityHelper mobility;
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    Ptr<ListPositionAllocator> pos = CreateObject<ListPositionAllocator>();
    const double mapX[9] = {0, 150, 300, 0, 150, 300, 0, 150, 300};
    const double mapY[9] = {300, 300, 300, 150, 150, 150, 0, 0, 0};
    for (uint32_t i = 0; i < 9; ++i)
    {
        pos->Add(Vector(mapX[i], mapY[i], 0));
    }
    pos->Add(Vector(450, 150, 0)); // gateway
    pos->Add(Vector(600, 150, 0)); // server
    pos->Add(Vector(0, 300 + staDist, 0)); // N1
    pos->Add(Vector(staDist, 300, 0));     // N2
    pos->Add(Vector(0, 150 - staDist, 0)); // N3
    pos->Add(Vector(n4X, 150, 0));         // N4
    pos->Add(Vector(n5X, n5Y, 0));         // N5
    mobility.SetPositionAllocator(pos);
    mobility.Install(meshNodes);
    mobility.Install(wiredNodes);
    mobility.Install(clientN1N2);
    mobility.Install(clientN3N4);
    mobility.Install(clientN5);

    // ------------------------------------------------------------- backhaul
    uint32_t bhCh = 155;
    double bhFreq = 5.775e9;
    WifiPhyBand bhBandEnum = WIFI_PHY_BAND_5GHZ;
    std::string bhBandStr = "BAND_5GHZ";
    if (backhaulBand == "6")
    {
        // 6 GHz channels well above the access channels 1..13
        bhBandEnum = WIFI_PHY_BAND_6GHZ;
        bhBandStr = "BAND_6GHZ";
        switch (backhaulWidth)
        {
        case 20:
            bhCh = 101;
            break;
        case 40:
            bhCh = 99;
            break;
        case 80:
            bhCh = 103;
            break;
        default:
            bhCh = 111;
            break; // 160 MHz
        }
        bhFreq = (5950 + 5 * bhCh) * 1e6;
    }
    else
    {
        switch (backhaulWidth)
        {
        case 20:
            bhCh = 149;
            bhFreq = 5.745e9;
            break;
        case 40:
            bhCh = 151;
            bhFreq = 5.755e9;
            break;
        case 80:
            bhCh = 155;
            bhFreq = 5.775e9;
            break;
        default:
            bhCh = 163;
            bhFreq = 5.815e9;
            break; // 160 MHz (UNII-3/4)
        }
    }
    // The backhaul runs on its own channel, isolated from the access channels,
    // so the YANS PHY model (no cross-channel spectrum computation) gives the
    // same behavior as the spectrum model at a fraction of the cost.
    YansWifiChannelHelper bhChanHelper;
    bhChanHelper.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    if (useRange)
    {
        bhChanHelper.AddPropagationLoss("ns3::RangePropagationLossModel",
                                        "MaxRange",
                                        DoubleValue(200.0));
    }
    else
    {
        bhChanHelper.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                                        "Exponent",
                                        DoubleValue(backhaulExp),
                                        "ReferenceDistance",
                                        DoubleValue(1.0),
                                        "ReferenceLoss",
                                        DoubleValue(RefLossDb(bhFreq)));
    }
    YansWifiPhyHelper backhaulPhy;
    backhaulPhy.SetChannel(bhChanHelper.Create());
    {
        std::ostringstream s;
        s << "{" << bhCh << ", " << backhaulWidth << ", " << bhBandStr << ", 0}";
        backhaulPhy.Set("ChannelSettings", StringValue(s.str()));
    }
    backhaulPhy.Set("TxPowerStart", DoubleValue(txPower));
    backhaulPhy.Set("TxPowerEnd", DoubleValue(txPower));
    WifiHelper backhaulWifi;
    backhaulWifi.SetStandard(WIFI_STANDARD_80211be);
    backhaulWifi.SetRemoteStationManager("ns3::IdealWifiManager");
    WifiMacHelper backhaulMac;
    backhaulMac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer backhaulDevices = backhaulWifi.Install(backhaulPhy, backhaulMac, meshNodes);
    (void)bhBandEnum;

    // --------------------------------------------------------------- access
    std::map<int, Ptr<MultiModelSpectrumChannel>> ch5, ch6;
    for (int c : {36, 40, 44, 48})
    {
        ch5[c] = MakeChannel(useRange, accessExp, (5000 + 5 * c) * 1e6, 250.0);
    }
    for (int c : {1, 5, 9, 13})
    {
        ch6[c] = MakeChannel(useRange, accessExp, (5950 + 5 * c) * 1e6, 250.0);
    }

    auto mapCh5 = [](uint32_t mapIdx) { return 36 + 4 * (int)(mapIdx % 4); };
    auto mapCh6 = [](uint32_t mapIdx) { return 1 + 4 * (int)(mapIdx % 4); };

    // Build a PHY helper with 1 link (5 GHz) or 2 links (5 + 6 GHz) for MAP index i
    auto makePhy = [&](uint32_t i, uint8_t nLinks) {
        SpectrumWifiPhyHelper phy(nLinks);
        std::ostringstream s5;
        s5 << "{" << mapCh5(i) << ", 20, BAND_5GHZ, 0}";
        phy.Set(0, "ChannelSettings", StringValue(s5.str()));
        phy.AddChannel(ch5[mapCh5(i)], WIFI_SPECTRUM_5_GHZ);
        if (nLinks == 2)
        {
            std::ostringstream s6;
            s6 << "{" << mapCh6(i) << ", 20, BAND_6GHZ, 0}";
            phy.Set(1, "ChannelSettings", StringValue(s6.str()));
            phy.AddChannel(ch6[mapCh6(i)], WIFI_SPECTRUM_6_GHZ);
        }
        phy.Set("TxPowerStart", DoubleValue(txPower));
        phy.Set("TxPowerEnd", DoubleValue(txPower));
        return phy;
    };

    const uint8_t apLinks = sloAll ? 1 : 2;
    NetDeviceContainer apDevices[9];
    for (uint32_t i = 0; i < 9; ++i)
    {
        if (!allAps && i != 0 && i != 3)
        {
            continue; // MAPs without stations act as pure backhaul relays
        }
        SpectrumWifiPhyHelper phy = makePhy(i, apLinks);
        WifiMacHelper mac;
        std::ostringstream ssid;
        ssid << "map-" << (i + 1);
        mac.SetType("ns3::ApWifiMac", "Ssid", SsidValue(Ssid(ssid.str())));
        WifiHelper wifi;
        wifi.SetStandard(WIFI_STANDARD_80211be);
        wifi.SetRemoteStationManager("ns3::IdealWifiManager");
        apDevices[i] = wifi.Install(phy, mac, meshNodes.Get(i));
    }

    WifiHelper wifiFast;
    wifiFast.SetStandard(WIFI_STANDARD_80211be);
    if (fastRate == "ideal")
    {
        wifiFast.SetRemoteStationManager("ns3::IdealWifiManager");
    }
    else
    {
        wifiFast.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                         "DataMode",
                                         StringValue(fastRate),
                                         "ControlMode",
                                         StringValue("OfdmRate6Mbps"));
    }
    WifiHelper wifiSlow;
    wifiSlow.SetStandard(WIFI_STANDARD_80211be);
    wifiSlow.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                     "DataMode",
                                     StringValue(n4Rate),
                                     "ControlMode",
                                     StringValue("OfdmRate6Mbps"));

    auto installSta = [&](NodeContainer nodes, uint32_t mapIdx, bool slow) {
        uint8_t nLinks = 2;
        if (sloAll || (slow && confineSlow))
        {
            nLinks = 1;
        }
        SpectrumWifiPhyHelper phy = makePhy(mapIdx, nLinks);
        WifiMacHelper mac;
        std::ostringstream ssid;
        ssid << "map-" << (mapIdx + 1);
        mac.SetType("ns3::StaWifiMac",
                    "Ssid",
                    SsidValue(Ssid(ssid.str())),
                    "ActiveProbing",
                    BooleanValue(false));
        return (slow ? wifiSlow : wifiFast).Install(phy, mac, nodes);
    };

    const uint32_t chosenMap = (scenario == 2) ? 4 : 1;
    const uint32_t chosenIdx = chosenMap - 1;

    NetDeviceContainer devN1N2 = installSta(clientN1N2, 0, false);
    NetDeviceContainer devN3 = installSta(NodeContainer(clientN3N4.Get(0)), 3, false);
    NetDeviceContainer devN4 = installSta(NodeContainer(clientN3N4.Get(1)), 3, true);
    NetDeviceContainer devN5;
    if (scenario != 0)
    {
        devN5 = installSta(clientN5, chosenIdx, false);
    }

    // Density-scaling extras, placed on rings around their MAP
    NodeContainer ex1, ex4, ex1s, ex4s;
    ex1.Create(extraMap1);
    ex4.Create(extraMap4);
    ex1s.Create(extraMap1Slow);
    ex4s.Create(extraMap4Slow);
    auto ring = [&](NodeContainer& nodes, double cx, double cy, double phase) {
        Ptr<ListPositionAllocator> a = CreateObject<ListPositionAllocator>();
        for (uint32_t k = 0; k < nodes.GetN(); ++k)
        {
            double ang = phase + 2.0 * M_PI * k / std::max<uint32_t>(nodes.GetN(), 1);
            double r = staDist + 5.0 * (k % 4);
            a->Add(Vector(cx + r * std::cos(ang), cy + r * std::sin(ang), 0));
        }
        mobility.SetPositionAllocator(a);
        mobility.Install(nodes);
    };
    ring(ex1, 0, 300, 0);
    ring(ex4, 0, 150, 0);
    ring(ex1s, 0, 300, M_PI / 4);
    ring(ex4s, 0, 150, M_PI / 4);
    NetDeviceContainer devEx1, devEx4, devEx1s, devEx4s;
    if (extraMap1)
    {
        devEx1 = installSta(ex1, 0, false);
    }
    if (extraMap4)
    {
        devEx4 = installSta(ex4, 3, false);
    }
    if (extraMap1Slow)
    {
        devEx1s = installSta(ex1s, 0, true);
    }
    if (extraMap4Slow)
    {
        devEx4s = installSta(ex4s, 3, true);
    }

    // Arriving stations (multi-station sequential-association experiment)
    struct NewSta
    {
        double x;
        double y;
        uint32_t map;
    };

    std::vector<NewSta> arrivals;
    {
        std::stringstream ss(newSta);
        std::string item;
        while (std::getline(ss, item, ','))
        {
            if (item.empty())
            {
                continue;
            }
            NewSta a{};
            char c1;
            char c2;
            std::stringstream is(item);
            is >> a.x >> c1 >> a.y >> c2 >> a.map;
            NS_ABORT_MSG_IF(a.map != 1 && a.map != 4, "newSta map must be 1 or 4");
            arrivals.push_back(a);
        }
    }
    NS_ABORT_MSG_IF(arrivals.size() > 40, "at most 40 arriving stations");
    NodeContainer arrNodes;
    arrNodes.Create(arrivals.size());
    std::vector<NetDeviceContainer> arrDevs;
    {
        Ptr<ListPositionAllocator> a = CreateObject<ListPositionAllocator>();
        for (const auto& st : arrivals)
        {
            a->Add(Vector(st.x, st.y, 0));
        }
        mobility.SetPositionAllocator(a);
        mobility.Install(arrNodes);
        for (uint32_t k = 0; k < arrivals.size(); ++k)
        {
            arrDevs.push_back(installSta(NodeContainer(arrNodes.Get(k)), arrivals[k].map - 1, false));
        }
    }

    // ---------------------------------------------------------- wired links
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("1Gbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    NetDeviceContainer p2pMAP3 = p2p.Install(meshNodes.Get(2), wiredNodes.Get(0));
    NetDeviceContainer p2pMAP6 = p2p.Install(meshNodes.Get(5), wiredNodes.Get(0));
    NetDeviceContainer p2pMAP9 = p2p.Install(meshNodes.Get(8), wiredNodes.Get(0));
    NetDeviceContainer p2pNet = p2p.Install(wiredNodes.Get(0), wiredNodes.Get(1));

    InternetStackHelper stack;
    stack.SetIpv6StackInstall(false); // IPv4 only: one flow probe per node, probe index == node id
    stack.Install(meshNodes);
    stack.Install(wiredNodes);
    stack.Install(clientN1N2);
    stack.Install(clientN3N4);
    stack.Install(clientN5);
    stack.Install(ex1);
    stack.Install(ex4);
    stack.Install(ex1s);
    stack.Install(ex4s);
    stack.Install(arrNodes);

    Ipv4AddressHelper addr;
    addr.SetBase("10.1.1.0", "255.255.255.0");
    addr.Assign(backhaulDevices);
    for (uint32_t i = 0; i < 9; ++i)
    {
        if (apDevices[i].GetN() == 0)
        {
            continue;
        }
        std::ostringstream b;
        b << "10.2." << (i + 1) << ".0";
        addr.SetBase(b.str().c_str(), "255.255.255.0");
        addr.Assign(apDevices[i]);
    }
    addr.SetBase("10.2.1.0", "255.255.255.0", "0.0.0.2");
    addr.Assign(devN1N2); // .2, .3
    addr.SetBase("10.2.4.0", "255.255.255.0", "0.0.0.2");
    addr.Assign(devN3); // .2
    addr.SetBase("10.2.4.0", "255.255.255.0", "0.0.0.3");
    addr.Assign(devN4); // .3
    if (scenario != 0)
    {
        std::ostringstream b;
        b << "10.2." << chosenMap << ".0";
        addr.SetBase(b.str().c_str(), "255.255.255.0", "0.0.0.4");
        addr.Assign(devN5); // .4
    }
    if (extraMap1)
    {
        addr.SetBase("10.2.1.0", "255.255.255.0", "0.0.0.10");
        addr.Assign(devEx1);
    }
    if (extraMap4)
    {
        addr.SetBase("10.2.4.0", "255.255.255.0", "0.0.0.10");
        addr.Assign(devEx4);
    }
    if (extraMap1Slow)
    {
        addr.SetBase("10.2.1.0", "255.255.255.0", "0.0.0.60");
        addr.Assign(devEx1s);
    }
    if (extraMap4Slow)
    {
        addr.SetBase("10.2.4.0", "255.255.255.0", "0.0.0.60");
        addr.Assign(devEx4s);
    }
    for (uint32_t k = 0; k < arrivals.size(); ++k)
    {
        std::ostringstream b;
        b << "10.2." << arrivals[k].map << ".0";
        std::ostringstream h;
        h << "0.0.0." << (100 + k);
        addr.SetBase(b.str().c_str(), "255.255.255.0", h.str().c_str());
        addr.Assign(arrDevs[k]);
    }
    addr.SetBase("10.3.3.0", "255.255.255.0");
    addr.Assign(p2pMAP3);
    addr.SetBase("10.3.6.0", "255.255.255.0");
    addr.Assign(p2pMAP6);
    addr.SetBase("10.3.9.0", "255.255.255.0");
    addr.Assign(p2pMAP9);
    addr.SetBase("10.4.1.0", "255.255.255.0");
    addr.Assign(p2pNet);

    // ------------------------------------------------------- static routing
    // MAP1 -> MAP2 -> MAP3 -> GW and MAP4 -> MAP5 -> MAP6 -> GW (2 wireless hops each)
    Ipv4StaticRoutingHelper srh;
    auto rt = [&](Ptr<Node> n) { return srh.GetStaticRouting(n->GetObject<Ipv4>()); };
    auto ifx = [](Ptr<Node> n, Ptr<NetDevice> d) {
        return n->GetObject<Ipv4>()->GetInterfaceForDevice(d);
    };
    Ptr<Node> server = wiredNodes.Get(1);
    Ptr<Node> gw = wiredNodes.Get(0);
    rt(server)->AddNetworkRouteTo("10.2.0.0", "255.255.0.0", "10.4.1.1", ifx(server, p2pNet.Get(1)));
    rt(gw)->AddNetworkRouteTo("10.2.1.0", "255.255.255.0", "10.3.3.1", ifx(gw, p2pMAP3.Get(1)));
    rt(gw)->AddNetworkRouteTo("10.2.4.0", "255.255.255.0", "10.3.6.1", ifx(gw, p2pMAP6.Get(1)));
    auto m = [&](uint32_t i) { return meshNodes.Get(i); };
    auto bh = [&](uint32_t i) { return ifx(m(i), backhaulDevices.Get(i)); };
    // backhaul addresses: MAP k -> 10.1.1.k
    rt(m(2))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.3.3.2", ifx(m(2), p2pMAP3.Get(0)));
    rt(m(2))->AddNetworkRouteTo("10.2.1.0", "255.255.255.0", "10.1.1.2", bh(2));
    rt(m(1))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.1.1.3", bh(1));
    rt(m(1))->AddNetworkRouteTo("10.2.1.0", "255.255.255.0", "10.1.1.1", bh(1));
    rt(m(0))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.1.1.2", bh(0));
    rt(m(5))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.3.6.2", ifx(m(5), p2pMAP6.Get(0)));
    rt(m(5))->AddNetworkRouteTo("10.2.4.0", "255.255.255.0", "10.1.1.5", bh(5));
    rt(m(4))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.1.1.6", bh(4));
    rt(m(4))->AddNetworkRouteTo("10.2.4.0", "255.255.255.0", "10.1.1.4", bh(4));
    rt(m(3))->AddNetworkRouteTo("10.4.1.0", "255.255.255.0", "10.1.1.5", bh(3));

    auto setDefault = [&](NodeContainer nodes, NetDeviceContainer devs, uint32_t mapNum) {
        std::ostringstream g;
        g << "10.2." << mapNum << ".1";
        for (uint32_t k = 0; k < nodes.GetN(); ++k)
        {
            rt(nodes.Get(k))->SetDefaultRoute(g.str().c_str(), ifx(nodes.Get(k), devs.Get(k)));
        }
    };
    setDefault(clientN1N2, devN1N2, 1);
    setDefault(NodeContainer(clientN3N4.Get(0)), devN3, 4);
    setDefault(NodeContainer(clientN3N4.Get(1)), devN4, 4);
    if (scenario != 0)
    {
        setDefault(clientN5, devN5, chosenMap);
    }
    if (extraMap1)
    {
        setDefault(ex1, devEx1, 1);
    }
    if (extraMap4)
    {
        setDefault(ex4, devEx4, 4);
    }
    if (extraMap1Slow)
    {
        setDefault(ex1s, devEx1s, 1);
    }
    if (extraMap4Slow)
    {
        setDefault(ex4s, devEx4s, 4);
    }
    for (uint32_t k = 0; k < arrivals.size(); ++k)
    {
        setDefault(NodeContainer(arrNodes.Get(k)), arrDevs[k], arrivals[k].map);
    }

    // --------------------------------------------------------- applications
    // station name <-> IP, and serving MAP node id for the access-delay probe
    std::map<Ipv4Address, std::string> staName;
    std::map<Ipv4Address, uint32_t> staMapNode;
    NodeContainer allSta;
    auto reg = [&](NodeContainer nodes, const std::string& prefix, uint32_t mapIdx, bool numbered) {
        for (uint32_t k = 0; k < nodes.GetN(); ++k)
        {
            Ipv4Address a = nodes.Get(k)->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
            staName[a] = numbered ? prefix + std::to_string(k) : prefix;
            staMapNode[a] = mapIdx;
            allSta.Add(nodes.Get(k));
        }
    };
    reg(NodeContainer(clientN1N2.Get(0)), "N1", 0, false);
    reg(NodeContainer(clientN1N2.Get(1)), "N2", 0, false);
    reg(NodeContainer(clientN3N4.Get(0)), "N3", 3, false);
    reg(NodeContainer(clientN3N4.Get(1)), "N4", 3, false);
    if (scenario != 0)
    {
        reg(clientN5, "N5", chosenIdx, false);
    }
    reg(ex1, "X1f", 0, true);
    reg(ex4, "X4f", 3, true);
    reg(ex1s, "X1s", 0, true);
    reg(ex4s, "X4s", 3, true);
    for (uint32_t k = 0; k < arrivals.size(); ++k)
    {
        reg(NodeContainer(arrNodes.Get(k)), "S" + std::to_string(k), arrivals[k].map - 1, false);
    }

    const uint16_t port = 9;
    const Ipv4Address serverAddr("10.4.1.2");
    ApplicationContainer senders;
    ApplicationContainer sinks;
    std::string sockFactory = useTcp ? "ns3::TcpSocketFactory" : "ns3::UdpSocketFactory";
    auto makeSender = [&](Address dst) {
        if (useTcp)
        {
            BulkSendHelper b(sockFactory, dst);
            b.SetAttribute("MaxBytes", UintegerValue(0));
            b.SetAttribute("SendSize", UintegerValue(1448));
            return b;
        }
        return BulkSendHelper(sockFactory, dst); // placeholder, UDP handled below
    };
    if (!downlink)
    {
        PacketSinkHelper sinkH(sockFactory, InetSocketAddress(Ipv4Address::GetAny(), port));
        sinks.Add(sinkH.Install(server));
        for (uint32_t k = 0; k < allSta.GetN(); ++k)
        {
            if (useTcp)
            {
                senders.Add(makeSender(InetSocketAddress(serverAddr, port)).Install(allSta.Get(k)));
            }
            else
            {
                OnOffHelper o(sockFactory, InetSocketAddress(serverAddr, port));
                o.SetConstantRate(DataRate("100Mbps"), 1400);
                senders.Add(o.Install(allSta.Get(k)));
            }
        }
    }
    else
    {
        PacketSinkHelper sinkH(sockFactory, InetSocketAddress(Ipv4Address::GetAny(), port));
        sinks.Add(sinkH.Install(allSta));
        for (auto& [a, name] : staName)
        {
            if (useTcp)
            {
                senders.Add(makeSender(InetSocketAddress(a, port)).Install(server));
            }
            else
            {
                OnOffHelper o(sockFactory, InetSocketAddress(a, port));
                o.SetConstantRate(DataRate("100Mbps"), 1400);
                senders.Add(o.Install(server));
            }
        }
    }
    sinks.Start(Seconds(0.5));
    sinks.Stop(Seconds(simTime + 1.0));
    for (uint32_t k = 0; k < senders.GetN(); ++k)
    {
        senders.Get(k)->SetStartTime(Seconds(1.0 + 0.05 * k));
        senders.Get(k)->SetStopTime(Seconds(simTime));
    }

    // ------------------------------------------------------- instrumentation
    FlowMonitorHelper flowmon;
    Ptr<FlowMonitor> monitor = flowmon.InstallAll();
    // Probes are created in NodeList order, so probe index == node id here.

    // AP channel utilization on MAP 1 and MAP 4, per link
    std::map<std::string, AirtimeAcc*> apAir;
    for (uint32_t idx : {0u, 3u})
    {
        Ptr<WifiNetDevice> dev = DynamicCast<WifiNetDevice>(apDevices[idx].Get(0));
        for (uint8_t l = 0; l < dev->GetNPhys(); ++l)
        {
            auto* acc = new AirtimeAcc{warmup, simTime};
            std::ostringstream key;
            key << "MAP" << (idx + 1) << "_L" << +l;
            apAir[key.str()] = acc;
            dev->GetPhy(l)->GetState()->TraceConnectWithoutContext(
                "State",
                MakeBoundCallback(&OnPhyState, acc));
        }
    }
    // Per-station TX airtime and data MCS, per link
    std::map<std::string, AirtimeAcc*> staAir;
    std::map<std::string, McsAcc*> staMcs;
    for (auto& [a, name] : staName)
    {
        Ptr<Node> n;
        for (uint32_t k = 0; k < allSta.GetN(); ++k)
        {
            if (allSta.Get(k)->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal() == a)
            {
                n = allSta.Get(k);
            }
        }
        Ptr<WifiNetDevice> dev = DynamicCast<WifiNetDevice>(n->GetDevice(0));
        for (uint8_t l = 0; l < dev->GetNPhys(); ++l)
        {
            std::ostringstream key;
            key << name << "_L" << +l;
            auto* acc = new AirtimeAcc{warmup, simTime};
            auto* mcs = new McsAcc;
            staAir[key.str()] = acc;
            staMcs[key.str()] = mcs;
            dev->GetPhy(l)->GetState()->TraceConnectWithoutContext(
                "State",
                MakeBoundCallback(&OnPhyState, acc));
            dev->GetPhy(l)->GetState()->TraceConnectWithoutContext("Tx",
                                                                  MakeBoundCallback(&OnPhyTx, mcs));
        }
    }

    Ptr<Ipv4FlowClassifier> classifier = DynamicCast<Ipv4FlowClassifier>(flowmon.GetClassifier());
    // Identify data flows: uplink = station -> server:9, downlink = server -> station:9
    auto dataFlowStation = [&](FlowId id, Ipv4Address& sta) {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(id);
        if (!downlink && t.destinationAddress == serverAddr && t.destinationPort == port)
        {
            sta = t.sourceAddress;
            return staName.count(sta) > 0;
        }
        if (downlink && t.sourceAddress == serverAddr && t.destinationPort == port)
        {
            sta = t.destinationAddress;
            return staName.count(sta) > 0;
        }
        return false;
    };
    auto snapshot = [&]() {
        std::map<std::string, FlowSnap> snap;
        const auto& stats = monitor->GetFlowStats();
        const auto& probes = monitor->GetAllProbes();
        for (const auto& [id, st] : stats)
        {
            Ipv4Address sta;
            if (!dataFlowStation(id, sta))
            {
                continue;
            }
            FlowSnap& s = snap[staName[sta]];
            s.rxBytes = st.rxBytes;
            s.rxPackets = st.rxPackets;
            s.txPackets = st.txPackets;
            s.lost = st.lostPackets;
            s.delaySum = st.delaySum.GetSeconds();
            uint32_t mapNode = staMapNode[sta];
            if (mapNode < probes.size())
            {
                auto ps = probes[mapNode]->GetStats();
                auto it = ps.find(id);
                if (it != ps.end())
                {
                    s.probeDelay = it->second.delayFromFirstProbeSum.GetSeconds();
                    s.probePkts = it->second.packets;
                }
            }
        }
        return snap;
    };

    std::map<std::string, FlowSnap> snapW, snapE;
    Simulator::Schedule(Seconds(warmup), [&]() { snapW = snapshot(); });
    Simulator::Schedule(Seconds(simTime), [&]() { snapE = snapshot(); });
    if (tputTrace)
    {
        auto last = std::make_shared<uint64_t>(0);
        for (double t = 1.0; t <= simTime + 1e-9; t += 1.0)
        {
            Simulator::Schedule(Seconds(t), [&, last, t]() {
                uint64_t tot = 0;
                for (const auto& [id, st] : monitor->GetFlowStats())
                {
                    Ipv4Address sta;
                    if (dataFlowStation(id, sta))
                    {
                        tot += st.rxBytes;
                    }
                }
                std::cout << "T " << t << " " << (tot - *last) * 8.0 / 1e6 << "\n";
                *last = tot;
            });
        }
    }

    Simulator::Stop(Seconds(simTime + 1.0));
    Simulator::Run();

    // --------------------------------------------------------------- output
    const double win = simTime - warmup;
    std::cout << std::fixed << std::setprecision(6);
    std::cout << "R scenario " << scenario << "\nR chosenMap " << (scenario ? chosenMap : 0)
              << "\nR linkMode " << linkMode << "\nR n4Rate " << n4Rate << "\nR n5X " << n5X
              << "\nR n5Y " << n5Y << "\nR rngRun " << rngRun << "\nR window " << win << "\n";
    double sumTput = 0;
    double sumLog = 0;
    double sumSq = 0;
    uint32_t nSta = 0;
    uint64_t txP = 0;
    uint64_t lostP = 0;
    double dSum = 0;
    double aSum = 0;
    uint64_t rxP = 0;
    uint64_t aP = 0;
    for (auto& [a, name] : staName)
    {
        FlowSnap e = snapE[name];
        FlowSnap w = snapW[name];
        double tput = (e.rxBytes - w.rxBytes) * 8.0 / win / 1e6; // Mbps
        uint64_t rp = e.rxPackets - w.rxPackets;
        uint64_t pp = e.probePkts - w.probePkts;
        double e2e = rp ? (e.delaySum - w.delaySum) / rp * 1e3 : 0.0;
        double acc = pp ? (e.probeDelay - w.probeDelay) / pp * 1e3 : 0.0;
        std::cout << "R tput_" << name << " " << tput << "\n";
        std::cout << "R e2e_" << name << " " << e2e << "\n";
        std::cout << "R probe_" << name << " " << acc << "\n";
        sumTput += tput;
        sumLog += std::log(std::max(tput, 1e-3));
        sumSq += tput * tput;
        nSta++;
        txP += e.txPackets - w.txPackets;
        lostP += e.lost - w.lost;
        dSum += e.delaySum - w.delaySum;
        rxP += rp;
        aSum += e.probeDelay - w.probeDelay;
        aP += pp;
    }
    std::cout << "R sumTput " << sumTput << "\n";
    std::cout << "R sumLog " << sumLog << "\n";
    std::cout << "R jain " << (sumSq > 0 ? sumTput * sumTput / (nSta * sumSq) : 0.0) << "\n";
    std::cout << "R nSta " << nSta << "\n";
    std::cout << "R lossPct " << (txP ? 100.0 * lostP / txP : 0.0) << "\n";
    std::cout << "R e2eMs " << (rxP ? dSum / rxP * 1e3 : 0.0) << "\n";
    // uplink: probe delay = access delay; downlink: probe delay = wired + backhaul delay
    std::cout << "R probeMs " << (aP ? aSum / aP * 1e3 : 0.0) << "\n";
    for (auto& [k, acc] : apAir)
    {
        std::cout << "R util_" << k << " " << acc->busy / win << "\n";
    }
    for (auto& [k, acc] : staAir)
    {
        std::cout << "R txair_" << k << " " << acc->tx / win << "\n";
    }
    for (auto& [k, mcs] : staMcs)
    {
        std::string best;
        uint64_t bestN = 0;
        uint64_t tot = 0;
        for (auto& [mode, n] : mcs->count)
        {
            tot += n;
            if (n > bestN)
            {
                bestN = n;
                best = mode;
            }
        }
        std::cout << "R mcs_" << k << " " << (best.empty() ? "none" : best) << "\n";
        std::cout << "R frames_" << k << " " << tot << "\n";
    }

    Simulator::Destroy();
    return 0;
}
