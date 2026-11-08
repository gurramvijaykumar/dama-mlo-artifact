#!/usr/bin/env python3
"""F1 H-LRN step (F1_SPEC.md): learners trained exactly as R1 (ideal contexts, leave-one-position-out, 4000 rounds,
5 replicates, constrained, seeds 1000*rep + hash(pos) % 997), executed on D0 (check) and D3 (primary) test inputs.
Usage: python3 f1_learners.py <mode>  -> f1_learners_<mode>.json"""
import json, os, sys
import numpy as np
REV = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2"
HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, "f1_rescore.py")).read().split("res = {")[0])
mode = sys.argv[1]
data = build(mode)
ideal = A.build_dataset(idx, mode)
positions = sorted({(k[1], k[2]) for k in ideal})
thr = POL["AirtimeThr"]


def per_seed_rewards(pol, cond):
    """{key: per-seed reward array} for a policy under D0 or D3."""
    out = {}
    for key, (c, rew, seeds, utils) in data.items():
        mu = list(np.mean(utils, axis=0)); r = []
        for i in range(len(seeds)):
            if cond == "D0":
                acts = [pol(with_util(c, mu))]
            else:
                others = [j for j in range(len(seeds)) if j != i] or [i]
                acts = [pol(with_util(c, q8(utils[j]))) for j in others]
            r.append(np.mean([rew[a][i] for a in acts]))
        out[key] = np.asarray(r)
    return out


def boot_diff(ra, rb):
    return A.cluster_boot([{"key": k, "d": list(ra[k] - rb[k])} for k in ra], "d")


oracle = {k: np.asarray(rew[A.oracle_action(c, rew)]) for k, (c, rew, _) in ideal.items()}
rssi = {k: np.asarray(rew[A.HEURISTICS["RSSI"](c)]) for k, (c, rew, _) in ideal.items()}
thr_r = {cond: per_seed_rewards(thr, cond) for cond in ("D0", "D3")}
stored = json.load(open(os.path.join(REV, "results/policies.json")))[mode]
res = {"mode": mode, "learners": {}}
for kind in A.LEARNERS:
    reps = {"D0": [], "D3": []}
    for rep in range(5):
        pols = {}
        for pos in positions:
            train = [(c, rew) for k, (c, rew, _) in ideal.items() if (k[1], k[2]) != pos]
            pols[pos] = P.train_learner(kind, train, 4000, seed=1000 * rep + hash(pos) % 997,
                                        constrained=A.TRAINING["constrained"])
        chooser = lambda c: pols[tuple(c["pos"])](c)
        for cond in reps:
            reps[cond].append(per_seed_rewards(chooser, cond))
    out = {}
    for cond, rr in reps.items():
        avg = {k: np.mean([r[k] for r in rr], axis=0) for k in rr[0]}
        rep_gain = [float(np.mean([np.mean(r[k] - rssi[k]) for k in r])) for r in rr]
        out[cond] = {"gain_vs_rssi": float(np.mean(rep_gain)), "rep_gains": rep_gain,
                     "train_sd": float(np.std(rep_gain, ddof=1)),
                     "shortfall": A.cluster_boot([{"key": k, "d": list(oracle[k] - avg[k])} for k in avg], "d"),
                     "vs_AirtimeThr": boot_diff(avg, thr_r[cond])}
    out["check_D0_gain_vs_stored"] = abs(out["D0"]["gain_vs_rssi"] - stored[kind]["mean_sumLog_gain_vs_rssi"][0])
    out["check_D0_vsThr_vs_stored"] = list(np.abs(np.array(out["D0"]["vs_AirtimeThr"]) - np.array(stored[kind]["vs_AirtimeThr_boot"])))
    res["learners"][kind] = out
    print(mode, kind, "D0 chk %.2e" % out["check_D0_gain_vs_stored"], "D3 vsThr", np.round(out["D3"]["vs_AirtimeThr"], 4),
          "D3 shortfall", np.round(out["D3"]["shortfall"], 4), flush=True)
    json.dump(res, open(os.path.join(HERE, f"f1_learners_{mode}.json"), "w"), indent=1, default=float)
