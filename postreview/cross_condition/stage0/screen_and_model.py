#!/usr/bin/env python3
"""Stage 0 desk screen (no simulation): per condition, the position lattice, candidate set J (1 dB margin, 0.029 dB
offset), RSSI side, hidden-station flags, N5 SNR, and the per-cell airtime-model utility ordering (assumptions in
docstring of model()). Output: stage0_screen.json. Deterministic."""
import json, math
OFF, FLOOR, MARGIN, NOISE = 0.029, -82.0, 1.0, -94.0
F5 = {1: 5.180e9, 4: 5.240e9}; F6 = {1: 5.955e9, 4: 6.015e9}
def pr(a, b, f, n=2.5): return 20 - 20 * math.log10(4 * math.pi * f / 299792458) - 10 * n * math.log10(max(math.dist(a, b), 1.0)) - OFF
# Approximate EHT 20 MHz, 1 SS, 0.8 us GI rates (Mbit/s) and SNR thresholds (dB). Anchor: in v2.0 N4 at 15 dB SNR
# decodes MCS 4 but not MCS 5 (experiments.py note); spacing between thresholds from the 802.11 minimum-sensitivity
# ordering. APPROXIMATE; used only for the model ordering, never for any simulated outcome.
RATE = [8.6, 17.2, 25.8, 34.4, 51.6, 68.8, 77.4, 86.0, 103.2, 114.7, 129.0, 143.4, 154.9, 172.1]
THR = [2.5, 5.5, 7.5, 10.5, 14.5, 18.5, 19.5, 20.5, 25.5, 27.5, 30.5, 32.5, 35.5, 38.5]
def ideal_rate(p_dbm):
    snr = p_dbm - NOISE; ok = [r for r, t in zip(RATE, THR) if snr >= t]
    return ok[-1] if ok else 0.0
MCS = {"EhtMcs0": 8.6, "EhtMcs2": 25.8, "EhtMcs4": 51.6}

def condition(cid):
    S = 100.0 if cid == "T2" else 150.0
    M1, M4 = (0.0, 2 * S), (0.0, S)
    sta1 = {"N1": ((0.0, 2 * S + 20), None), "N2": ((20.0, 2 * S), None)}
    sta4 = {"N3": ((0.0, S - 20), None), "N4": ((120.0, S), "EhtMcs4" if cid == "T3" else "EhtMcs0")}
    if cid == "T1":   # extraMap4Slow = 1: ring k=0, r = 20, phase pi/4
        sta4["X4s0"] = ((20 * math.cos(math.pi / 4), S + 20 * math.sin(math.pi / 4)), "EhtMcs0")
    if cid == "T3":   # extraMap4 = 2: ring r = 20 + 5 (k % 4), angles 0 and pi
        sta4["X4f0"] = ((20.0, S), None); sta4["X4f1"] = ((-25.0, S), None)
    return S, M1, M4, sta1, sta4

def model(p5, M1, M4, sta1, sta4, nl, L_bits=1500 * 8, T_oh=100e-6):
    """Per-cell airtime model (manuscript Sec. airtime, extended to utility). Assumptions: every station saturated;
    CSMA/CA gives each station on a link one frame per round (Heusse 2003); frame time T = T_oh + L/R; no
    aggregation, collisions, hidden stations, backhaul or TCP; under MLO every MLD is on both links of its MAP and
    the per-link throughputs add; fast stations and N5 use the ideal rate from SNR. Returns sum-log (Mbit/s) for
    N5 -> MAP 1 and N5 -> MAP 4 over the stations of both cells."""
    out = {}
    for a in (1, 4):
        tot = 0.0
        for mid, M, sta in ((1, M1, sta1), (4, M4, sta4)):
            members = dict(sta)
            if a == mid:
                members["N5"] = (p5, None)
            th = {k: 0.0 for k in members}
            for l in range(nl):
                f = (F5 if l == 0 else F6)[mid]
                R = {k: (MCS[r] if r else ideal_rate(pr(pos, M, f))) for k, (pos, r) in members.items()}
                if min(R.values()) <= 0:
                    return None
                T = {k: T_oh + L_bits / (R[k] * 1e6) for k in members}
                rnd = sum(T.values())
                for k in members:
                    th[k] += L_bits / rnd / 1e6
            tot += sum(math.log(max(v, 1e-3)) for v in th.values())
        out[a] = tot
    return out

res = {}
for cid in ("T1", "T2", "T3"):
    S, M1, M4, sta1, sta4 = condition(cid)
    lat = [(x, S + f * S) for x in (10, 25, 40, 55, 70, 85, 100) for f in (0.2, 0.4)]
    rows = []
    for p in lat:
        r = {"pos": p}
        r["P5"] = {m: round(pr(p, M, F5[m]), 2) for m, M in ((1, M1), (4, M4))}
        r["P6"] = {m: round(pr(p, M, F6[m]), 2) for m, M in ((1, M1), (4, M4))}
        J_slo = all(r["P5"][m] >= FLOOR + MARGIN for m in (1, 4))
        J_mlo = J_slo and all(r["P6"][m] >= FLOOR + MARGIN for m in (1, 4))
        rssi4 = math.dist(p, M4) < math.dist(p, M1)
        r["qualifies"] = J_slo and J_mlo and rssi4
        r["hidden"] = {m: [k for k, (q, _) in (sta1 if m == 1 else sta4).items()
                           if min(pr(p, q, F5[m]), pr(p, q, F6[m])) < FLOOR] for m in (1, 4)}
        r["snr5"] = {m: round(r["P5"][m] - NOISE, 1) for m in (1, 4)}
        rows.append(r)
    q = [r for r in rows if r["qualifies"]]
    if len(q) > 8:
        idx = sorted({round(i * (len(q) - 1) / 7) for i in range(8)})
        q = [q[i] for i in idx]
    feasible = len(q) >= 6
    for r in q:
        r["model"] = {}
        for mode, nl in (("slo", 1), ("mlo", 2)):
            base = model(r["pos"], M1, M4, sta1, sta4, nl)
            sens = [model(r["pos"], M1, M4, sta1, sta4, nl, L, T) for L in (1500 * 8, 15000 * 8) for T in (50e-6, 150e-6)]
            r["model"][mode] = {"sumlog_MAP1": round(base[1], 3), "sumlog_MAP4": round(base[4], 3),
                                "better": 1 if base[1] > base[4] else 4,
                                "robust_over_L_Toh": all((s[1] > s[4]) == (base[1] > base[4]) for s in sens)}
    res[cid] = {"spacing": S, "n_qualifying": sum(r["qualifies"] for r in rows), "selected": q, "feasible": feasible,
                "N": 5 + (1 if cid == "T1" else 2 if cid == "T3" else 0)}
    print(cid, "S=%d" % S, "qualifying", res[cid]["n_qualifying"], "selected", len(q), "feasible", feasible)
    for r in q:
        print("  ", r["pos"], "P5", r["P5"], "hidden", r["hidden"], "| model SLO better MAP%d %s, MLO better MAP%d %s" % (
            r["model"]["slo"]["better"], "robust" if r["model"]["slo"]["robust_over_L_Toh"] else "NOT robust",
            r["model"]["mlo"]["better"], "robust" if r["model"]["mlo"]["robust_over_L_Toh"] else "NOT robust"))
json.dump(res, open("stage0_screen.json", "w"), indent=1)
