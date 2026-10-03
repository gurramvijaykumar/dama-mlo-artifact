/*
 * DAMA-MLO edge-stall trace scenario (COMNET-D-26-05038, major revision).
 *
 * Copy of scratch/dama-mlo-v2dev.cc (code version 2.1) with extra tracing of
 * N5 and its serving AP MLD (see "edge-stall trace" below) and the option
 * --n5Links=5, which makes N5 a single-link 5 GHz device (viable-link-only
 * control). Used only for the edge-stall diagnosis; the sweep scenario is
 * scratch/dama-mlo-v2.cc.
 *
 * Original description:
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
 *  - matched per-packet delay split (code version 2.1): each delivered data
 *    packet is time-stamped at its source, at the serving MAP, at the
 *    gateway MAP (wireless backhaul <-> wired boundary) and at its
 *    destination, so access + wireless backhaul + wired = end-to-end for
 *    exactly the same packets;
 *  - downlink (code version 2.1): the AP sends data to each slow station at
 *    that station's fixed rate, and to every other station at the ideal rate;
 *  - the old flow-probe access delay (probe_*) is still printed for comparison;
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
#include "ns3/ampdu-subframe-header.h"
#include "ns3/ap-wifi-mac.h"
#include "ns3/arp-header.h"
#include "ns3/llc-snap-header.h"
#include "ns3/block-ack-manager.h"
#include "ns3/qos-txop.h"
#include "ns3/spectrum-wifi-phy.h"
#include "ns3/sta-wifi-mac.h"
#include "ns3/wifi-psdu.h"
#include "ns3/wifi-spectrum-signal-parameters.h"

#include <cmath>
#include <iomanip>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <tuple>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("DamaMloTrace");

// ------------------------------------------------ edge-stall trace helpers
namespace
{

/**
 * Frame category of a MAC header, for the edge-stall trace.
 *
 * @param h MAC header
 * @return short category name
 */
std::string
FrameCat(const WifiMacHeader& h)
{
    if (h.IsBeacon())
    {
        return "beacon";
    }
    if (h.IsAssocReq() || h.IsAssocResp() || h.IsReassocReq() || h.IsReassocResp())
    {
        return "assoc";
    }
    if (h.IsProbeReq() || h.IsProbeResp())
    {
        return "probe";
    }
    if (h.IsAction())
    {
        return "action";
    }
    if (h.IsBlockAckReq())
    {
        return "bar";
    }
    if (h.IsBlockAck())
    {
        return "ba";
    }
    if (h.IsAck())
    {
        return "ack";
    }
    if (h.IsRts() || h.IsCts())
    {
        return "rtscts";
    }
    if (h.IsQosData() && !h.HasData())
    {
        return "qosnull";
    }
    if (h.IsData())
    {
        return "data";
    }
    return "other";
}

/**
 * Category of the (first) MPDU carried by a PPDU.
 *
 * @param ppdu the PPDU
 * @param addr2 set to the transmitter address
 * @return category
 */
std::string
PpduCat(Ptr<const WifiPpdu> ppdu, Mac48Address& addr2)
{
    Ptr<const WifiPsdu> psdu = ppdu->GetPsdu();
    addr2 = psdu->GetAddr2();
    return FrameCat(psdu->GetHeader(0));
}

/// Receive-power statistics of one frame category.
struct PowStat
{
    uint64_t n{0};    ///< count
    double sum{0};    ///< sum (dBm or dB)
    double lo{1e9};   ///< minimum
    double hi{-1e9};  ///< maximum

    /**
     * Add one sample.
     * @param v value
     */
    void Add(double v)
    {
        n++;
        sum += v;
        lo = std::min(lo, v);
        hi = std::max(hi, v);
    }
};

/// Everything the edge-stall trace records for one direction on one link.
struct LinkTrace
{
    std::map<std::string, PowStat> arrival;                ///< every arriving signal: rx power (dBm)
    std::map<std::string, PowStat> decoded;                ///< decoded MPDUs: SNR (dB)
    std::map<std::string, std::map<std::string, uint64_t>> drop; ///< cat -> reason -> PPDUs
    std::map<std::string, uint64_t> tx;                    ///< transmitted PSDUs by category
    std::map<std::string, uint64_t> txMode;                ///< data PSDUs by mode
    uint64_t txDataMpdus{0};                               ///< data MPDUs transmitted
    uint64_t failData{0};                                  ///< MacTxDataFailed
    uint64_t failFinal{0};                                 ///< MacTxFinalDataFailed
    std::map<int, uint64_t> txDataPerSec;                  ///< second -> data MPDUs sent
    std::map<int, uint64_t> rxDataPerSec;                  ///< second -> data MPDUs decoded
};

} // namespace

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
 * Ideal rate control, except that data frames to selected stations use a fixed
 * mode. Used on access APs in downlink runs so that the AP sends to the slow
 * station at the slow station's fixed rate, while its fast clients keep the
 * SNR-driven rate.
 */
class FixedDestIdealWifiManager : public IdealWifiManager
{
  public:
    /**
     * Get the type ID.
     * @return the object TypeId
     */
    static TypeId GetTypeId();

    /**
     * Send data frames to this address with a fixed mode.
     *
     * @param addr link (or MLD) address of the destination station
     * @param mode data mode to use
     */
    void AddFixed(Mac48Address addr, WifiMode mode)
    {
        m_fixed[addr] = mode;
    }

  protected:
    WifiTxVector DoGetDataTxVector(WifiRemoteStation* station, MHz_u allowedWidth) override
    {
        auto it = m_fixed.find(station->m_state->m_address);
        if (it == m_fixed.end())
        {
            return IdealWifiManager::DoGetDataTxVector(station, allowedWidth);
        }
        // same TXVECTOR as ConstantRateWifiManager builds for this mode, i.e. the
        // one the slow station itself uses in the uplink (preamble, GI, width)
        const WifiMode& mode = it->second;
        uint8_t nss = std::min(GetMaxNumberOfTransmitStreams(), GetNumberOfSupportedStreams(station));
        return WifiTxVector(
            mode,
            GetDefaultTxPowerLevel(),
            GetPreambleForTransmission(mode.GetModulationClass(), GetShortPreambleEnabled()),
            GetGuardIntervalForMode(mode,
                                    GetShortGuardIntervalSupported(station),
                                    GetGuardInterval(station)),
            GetNumberOfAntennas(),
            nss,
            0,
            GetPhy()->GetTxBandwidth(mode, std::min(allowedWidth, GetChannelWidth(station))),
            GetAggregation(station));
    }

  private:
    std::map<Mac48Address, WifiMode> m_fixed; ///< destination -> fixed data mode
};

TypeId
FixedDestIdealWifiManager::GetTypeId()
{
    static TypeId tid = TypeId("ns3::FixedDestIdealWifiManager")
                            .SetParent<IdealWifiManager>()
                            .SetGroupName("Wifi")
                            .AddConstructor<FixedDestIdealWifiManager>();
    return tid;
}

NS_OBJECT_ENSURE_REGISTERED(FixedDestIdealWifiManager);

/**
 * Per-destination data-frame mode histogram of one AP link, clipped to the
 * measurement window.
 */
struct ApMcsAcc
{
    double t0{0};                                   ///< window start (s)
    double t1{0};                                   ///< window end (s)
    const std::map<Mac48Address, std::string>* who; ///< link address -> station name
    std::map<std::string, std::map<std::string, uint64_t>> count; ///< name -> mode -> frames
};

/**
 * AP PHY PSDU trace sink: count data PSDUs (>= 1000 bytes) per destination and mode.
 *
 * @param acc accumulator
 * @param psduMap transmitted PSDU(s)
 * @param txVector TX vector
 * @param txPowerW TX power (W)
 */
void
OnApPsduTx(ApMcsAcc* acc, WifiConstPsduMap psduMap, WifiTxVector txVector, double txPowerW)
{
    double now = Simulator::Now().GetSeconds();
    if (now < acc->t0 || now > acc->t1 || txVector.IsMu())
    {
        return;
    }
    for (const auto& [staId, psdu] : psduMap)
    {
        if (psdu->GetSize() < 1000)
        {
            continue;
        }
        auto it = acc->who->find(psdu->GetAddr1());
        if (it != acc->who->end())
        {
            acc->count[it->second][txVector.GetMode().GetUniqueName()]++;
        }
    }
}

/// Time stamps of one data packet along its path (s; negative = not seen).
struct PktStamp
{
    double src{-1}; ///< sent by the source IP layer
    double map{-1}; ///< forwarded by the serving MAP
    double gw{-1};  ///< forwarded by the gateway MAP (MAP 3 or MAP 6)
};

/// Matched per-packet delay sums of one station (s).
struct DelayAcc
{
    uint64_t n{0};      ///< packets delivered in the window with all stamps
    uint64_t miss{0};   ///< packets delivered in the window with a missing stamp
    double access{0};   ///< access-link delay sum
    double wireless{0}; ///< wireless-backhaul delay sum
    double wired{0};    ///< wired-path delay sum
};

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
    bool psTrace = false; // stream identities, power-save state and group frames ("P" lines)
    std::string n5Links = "all"; // "all" or "5" (N5 single-link 5 GHz)
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
    cmd.AddValue("n5Links", "N5 links: all, or 5 (single-link 5 GHz control)", n5Links);
    cmd.AddValue("newSta", "arriving fast stations as x:y:map list (map 1 or 4)", newSta);
    cmd.AddValue("psTrace", "stream identities, power-save state and group frames", psTrace);
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
        // downlink: per-destination fixed rate for slow stations (see below);
        // uplink keeps the plain ideal manager, identical to code version 2.0
        wifi.SetRemoteStationManager(downlink ? "ns3::FixedDestIdealWifiManager"
                                              : "ns3::IdealWifiManager");
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

    auto installSta = [&](NodeContainer nodes, uint32_t mapIdx, bool slow, bool oneLink = false) {
        uint8_t nLinks = 2;
        if (sloAll || (slow && confineSlow) || oneLink)
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
        devN5 = installSta(clientN5, chosenIdx, false, n5Links == "5");
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

    // --- code version 2.1 instrumentation -----------------------------------
    // Link (and MLD) MAC addresses of every station -> station name
    std::map<Mac48Address, std::string> macName;
    auto staDevice = [&](Ipv4Address a) {
        for (uint32_t k = 0; k < allSta.GetN(); ++k)
        {
            if (allSta.Get(k)->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal() == a)
            {
                return DynamicCast<WifiNetDevice>(allSta.Get(k)->GetDevice(0));
            }
        }
        return Ptr<WifiNetDevice>();
    };
    for (auto& [a, name] : staName)
    {
        Ptr<WifiNetDevice> dev = staDevice(a);
        macName[dev->GetMac()->GetAddress()] = name;
        for (uint8_t l = 0; l < dev->GetNPhys(); ++l)
        {
            macName[dev->GetMac()->GetFrameExchangeManager(l)->GetAddress()] = name;
        }
    }

    // Downlink: the access AP sends to each slow station at its fixed rate
    if (downlink)
    {
        auto fixSlow = [&](NetDeviceContainer slowDevs, uint32_t apIdx) {
            Ptr<WifiNetDevice> ap = DynamicCast<WifiNetDevice>(apDevices[apIdx].Get(0));
            for (uint32_t k = 0; k < slowDevs.GetN(); ++k)
            {
                Ptr<WifiNetDevice> sd = DynamicCast<WifiNetDevice>(slowDevs.Get(k));
                std::vector<Mac48Address> addrs{sd->GetMac()->GetAddress()};
                for (uint8_t l = 0; l < sd->GetNPhys(); ++l)
                {
                    addrs.push_back(sd->GetMac()->GetFrameExchangeManager(l)->GetAddress());
                }
                for (uint8_t l = 0; l < ap->GetNPhys(); ++l)
                {
                    auto mgr = DynamicCast<FixedDestIdealWifiManager>(ap->GetRemoteStationManager(l));
                    NS_ABORT_MSG_IF(!mgr, "downlink AP must use FixedDestIdealWifiManager");
                    for (const auto& m : addrs)
                    {
                        mgr->AddFixed(m, WifiMode(n4Rate));
                    }
                }
            }
        };
        fixSlow(devN4, 3);
        if (extraMap1Slow)
        {
            fixSlow(devEx1s, 0);
        }
        if (extraMap4Slow)
        {
            fixSlow(devEx4s, 3);
        }
    }

    // Data MCS actually used by MAP 1 and MAP 4 towards each station, per link
    std::map<std::string, ApMcsAcc*> apMcs;
    for (uint32_t idx : {0u, 3u})
    {
        Ptr<WifiNetDevice> dev = DynamicCast<WifiNetDevice>(apDevices[idx].Get(0));
        for (uint8_t l = 0; l < dev->GetNPhys(); ++l)
        {
            auto* acc = new ApMcsAcc{warmup, simTime, &macName, {}};
            std::ostringstream key;
            key << "MAP" << (idx + 1) << "_L" << +l;
            apMcs[key.str()] = acc;
            dev->GetPhy(l)->TraceConnectWithoutContext("PhyTxPsduBegin",
                                                       MakeBoundCallback(&OnApPsduTx, acc));
        }
    }

    // Matched per-packet delay: stamps at source, serving MAP, gateway MAP and
    // destination for every data packet; key = station IP (32 bit) | IP id (16 bit)
    std::map<uint64_t, PktStamp> stamps;
    std::map<std::string, DelayAcc> delayAcc;
    auto dataKey = [&](const Ipv4Header& h, uint64_t& key) {
        Ipv4Address sta = downlink ? h.GetDestination() : h.GetSource();
        bool isData = downlink ? (h.GetSource() == serverAddr && staName.count(sta))
                               : (h.GetDestination() == serverAddr && staName.count(sta));
        key = (static_cast<uint64_t>(sta.Get()) << 16) | h.GetIdentification();
        return isData;
    };
    using IpTrace = Callback<void, const Ipv4Header&, Ptr<const Packet>, uint32_t>;
    IpTrace onSend([&](const Ipv4Header& h, Ptr<const Packet>, uint32_t) {
        uint64_t k;
        if (dataKey(h, k))
        {
            stamps[k] = PktStamp{Simulator::Now().GetSeconds(), -1, -1};
        }
    });
    auto onForwardAt = [&](bool gwMap) {
        return IpTrace([&, gwMap](const Ipv4Header& h, Ptr<const Packet>, uint32_t) {
            uint64_t k;
            if (!dataKey(h, k))
            {
                return;
            }
            auto it = stamps.find(k);
            if (it != stamps.end())
            {
                (gwMap ? it->second.gw : it->second.map) = Simulator::Now().GetSeconds();
            }
        });
    };
    IpTrace onDeliver([&](const Ipv4Header& h, Ptr<const Packet>, uint32_t) {
        uint64_t k;
        if (!dataKey(h, k))
        {
            return;
        }
        auto it = stamps.find(k);
        double now = Simulator::Now().GetSeconds();
        if (now >= warmup && now <= simTime)
        {
            DelayAcc& d = delayAcc[staName[downlink ? h.GetDestination() : h.GetSource()]];
            if (it == stamps.end() || it->second.map < 0 || it->second.gw < 0)
            {
                d.miss++;
            }
            else
            {
                const PktStamp& t = it->second;
                d.n++;
                if (!downlink)
                {
                    d.access += t.map - t.src;
                    d.wireless += t.gw - t.map;
                    d.wired += now - t.gw;
                }
                else
                {
                    d.wired += t.gw - t.src;
                    d.wireless += t.map - t.gw;
                    d.access += now - t.map;
                }
            }
        }
        if (it != stamps.end())
        {
            stamps.erase(it);
        }
    });
    auto ipOf = [](Ptr<Node> n) { return n->GetObject<Ipv4L3Protocol>(); };
    NodeContainer endpoints(allSta);
    endpoints.Add(server);
    for (uint32_t k = 0; k < endpoints.GetN(); ++k)
    {
        ipOf(endpoints.Get(k))->TraceConnectWithoutContext("SendOutgoing", onSend);
        ipOf(endpoints.Get(k))->TraceConnectWithoutContext("LocalDeliver", onDeliver);
    }
    for (uint32_t idx : {0u, 3u})
    {
        ipOf(meshNodes.Get(idx))->TraceConnectWithoutContext("UnicastForward", onForwardAt(false));
    }
    for (uint32_t idx : {2u, 5u})
    {
        ipOf(meshNodes.Get(idx))->TraceConnectWithoutContext("UnicastForward", onForwardAt(true));
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


    // --------------------------------------------------- edge-stall trace
    // Traces N5 and its serving AP MLD, link by link, for the whole run (not
    // clipped to the measurement window): association and link setup, BA
    // agreements, received power of every signal from the peer (including
    // signals too weak to detect), PHY drop reasons, decoded SNR, MAC
    // retries/drops, per-second data MPDUs, N5's queue and N5's delivered bytes.
    // "L up_<l>" = N5 -> AP on link l, "dn_<l>" = AP -> N5 on link l.
    std::map<std::string, LinkTrace> ltr;
    std::map<std::string, uint64_t> macCnt;
    std::vector<std::string> events;
    auto ev = [&](const std::string& s) {
        std::ostringstream o;
        o << std::fixed << std::setprecision(6) << "E " << Simulator::Now().GetSeconds() << " "
          << s;
        if (events.size() < 400)
        {
            events.push_back(o.str());
        }
    };
    std::map<int, std::string> perSec; // second -> sampled state line
    if (scenario != 0)
    {
        Ptr<WifiNetDevice> n5 = DynamicCast<WifiNetDevice>(devN5.Get(0));
        Ptr<WifiNetDevice> ap = DynamicCast<WifiNetDevice>(apDevices[chosenIdx].Get(0));
        Ptr<StaWifiMac> n5mac = DynamicCast<StaWifiMac>(n5->GetMac());
        const uint32_t n5Node = clientN5.Get(0)->GetId();
        const uint32_t apNode = meshNodes.Get(chosenIdx)->GetId();
        auto addrsOf = [](Ptr<WifiNetDevice> d) {
            std::set<Mac48Address> s{d->GetMac()->GetAddress()};
            for (uint8_t l = 0; l < d->GetNPhys(); ++l)
            {
                s.insert(d->GetMac()->GetFrameExchangeManager(l)->GetAddress());
            }
            return s;
        };
        auto n5Addr = std::make_shared<std::set<Mac48Address>>(addrsOf(n5));
        auto apAddr = std::make_shared<std::set<Mac48Address>>(addrsOf(ap));

        // association, link setup, BA agreements
        n5mac->TraceConnectWithoutContext("Assoc", Callback<void, Mac48Address>([&](Mac48Address a) {
                                              std::ostringstream o;
                                              o << "assoc " << a;
                                              ev(o.str());
                                          }));
        n5mac->TraceConnectWithoutContext("DeAssoc",
                                          Callback<void, Mac48Address>([&](Mac48Address a) {
                                              std::ostringstream o;
                                              o << "deassoc " << a;
                                              ev(o.str());
                                          }));
        n5mac->TraceConnectWithoutContext(
            "LinkSetupCompleted",
            Callback<void, uint8_t, Mac48Address>([&](uint8_t l, Mac48Address a) {
                std::ostringstream o;
                o << "linksetup link=" << +l << " ap=" << a;
                ev(o.str());
            }));
        auto baTrace = [&](const std::string& who, std::shared_ptr<std::set<Mac48Address>> only) {
            return Callback<void, Time, Mac48Address, uint8_t, OriginatorBlockAckAgreement::State>(
                [&, who, only](Time, Mac48Address r, uint8_t tid, OriginatorBlockAckAgreement::State st) {
                    if (only && !only->count(r))
                    {
                        return;
                    }
                    static const char* names[] = {"PENDING", "ESTABLISHED", "NO_REPLY", "RESET", "REJECTED"};
                    std::ostringstream o;
                    o << "ba_" << who << " tid=" << +tid << " state=" << names[st];
                    ev(o.str());
                });
        };
        n5mac->GetQosTxop(AC_BE)->GetBaManager()->TraceConnectWithoutContext("AgreementState",
                                                                             baTrace("n5", nullptr));
        ap->GetMac()->GetQosTxop(AC_BE)->GetBaManager()->TraceConnectWithoutContext(
            "AgreementState",
            baTrace("ap", n5Addr));

        // MAC drops, response timeouts, drops before the queue
        auto macTrace = [&](const std::string& who, std::shared_ptr<std::set<Mac48Address>> only) {
            return std::make_tuple(
                Callback<void, WifiMacDropReason, Ptr<const WifiMpdu>>(
                    [&, who, only](WifiMacDropReason r, Ptr<const WifiMpdu> m) {
                        if (only && !only->count(m->GetHeader().GetAddr1()))
                        {
                            return;
                        }
                        static const char* names[] = {"FAILED_ENQUEUE", "EXPIRED_LIFETIME", "RETRY_LIMIT", "QOS_OLD"};
                        std::string k = "drop_" + who + "_" + FrameCat(m->GetHeader()) + "_" + names[r];
                        if (macCnt[k]++ < 3)
                        {
                            ev(k);
                        }
                    }),
                Callback<void, uint8_t, Ptr<const WifiMpdu>, const WifiTxVector&>(
                    [&, who, only](uint8_t, Ptr<const WifiMpdu> m, const WifiTxVector&) {
                        if (!only || only->count(m->GetHeader().GetAddr1()))
                        {
                            macCnt["mpduTimeout_" + who + "_" + FrameCat(m->GetHeader())]++;
                        }
                    }),
                Callback<void, uint8_t, Ptr<const WifiPsdu>, const WifiTxVector&>(
                    [&, who, only](uint8_t, Ptr<const WifiPsdu> p, const WifiTxVector&) {
                        if (!only || only->count(p->GetAddr1()))
                        {
                            macCnt["psduTimeout_" + who + "_" + FrameCat(p->GetHeader(0))]++;
                        }
                    }));
        };
        for (auto [dev, who, only] :
             {std::make_tuple(n5, std::string("n5"), std::shared_ptr<std::set<Mac48Address>>()),
              std::make_tuple(ap, std::string("ap"), n5Addr)})
        {
            auto [d, t1, t2] = macTrace(who, only);
            dev->GetMac()->TraceConnectWithoutContext("DroppedMpdu", d);
            dev->GetMac()->TraceConnectWithoutContext("MpduResponseTimeout", t1);
            dev->GetMac()->TraceConnectWithoutContext("PsduResponseTimeout", t2);
        }
        n5mac->TraceConnectWithoutContext("MacTxDrop", Callback<void, Ptr<const Packet>>([&](Ptr<const Packet>) {
                                              if (macCnt["macTxDrop_n5"]++ < 3)
                                              {
                                                  ev("macTxDrop_n5 (not associated)");
                                              }
                                          }));

        // PHY and station-manager traces, per link and direction
        auto hookLink = [&](Ptr<WifiNetDevice> txDev,
                            Ptr<WifiNetDevice> rxDev,
                            uint32_t txNode,
                            std::shared_ptr<std::set<Mac48Address>> txAddrs,
                            std::shared_ptr<std::set<Mac48Address>> rxAddrs,
                            const std::string& dir) {
            for (uint8_t l = 0; l < rxDev->GetNPhys(); ++l)
            {
                std::string key = dir + "_" + std::to_string(l);
                LinkTrace* lt = &ltr[key];
                Ptr<SpectrumWifiPhy> rphy = DynamicCast<SpectrumWifiPhy>(rxDev->GetPhy(l));
                rphy->TraceConnectWithoutContext(
                    "SignalArrival",
                    Callback<void, Ptr<const SpectrumSignalParameters>, uint32_t, double, Time>(
                        [lt, txNode, rphy](Ptr<const SpectrumSignalParameters> s, uint32_t from, double pw, Time) {
                            auto w = DynamicCast<const WifiSpectrumSignalParameters>(s);
                            // every PHY is attached to the 5 and 6 GHz channels; keep only
                            // signals on the channel this PHY operates on
                            if (from != txNode || !w ||
                                std::abs(w->ppdu->GetTxCenterFreqs().front() - rphy->GetFrequency()) > 1)
                            {
                                return;
                            }
                            Mac48Address a2;
                            std::string cat = PpduCat(w->ppdu, a2);
                            lt->arrival[cat].Add(pw);
                        }));
                rphy->TraceConnectWithoutContext(
                    "PhyRxPpduDrop",
                    Callback<void, Ptr<const WifiPpdu>, WifiPhyRxfailureReason>(
                        [lt, txAddrs](Ptr<const WifiPpdu> p, WifiPhyRxfailureReason r) {
                            Mac48Address a2;
                            std::string cat = PpduCat(p, a2);
                            if (txAddrs->count(a2))
                            {
                                std::ostringstream o;
                                o << r;
                                lt->drop[cat][o.str()]++;
                            }
                        }));
                rphy->TraceConnectWithoutContext(
                    "MonitorSnifferRx",
                    Callback<void, Ptr<const Packet>, uint16_t, WifiTxVector, MpduInfo, SignalNoiseDbm, uint16_t>(
                        [lt, txAddrs](Ptr<const Packet> pkt, uint16_t, WifiTxVector, MpduInfo mi, SignalNoiseDbm sn, uint16_t) {
                            Ptr<Packet> c = pkt->Copy();
                            if (mi.type != NORMAL_MPDU)
                            {
                                AmpduSubframeHeader sh;
                                c->RemoveHeader(sh);
                            }
                            WifiMacHeader h;
                            c->PeekHeader(h);
                            // ACK/CTS carry no transmitter address: attribute by receiver instead
                            bool ours = (h.IsAck() || h.IsCts()) ? true : txAddrs->count(h.GetAddr2()) > 0;
                            if (!ours)
                            {
                                return;
                            }
                            std::string cat = FrameCat(h);
                            if (h.IsAck() || h.IsCts())
                            {
                                cat += "_any";
                            }
                            lt->decoded[cat].Add(sn.signal - sn.noise);
                            if (cat == "data")
                            {
                                lt->rxDataPerSec[static_cast<int>(Simulator::Now().GetSeconds())]++;
                            }
                        }));
            }
            for (uint8_t l = 0; l < txDev->GetNPhys(); ++l)
            {
                std::string key = dir + "_" + std::to_string(l);
                LinkTrace* lt = &ltr[key];
                txDev->GetPhy(l)->TraceConnectWithoutContext(
                    "PhyTxPsduBegin",
                    Callback<void, WifiConstPsduMap, WifiTxVector, double>(
                        [lt, rxAddrs](WifiConstPsduMap m, WifiTxVector tv, double) {
                            for (const auto& [id, psdu] : m)
                            {
                                if (!rxAddrs->count(psdu->GetAddr1()) && !psdu->GetAddr1().IsGroup())
                                {
                                    continue;
                                }
                                std::string cat = FrameCat(psdu->GetHeader(0));
                                lt->tx[cat]++;
                                if (cat == "data")
                                {
                                    lt->txMode[tv.GetMode().GetUniqueName()]++;
                                    lt->txDataMpdus += psdu->GetNMpdus();
                                    lt->txDataPerSec[static_cast<int>(Simulator::Now().GetSeconds())] +=
                                        psdu->GetNMpdus();
                                }
                            }
                        }));
                Ptr<WifiRemoteStationManager> rsm = txDev->GetRemoteStationManager(l);
                rsm->TraceConnectWithoutContext("MacTxDataFailed",
                                                Callback<void, Mac48Address>([lt, rxAddrs](Mac48Address a) {
                                                    if (rxAddrs->count(a))
                                                    {
                                                        lt->failData++;
                                                    }
                                                }));
                rsm->TraceConnectWithoutContext("MacTxFinalDataFailed",
                                                Callback<void, Mac48Address>([lt, rxAddrs](Mac48Address a) {
                                                    if (rxAddrs->count(a))
                                                    {
                                                        lt->failFinal++;
                                                    }
                                                }));
            }
        };
        hookLink(n5, ap, n5Node, n5Addr, apAddr, "up");
        hookLink(ap, n5, apNode, apAddr, n5Addr, "dn");

        // per-second state: association, setup links, queue, N5 delivered bytes
        Ipv4Address n5Ip = clientN5.Get(0)->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
        auto lastRx = std::make_shared<uint64_t>(0);
        for (int t = 1; t <= static_cast<int>(simTime); ++t)
        {
            Simulator::Schedule(Seconds(t), [&, t, n5mac, n5Ip, lastRx]() {
                uint64_t rx = 0;
                for (const auto& [id, st] : monitor->GetFlowStats())
                {
                    Ipv4Address sta;
                    if (dataFlowStation(id, sta) && sta == n5Ip)
                    {
                        rx += st.rxBytes;
                    }
                }
                std::ostringstream o;
                o << "S " << t << " assoc=" << n5mac->IsAssociated() << " links=";
                for (auto l : n5mac->GetSetupLinkIds())
                {
                    o << +l << ";";
                }
                o << " q=" << n5mac->GetTxopQueue(AC_BE)->GetNPackets()
                  << " n5Mbps=" << (rx - *lastRx) * 8.0 / 1e6;
                *lastRx = rx;
                perSec[t] = o.str();
            });
        }
    }

    // ------------------------------------------------------ power-save trace
    // Opt-in (--psTrace). Streams "P" lines as they happen (flushed, so they
    // survive an abort): runtime identities of the APs and stations, AP-side
    // power-save state of every associated station link (polled every 1 ms;
    // only stations in the AP's own station list are queried, so the poll
    // creates no station-manager state), the STA-side power-management mode,
    // and every group-addressed frame the AP MLDs of MAP 1 and MAP 4 transmit.
    if (psTrace)
    {
        std::vector<std::tuple<std::string, Ptr<WifiNetDevice>, uint32_t>> stas = {
            {"N1", DynamicCast<WifiNetDevice>(devN1N2.Get(0)), clientN1N2.Get(0)->GetId()},
            {"N2", DynamicCast<WifiNetDevice>(devN1N2.Get(1)), clientN1N2.Get(1)->GetId()},
            {"N3", DynamicCast<WifiNetDevice>(devN3.Get(0)), clientN3N4.Get(0)->GetId()},
            {"N4", DynamicCast<WifiNetDevice>(devN4.Get(0)), clientN3N4.Get(1)->GetId()}};
        if (scenario != 0)
        {
            stas.emplace_back("N5", DynamicCast<WifiNetDevice>(devN5.Get(0)), clientN5.Get(0)->GetId());
        }
        std::vector<std::tuple<std::string, Ptr<WifiNetDevice>, uint32_t>> aps = {
            {"MAP1", DynamicCast<WifiNetDevice>(apDevices[0].Get(0)), meshNodes.Get(0)->GetId()},
            {"MAP4", DynamicCast<WifiNetDevice>(apDevices[3].Get(0)), meshNodes.Get(3)->GetId()}};
        auto names = std::make_shared<std::map<Mac48Address, std::string>>();
        auto ident = [&](const std::string& role, const std::string& name, Ptr<WifiNetDevice> d, uint32_t node) {
            std::cout << "P id " << role << " " << name << " node=" << node
                      << " mld=" << d->GetMac()->GetAddress();
            (*names)[d->GetMac()->GetAddress()] = name;
            for (uint8_t l = 0; l < d->GetNPhys(); ++l)
            {
                Mac48Address a = d->GetMac()->GetFrameExchangeManager(l)->GetAddress();
                (*names)[a] = name + "/L" + std::to_string(l);
                std::cout << " L" << +l << "=" << a << "@" << d->GetPhy(l)->GetPhyBand() << "/"
                          << d->GetPhy(l)->GetFrequency();
            }
            std::cout << std::endl;
        };
        for (auto& [n, d, node] : aps)
        {
            ident("ap", n, d, node);
        }
        for (auto& [n, d, node] : stas)
        {
            ident("sta", n, d, node);
        }
        auto nm = [names](Mac48Address a) {
            auto it = names->find(a);
            std::ostringstream o;
            o << a;
            return it == names->end() ? o.str() : it->second;
        };
        auto last = std::make_shared<std::map<std::string, int>>();
        auto report = [last](const std::string& key, int v, const std::string& line) {
            auto it = last->find(key);
            if (it == last->end() || it->second != v)
            {
                (*last)[key] = v;
                std::cout << std::fixed << std::setprecision(6) << "P " << Simulator::Now().GetSeconds()
                          << " " << line << std::endl;
            }
        };
        for (int ms = 0; ms <= static_cast<int>(simTime * 1000); ++ms)
        {
            Simulator::Schedule(MilliSeconds(ms), [aps, stas, nm, report]() {
                for (auto& [n, d, node] : aps)
                {
                    Ptr<ApWifiMac> am = DynamicCast<ApWifiMac>(d->GetMac());
                    for (uint8_t l = 0; l < d->GetNPhys(); ++l)
                    {
                        std::size_t nps = am->GetNStationsInPsMode(l);
                        report(n + "/n" + std::to_string(l), static_cast<int>(nps),
                               "apPsCount " + n + " L" + std::to_string(l) + " n=" + std::to_string(nps));
                        for (const auto& [aid, a] : am->GetStaList(l))
                        {
                            int ps = d->GetRemoteStationManager(l)->IsInPsMode(a) ? 1 : 0;
                            report(n + "/" + std::to_string(l) + "/" + nm(a), ps,
                                   "apPs " + n + " L" + std::to_string(l) + " sta=" + nm(a) +
                                       " ps=" + std::to_string(ps));
                        }
                    }
                }
                for (auto& [n, d, node] : stas)
                {
                    Ptr<StaWifiMac> sm = DynamicCast<StaWifiMac>(d->GetMac());
                    for (auto l : sm->GetSetupLinkIds())
                    {
                        int pm = sm->GetPmMode(l);
                        report(n + "/pm" + std::to_string(l), pm,
                               "staPm " + n + " L" + std::to_string(+l) + " mode=" + std::to_string(pm));
                    }
                }
            });
        }
        // group-addressed frames sent by the MAP 1 / MAP 4 AP MLDs (beacons only counted)
        auto beacons = std::make_shared<std::map<std::string, uint64_t>>();
        for (auto& [n, d, node] : aps)
        {
            for (uint8_t l = 0; l < d->GetNPhys(); ++l)
            {
                std::string tag = n + " L" + std::to_string(l);
                d->GetPhy(l)->TraceConnectWithoutContext(
                    "PhyTxPsduBegin",
                    Callback<void, WifiConstPsduMap, WifiTxVector, double>(
                        [tag, nm, beacons](WifiConstPsduMap m, WifiTxVector, double) {
                            for (const auto& [id, psdu] : m)
                            {
                                if (!psdu->GetAddr1().IsGroup())
                                {
                                    continue;
                                }
                                const WifiMacHeader& h = psdu->GetHeader(0);
                                if (h.IsBeacon())
                                {
                                    (*beacons)[tag]++;
                                    continue;
                                }
                                std::ostringstream o;
                                o << std::fixed << std::setprecision(6) << "P "
                                  << Simulator::Now().GetSeconds() << " grp " << tag << " type=" << h.GetTypeString()
                                  << " a1=" << h.GetAddr1() << " a2=" << nm(h.GetAddr2())
                                  << " a3=" << nm(h.GetAddr3()) << " bytes=" << psdu->GetSize()
                                  << " beaconsBefore=" << (*beacons)[tag];
                                if (h.IsData() && psdu->GetNMpdus() == 1)
                                {
                                    Ptr<Packet> c = psdu->GetPayload(0)->Copy();
                                    LlcSnapHeader llc;
                                    if (c->RemoveHeader(llc))
                                    {
                                        o << " ethertype=0x" << std::hex << llc.GetType() << std::dec;
                                        if (llc.GetType() == 0x0806)
                                        {
                                            ArpHeader arp;
                                            c->RemoveHeader(arp);
                                            o << " arp=" << (arp.IsRequest() ? "request" : "reply")
                                              << " src=" << arp.GetSourceIpv4Address()
                                              << " dst=" << arp.GetDestinationIpv4Address();
                                        }
                                        else if (llc.GetType() == 0x0800)
                                        {
                                            Ipv4Header ip;
                                            c->RemoveHeader(ip);
                                            o << " ip src=" << ip.GetSource() << " dst=" << ip.GetDestination()
                                              << " proto=" << +ip.GetProtocol();
                                        }
                                    }
                                }
                                std::cout << o.str() << std::endl;
                            }
                        }));
            }
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

    // code version 2.1: matched per-packet delay split (ms) and AP data MCS
    std::cout << "R codeVersion 2.1\n";
    DelayAcc tot;
    for (auto& [name, d] : delayAcc)
    {
        std::cout << "R dN_" << name << " " << d.n << "\n";
        std::cout << "R dMiss_" << name << " " << d.miss << "\n";
        if (d.n)
        {
            std::cout << "R dAcc_" << name << " " << d.access / d.n * 1e3 << "\n";
            std::cout << "R dWbh_" << name << " " << d.wireless / d.n * 1e3 << "\n";
            std::cout << "R dWired_" << name << " " << d.wired / d.n * 1e3 << "\n";
            std::cout << "R dE2e_" << name << " " << (d.access + d.wireless + d.wired) / d.n * 1e3
                      << "\n";
        }
        tot.n += d.n;
        tot.miss += d.miss;
        tot.access += d.access;
        tot.wireless += d.wireless;
        tot.wired += d.wired;
    }
    std::cout << "R dN " << tot.n << "\nR dMiss " << tot.miss << "\n";
    if (tot.n)
    {
        std::cout << "R dAccMs " << tot.access / tot.n * 1e3 << "\nR dWbhMs "
                  << tot.wireless / tot.n * 1e3 << "\nR dWiredMs " << tot.wired / tot.n * 1e3
                  << "\nR dE2eMs " << (tot.access + tot.wireless + tot.wired) / tot.n * 1e3 << "\n";
    }
    for (auto& [link, acc] : apMcs)
    {
        for (auto& [name, modes] : acc->count)
        {
            std::string best;
            uint64_t bestN = 0;
            uint64_t n = 0;
            for (auto& [mode, c] : modes)
            {
                n += c;
                if (c > bestN)
                {
                    bestN = c;
                    best = mode;
                }
            }
            std::cout << "R apmcs_" << link << "_" << name << " " << best << "\n";
            std::cout << "R apframes_" << link << "_" << name << " " << n << "\n";
            std::cout << "R apmcsShare_" << link << "_" << name << " "
                      << (n ? static_cast<double>(bestN) / n : 0.0) << "\n";
        }
    }


    // edge-stall trace output
    std::cout << "R traceVersion 1\nR n5Links " << n5Links << "\n";
    for (const auto& e : events)
    {
        std::cout << e << "\n";
    }
    for (const auto& [t, s] : perSec)
    {
        std::cout << s << "\n";
    }
    for (const auto& [k, n] : macCnt)
    {
        std::cout << "M " << k << " " << n << "\n";
    }
    for (auto& [key, lt] : ltr)
    {
        for (auto& [cat, p] : lt.arrival)
        {
            std::cout << "L " << key << " arrival_" << cat << " n=" << p.n
                      << " meanDbm=" << (p.n ? p.sum / p.n : 0) << " minDbm=" << p.lo
                      << " maxDbm=" << p.hi << "\n";
        }
        for (auto& [cat, p] : lt.decoded)
        {
            std::cout << "L " << key << " decoded_" << cat << " n=" << p.n
                      << " meanSnrDb=" << (p.n ? p.sum / p.n : 0) << " minSnrDb=" << p.lo << "\n";
        }
        for (auto& [cat, rs] : lt.drop)
        {
            for (auto& [r, n] : rs)
            {
                std::cout << "L " << key << " phydrop_" << cat << "_" << r << " " << n << "\n";
            }
        }
        for (auto& [cat, n] : lt.tx)
        {
            std::cout << "L " << key << " tx_" << cat << " " << n << "\n";
        }
        for (auto& [m, n] : lt.txMode)
        {
            std::cout << "L " << key << " txmode_" << m << " " << n << "\n";
        }
        std::cout << "L " << key << " txDataMpdus " << lt.txDataMpdus << "\nL " << key
                  << " macTxDataFailed " << lt.failData << "\nL " << key
                  << " macTxFinalDataFailed " << lt.failFinal << "\n";
        std::ostringstream tx;
        std::ostringstream rx;
        for (int t = 0; t <= static_cast<int>(simTime); ++t)
        {
            tx << (lt.txDataPerSec.count(t) ? lt.txDataPerSec[t] : 0) << ",";
            rx << (lt.rxDataPerSec.count(t) ? lt.rxDataPerSec[t] : 0) << ",";
        }
        std::cout << "L " << key << " txDataPerSec " << tx.str() << "\nL " << key
                  << " rxDataPerSec " << rx.str() << "\n";
    }

    Simulator::Destroy();
    return 0;
}
