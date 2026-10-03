"""Summarize the edge-stall trace runs (run_edge_trace.sh) into one table.

Per run: N5 throughput, per link (0 = 5 GHz, 1 = 6 GHz) the measured receive
power of AP beacons at N5 and of N5 data at the AP, how many N5 data MPDUs were
sent / decoded on each link, preamble-detection failures, MAC retry-limit drops
and the BA agreement events. Writes <dir>/summary.json, where <dir> is the
optional first argument (default results/edge_trace).
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results", "edge_trace")


def parse(path):
    r = {"R": {}, "E": [], "S": [], "M": {}, "L": {}}
    for line in open(path):
        line = line.rstrip("\n")
        tag, _, rest = line.partition(" ")
        if tag == "R":
            k, _, v = rest.partition(" ")
            r["R"][k] = v
        elif tag == "E":
            r["E"].append(rest)
        elif tag == "S":
            r["S"].append(rest)
        elif tag == "M":
            k, v = rest.split()
            r["M"][k] = int(v)
        elif tag == "L":
            link, k, v = rest.split(" ", 2)
            r["L"].setdefault(link, {})[k] = v
    return r


def field(s, name):
    m = re.search(name + r"=(-?[0-9.e+-]+)", s or "")
    return float(m.group(1)) if m else None


def summarize(r):
    L = r["L"]
    out = {"tputN5": float(r["R"].get("tput_N5", "nan")), "n5Links": r["R"].get("n5Links")}
    for l in ("0", "1"):
        up = L.get("up_" + l, {})
        dn = L.get("dn_" + l, {})
        if not up and not dn:
            continue
        out["L" + l] = {
            "beaconDbmAtN5": field(dn.get("arrival_beacon"), "meanDbm"),
            "dataDbmAtAp": field(up.get("arrival_data"), "meanDbm"),
            "beaconsDecodedAtN5": field(dn.get("decoded_beacon"), "n") or 0,
            "beaconsPreambleFailAtN5": int(dn.get("phydrop_beacon_PREAMBLE_DETECT_FAILURE", 0)),
            "upDataMpdusSent": int(up.get("txDataMpdus", 0)),
            "upDataDecodedAtAp": field(up.get("decoded_data"), "n") or 0,
            "upDataPreambleFailAtAp": int(up.get("phydrop_data_PREAMBLE_DETECT_FAILURE", 0)),
            "upTxMode": sorted(k[7:] for k in up if k.startswith("txmode_")),
            "upMacTxFinalFailed": int(up.get("macTxFinalDataFailed", 0)),
            "upTxPerSec": up.get("txDataPerSec"),
            "dnDataPreambleFailAtN5": int(dn.get("phydrop_data_PREAMBLE_DETECT_FAILURE", 0)),
        }
    out["n5RetryLimitDrops"] = r["M"].get("drop_n5_data_RETRY_LIMIT", 0)
    out["n5BarTimeouts"] = r["M"].get("psduTimeout_n5_bar", 0)
    out["events"] = [e for e in r["E"] if "drop_" not in e]
    return out


def main():
    res = {}
    for p in sorted(glob.glob(os.path.join(OUT, "*.txt"))):
        res[os.path.basename(p)[:-4]] = summarize(parse(p))
    json.dump(res, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    hdr = f"{'run':26s} {'N5':>6s} | {'L0 bcn':>7s} {'L0 up':>7s} {'sent/dec':>11s} | {'L1 bcn':>8s} {'L1 up':>8s} {'sent/dec':>11s} {'PDfail':>6s} | {'RLdrop':>6s}"
    print(hdr)
    for k, s in res.items():
        l0 = s.get("L0", {})
        l1 = s.get("L1", {})
        f = lambda v, w=7, d=2: f"{v:{w}.{d}f}" if isinstance(v, float) else f"{'-':>{w}s}"
        print(f"{k:26s} {s['tputN5']:6.2f} | {f(l0.get('beaconDbmAtN5'))} {f(l0.get('dataDbmAtAp'))} "
              f"{str(l0.get('upDataMpdusSent', '-')) + '/' + str(int(l0.get('upDataDecodedAtAp', 0))):>11s} | "
              f"{f(l1.get('beaconDbmAtN5'), 8, 3)} {f(l1.get('dataDbmAtAp'), 8, 3)} "
              f"{str(l1.get('upDataMpdusSent', '-')) + '/' + str(int(l1.get('upDataDecodedAtAp', 0))):>11s} "
              f"{l1.get('upDataPreambleFailAtAp', '-'):>6} | {s['n5RetryLimitDrops']:6d}")


if __name__ == "__main__":
    main()
