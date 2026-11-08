#!/usr/bin/env python3
"""Claim-evidence clearance on stored runs only (rules: CLEARANCE_RULES.md). Run from revision_v2/."""
import json, re
import numpy as np
import analyze, policies as P
from experiments import GRID_SEEDS, GRID_X, GRID_Y
idx = analyze.index(analyze.load_runs()); rate = "EhtMcs0"; modes = ("slo", "mlo")
R = json.load(open("artifact_out/dama-mlo-code-data/data/common_candidate_diag_offset-0.029.json"))
common = [tuple(p) for p in R["common_positions"]]; S = len(GRID_SEEDS); out = {}
tp = lambda o: {k: v for k, v in o.items() if re.fullmatch(r"tput_N\d+", k)}
def util(o, fl): return sum(np.log(max(v, fl)) for v in tp(o).values())
def mats(fl=None):
    G = {}
    for m in modes:
        rows, cf = [], []
        for x, y in common:
            c = analyze.context(idx, m, rate, x, y, GRID_SEEDS[0])
            rew = np.array([[(idx[(m, rate, a + 1, x, y, s)]["sumLog"] if fl is None else util(idx[(m, rate, a + 1, x, y, s)], fl)) for s in GRID_SEEDS] for a in (0, 1)])
            ra = 0 if c["rssi"][0] >= c["rssi"][1] else 1; oa = int(rew[1].mean() > rew[0].mean())
            rows.append(rew[oa] - rew[ra])
            fold = [rew[int(np.delete(rew[1], i).mean() > np.delete(rew[0], i).mean())][i] - rew[ra][i] for i in range(S)]
            cf.append(fold)
        G[m] = (np.array(rows), np.array(cf))
    return G
def boot(a, b, keep=None, n=20000, seed=20261007):
    rng = np.random.default_rng(seed); P_ = a.shape[0]
    keep = keep if keep is not None else [list(range(S))] * P_
    use = [i for i in range(P_) if keep[i]]
    pt = np.mean([a[i, keep[i]].mean() - b[i, keep[i]].mean() for i in use])
    draw = rng.integers(len(use), size=(n, len(use))); v = np.zeros(n)
    for j, i in enumerate(use):
        k = np.array(keep[i]); d = (a[i] - b[i])[k]
        pick = d[rng.integers(len(k), size=(n, len(use), len(k)))].mean(axis=2)
        v += (pick * (draw == j)).sum(axis=1)
    v /= len(use)
    return [float(pt), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))], len(use), int(sum(len(keep[i]) for i in use))
G = mats(); a, b = G["slo"][0], G["mlo"][0]
# A1 with the original draw order
rng = np.random.default_rng(20261007); pd_ = rng.integers(14, size=(20000, 14)); sd = rng.integers(S, size=(20000, 14, S))
d = a[pd_[:, :, None], sd].mean(axis=(1, 2)) - b[pd_[:, :, None], sd].mean(axis=(1, 2))
A1 = [float(a.mean() - b.mean()), *np.percentile(d, [2.5, 97.5]).tolist()]
out["A1"] = {"computed": A1, "stored": [R["paired_slo_minus_mlo"]["mean_difference"], *R["paired_slo_minus_mlo"]["bootstrap_95"]]}
out["A1"]["exact"] = bool(np.allclose(out["A1"]["computed"], out["A1"]["stored"], atol=1e-9))
inv = []; flagged = set()
for m in modes:
    for (x, y) in common:
        c = analyze.context(idx, m, rate, x, y, GRID_SEEDS[0]); ra = 0 if c["rssi"][0] >= c["rssi"][1] else 1
        rew = np.array([[idx[(m, rate, q + 1, x, y, s)]["sumLog"] for s in GRID_SEEDS] for q in (0, 1)]); oa = int(rew[1].mean() > rew[0].mean())
        for act in (0, 1):
            for si, s in enumerate(GRID_SEEDS):
                t = tp(idx[(m, rate, act + 1, x, y, s)]); mn = min(t.values())
                if mn < 0.05:
                    flagged.add(((x, y), si))
                    inv.append({"mode": m, "pos": [x, y], "MAP": [1, 4][act], "seed": s, "low": {k: round(v, 5) for k, v in t.items() if v < 0.05}, "below_0.01": mn < 0.01, "is_rssi_action": act == ra, "is_oracle_action": act == oa, "enters_estimate": act in (ra, oa)})
out["A2"] = {"runs_checked": len(modes) * 14 * 2 * S, "flagged_below_0.05": len(inv), "below_0.01": sum(i["below_0.01"] for i in inv), "entering_estimate": sum(i["enters_estimate"] for i in inv), "list": inv}
out["A3"] = {str(f): boot(*(lambda g: (g["slo"][0], g["mlo"][0]))(mats(f)))[0] for f in (1e-2, 1e-1, 1.0)}
k4 = [[si for si in range(S) if (p, si) not in flagged] for p in common]
out["A4"] = dict(zip(("est", "positions", "pairs"), boot(a, b, k4)))
k5 = [list(range(S)) if not any((p, si) in flagged for si in range(S)) else [] for p in common]
out["A5"] = dict(zip(("est", "positions", "pairs"), boot(a, b, k5)))
out["A6"] = boot(G["slo"][1], G["mlo"][1])[0]; out["A6_gains"] = {"slo": float(G["slo"][1].mean()), "mlo": float(G["mlo"][1].mean())}
lo = [float(np.delete(a - b, i, axis=0).mean()) for i in range(14)]
out["A7"] = {"min": min(lo), "max": max(lo), "by_left_out": dict(zip(map(str, common), np.round(lo, 4).tolist()))}
out["per_position_slo_minus_mlo"] = dict(zip(map(str, common), np.round((a - b).mean(axis=1), 3).tolist()))
# B shares
def share(mode, n=4000, seed=20260930):
    D = analyze.build_dataset(idx, mode); gp = {}
    pol = analyze.HEURISTICS["AirtimeThr"]
    for (r, x, y), (c, rew, met) in D.items():
        rew = [np.array(v) for v in rew]; at, ar, ao = pol(c), analyze.HEURISTICS["RSSI"](c), analyze.oracle_action(c, [list(v) for v in rew])
        gp.setdefault((x, y), []).append((rew[at] - rew[ar], rew[ao] - rew[ar]))
    pos = list(gp); rng = np.random.default_rng(seed)
    num = np.mean([d[0].mean() for g in gp.values() for d in g]); den = np.mean([d[1].mean() for g in gp.values() for d in g]); v = []
    for _ in range(n):
        A = B = N = 0
        for j in rng.integers(len(pos), size=len(pos)):
            for t, o in gp[pos[j]]:
                k = rng.integers(len(t), size=len(t)); A += t[k].mean(); B += o[k].mean(); N += 1
        v.append(A / B if B > 0 else np.nan)
    v = np.array(v)
    return {"thr_gain": float(num), "oracle_gain": float(den), "share": float(num / den), "ci": np.nanpercentile(v, [2.5, 97.5]).tolist(), "undefined_draws": int(np.isnan(v).sum())}
out["B"] = {"AirtimeThr_share_slo": share("slo"), "AirtimeThr_share_mlo": share("mlo")}
rr = R["paired_ratio_slo_over_mlo"]; out["B"]["reduction_share_1_minus_mlo_over_slo"] = {"point": 1 - 1 / rr["point_ratio"], "ci": [1 - 1 / rr["bootstrap_95"][0], 1 - 1 / rr["bootstrap_95"][1]]}
json.dump(out, open("desk_checks_2026-11-03/claim_evidence_clearance/CLEARANCE_RESULTS.json", "w"), indent=1)
o = {k: v for k, v in out.items() if k not in ("A2",)}; print(json.dumps(o, indent=0)); print("A2", {k: v for k, v in out["A2"].items() if k != "list"})
for i in out["A2"]["list"]: print(i["mode"], i["pos"], "MAP", i["MAP"], "s", i["seed"], i["low"], "rssi" if i["is_rssi_action"] else "", "oracle" if i["is_oracle_action"] else "")
