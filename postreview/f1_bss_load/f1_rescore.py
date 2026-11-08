#!/usr/bin/env python3
"""F1 measurement-realism re-scoring of the stored grid (rules: F1_SPEC.md). Fixed rules only. Desk; no simulation.
Usage: python3 f1_rescore.py  -> f1_fixed_rules.json"""
import json, os, sys
import numpy as np
REV = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2"
sys.path.insert(0, REV); os.chdir(REV)
import analyze as A, policies as P  # noqa: E402
from experiments import GRID_SEEDS, GRID_X, GRID_Y, LINK_MODES, N4_RATES  # noqa: E402
OUT = os.path.dirname(os.path.abspath(__file__))
D = 0.05
q8 = lambda u: [round(255 * v) / 255 for v in u]
stored = json.load(open(os.path.join(REV, "results/policies.json")))
idx = A.index(A.load_runs(None))
POL = {n: A.HEURISTICS[n] for n in ("RSSI", "Airtime", "AirtimeThr")}


def build(mode):
    """Like A.build_dataset, plus the seed ids and per-seed utilisation of each context."""
    data = {}
    for rate in N4_RATES:
        for x in GRID_X:
            for y in GRID_Y:
                rew, seeds, utils, base = [[], []], [], [], None
                for s in GRID_SEEDS:
                    try:
                        c = A.context(idx, mode, rate, x, y, s)
                        o1 = idx[(mode, rate, 1, x, y, s)]; o4 = idx[(mode, rate, 2, x, y, s)]
                    except KeyError:
                        continue
                    base = base or c
                    seeds.append(s); utils.append(c["util"])
                    rew[0].append(o1["sumLog"]); rew[1].append(o4["sumLog"])
                if seeds:
                    data[(rate, x, y)] = (dict(base), rew, seeds, utils)
    return data


def with_util(c, u):
    c2 = dict(c); c2["util"] = list(u); return c2


def score(data, pol, cond):
    """Per-context records with per-seed reward of the chosen MAP under condition cond."""
    recs, n_changed, n_total = [], 0, 0
    for key, (c, rew, seeds, utils) in data.items():
        mean_u = list(np.mean(utils, axis=0))
        c0 = with_util(c, mean_u)
        a0 = pol(c0); ar = A.HEURISTICS["RSSI"](c0); best = A.oracle_action(c0, rew)
        r = []
        for i in range(len(seeds)):
            if cond == "D0":
                acts = [a0]
            elif cond == "D1":
                acts = [pol(with_util(c, q8(mean_u)))]
            elif cond == "D2":
                acts = [pol(with_util(c, q8(utils[i])))]
            else:  # D3: every other seed's estimate (or a single offset k for D3k)
                others = [j for j in range(len(seeds)) if j != i] or [i]
                if cond.startswith("D3k"):
                    k = int(cond[3:]); others = [others[(k - 1) % len(others)]]
                acts = [pol(with_util(c, q8(utils[j]))) for j in others]
            n_changed += sum(a != a0 for a in acts); n_total += len(acts)
            r.append(float(np.mean([rew[a][i] for a in acts])))
        r = np.asarray(r)
        recs.append({"key": key, "reg_seeds": list(np.asarray(rew[best]) - r),
                     "d_seeds": list(r - np.asarray(rew[ar])), "r_seeds": list(r),
                     "sumLog": float(r.mean()), "sumLog_rssi": float(np.mean(rew[ar])),
                     "sumLog_oracle": float(np.mean(rew[best]))})
    return recs, n_changed, n_total


def verdict(lo, hi):
    return "SUFFICIENT" if hi < D else ("BOUNDARY" if lo > D else "INCONCLUSIVE")


res = {"spec": "F1_SPEC.md", "d": D, "modes": {}}
for mode in LINK_MODES:
    data = build(mode)
    # validity: our contexts equal analyze.build_dataset
    ref = A.build_dataset(idx, mode)
    assert set(ref) == set(data)
    for k in ref:
        assert np.allclose(ref[k][0]["util"], np.mean(data[k][3], axis=0)) and ref[k][1] == data[k][1]
    m = {}
    for name, pol in POL.items():
        for cond in ("D0", "D1", "D2", "D3", "D3k1", "D3k2", "D3k3", "D3k4"):
            recs, nch, ntot = score(data, pol, cond)
            reg = A.cluster_boot(recs, "reg_seeds"); gain = A.cluster_boot(recs, "d_seeds")
            m[f"{name}|{cond}"] = {"shortfall": reg, "gain_vs_rssi": gain, "changed": [nch, ntot],
                                   "verdict": verdict(reg[1], reg[2]),
                                   "mean_regret_plain": float(np.mean([r["sumLog_oracle"] - r["sumLog"] for r in recs]))}
            if cond == "D0" and name != "RSSI":
                st = stored[mode][name]
                m[f"{name}|{cond}"]["check_vs_stored"] = [
                    abs(float(np.mean([r["sumLog"] - r["sumLog_rssi"] for r in recs])) - st["mean_sumLog_gain_vs_rssi"][0]),
                    abs(m[f"{name}|{cond}"]["mean_regret_plain"] - st["mean_regret"][0])]
    m["Oracle_gain_vs_rssi_ideal"] = stored[mode]["Oracle"]["mean_sumLog_gain_vs_rssi"][0]
    m["n_contexts"] = len(data)
    res["modes"][mode] = m
    for key in ("AirtimeThr|D0", "AirtimeThr|D1", "AirtimeThr|D2", "AirtimeThr|D3", "Airtime|D3", "RSSI|D0"):
        v = m[key]
        print(mode, key, "S=%.4f [%.4f, %.4f]" % tuple(v["shortfall"]), v["verdict"], "chg %d/%d" % tuple(v["changed"]),
              "chk", v.get("check_vs_stored"), flush=True)
json.dump(res, open(os.path.join(OUT, "f1_fixed_rules.json"), "w"), indent=1)
