"""Analysis of the DAMA-MLO revision sweeps.

Reads results/runs.jsonl (written by simlib) and produces results/*.json
used for the revised manuscript's tables and figures.

  python3 analyze.py ablation   SLO vs MLO vs MLO-confined under fixed association
  python3 analyze.py policies   leave-one-position-out policy comparison
  python3 analyze.py states     the five named states (continuity with Table III)
"""

import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
from scipy import stats

import policies as P
from experiments import GRID_SEEDS, GRID_X, GRID_Y, LINK_MODES, N4_RATES, STATE_SEEDS, STATES
from simlib import BASE, FAILED_FILE, HERE, LEGACY_VERSION, RUNS_FILE, record_version

OUT = os.path.join(HERE, "results")
SWEPT = ("linkMode", "n4Rate")
GRID_KEYS = ("scenario", "n5X", "n5Y", "rngRun")


def load_runs(filters=None, version=LEGACY_VERSION, failed=False):
    """Return list of (args, out) for runs of one code version whose args match BASE+filters.

    With failed=True, read results/failed_runs.jsonl instead (runs that exited
    non-zero and are excluded from every result); out is then None.
    """
    filters = filters or {}
    # linkMode and n4Rate are swept and kept apart by index(); BASE only pins them
    # for single runs, so they are filtered on only when a caller asks for it.
    want = {k: v for k, v in BASE.items() if k not in SWEPT}
    want.update(filters)
    res = []
    path = FAILED_FILE if failed else RUNS_FILE
    if not os.path.exists(path):
        return res
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if record_version(rec) != version:
                continue
            a = rec["args"]
            # args outside BASE (e.g. arrivals.py's newSta) change the network, so
            # such runs are kept only when the caller filters on that arg
            if any(k not in BASE and k not in GRID_KEYS and k not in filters for k in a):
                continue
            ok = all(str(a.get(k)) == str(v) for k, v in want.items() if k in a or k in BASE)
            if ok:
                res.append((a, None if failed else rec["out"]))
    return res


def index(runs):
    """Map (linkMode, n4Rate, scenario, n5X, n5Y, rngRun) -> out."""
    idx = {}
    for a, o in runs:
        sc = int(a["scenario"])
        key = (a["linkMode"], a["n4Rate"], sc,
               float(a["n5X"]) if sc else None, float(a["n5Y"]) if sc else None,
               int(a["rngRun"]))
        idx[key] = o
    return idx


def ci95(x):
    x = np.asarray(x, float)
    if len(x) < 2:
        return float(x.mean()), 0.0
    return float(x.mean()), float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / math.sqrt(len(x)))


def context(idx, mode, rate, x, y, seed):
    pre = idx[(mode, rate, 0, None, None, seed)]
    util = [pre.get("util_MAP1_L0", 0.0), pre.get("util_MAP1_L1", 0.0),
            pre.get("util_MAP4_L0", 0.0), pre.get("util_MAP4_L1", 0.0)]
    return {
        "rssi": (P.rssi_dbm(x, y, 0), P.rssi_dbm(x, y, 1)),
        "util": util,
        "nlinks": 1 if mode == "slo" else 2,
        "nclients": (2, 2),
        "pos": (x, y),
        "rate": rate,
    }


# ------------------------------------------------------------------ ablation
def ablation(filters=None, tag=""):
    runs = load_runs(filters)
    idx = index(runs)
    out = {}
    for mode in LINK_MODES:
        for rate in N4_RATES:
            for sc in (1, 2):
                vals = defaultdict(list)
                for x in GRID_X:
                    for y in GRID_Y:
                        for s in GRID_SEEDS:
                            o = idx.get((mode, rate, sc, x, y, s))
                            if o is None:
                                continue
                            vals["sumTput"].append(o["sumTput"])
                            vals["sumLog"].append(o["sumLog"])
                            vals["tput_N5"].append(o["tput_N5"])
                            vals["tput_N3"].append(o["tput_N3"])
                            vals["tput_N4"].append(o["tput_N4"])
                            vals["e2eMs"].append(o["e2eMs"])
                            vals["probeMs"].append(o["probeMs"])
                            vals["jain"].append(o["jain"])
                out[f"{mode}|{rate}|MAP{1 if sc == 1 else 4}"] = {
                    k: ci95(v) + (len(v),) for k, v in vals.items()}
            pre = [idx[(mode, rate, 0, None, None, s)] for s in GRID_SEEDS
                   if (mode, rate, 0, None, None, s) in idx]
            out[f"{mode}|{rate}|pre"] = {
                k: ci95([p.get(k, 0.0) for p in pre]) + (len(pre),)
                for k in ("util_MAP1_L0", "util_MAP1_L1", "util_MAP4_L0", "util_MAP4_L1",
                          "sumTput", "tput_N3", "tput_N4", "txair_N4_L0", "txair_N4_L1",
                          "txair_N3_L0", "txair_N3_L1")}
    with open(os.path.join(OUT, f"ablation{tag}.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


# ------------------------------------------------------------------ policies
HEURISTICS = {n: P.with_floor(p) for n, p in {
    "RSSI": P.pol_rssi,
    "LoadAware": P.pol_load,
    "Airtime": P.pol_airtime,
    "AirtimeThr": P.make_threshold(0.2),
}.items()}
LEARNERS = ["ucb1", "linucb", "neural"]


def oracle_action(ctx, rew):
    """Empirical hindsight oracle over the candidate set: larger mean reward over the seeds."""
    return max(P.feasible_actions(ctx), key=lambda a: np.mean(rew[a]))


def build_dataset(idx, mode):
    """contexts[(rate, x, y)] -> (ctx, rewards[a] list over seeds, metrics[a] list)."""
    data = {}
    for rate in N4_RATES:
        for x in GRID_X:
            for y in GRID_Y:
                rew = [[], []]
                met = [[], []]
                ctxs = []
                for s in GRID_SEEDS:
                    try:
                        c = context(idx, mode, rate, x, y, s)
                        o1 = idx[(mode, rate, 1, x, y, s)]
                        o4 = idx[(mode, rate, 2, x, y, s)]
                    except KeyError:
                        continue
                    ctxs.append(c)
                    for a, o in enumerate((o1, o4)):
                        rew[a].append(o["sumLog"])
                        met[a].append(o)
                if ctxs:
                    # mean pre-association utilization over seeds = the advertised BSS Load
                    c = dict(ctxs[0])
                    c["util"] = list(np.mean([cc["util"] for cc in ctxs], axis=0))
                    data[(rate, x, y)] = (c, rew, met)
    return data


def evaluate_policy_choices(data, choose):
    """choose(key, ctx) -> action. Returns per-context records."""
    recs = []
    for key, (c, rew, met) in data.items():
        a = choose(key, c)
        ar = HEURISTICS["RSSI"](c)  # the RSSI baseline, restricted to the candidate set
        best = oracle_action(c, rew)
        recs.append({
            "key": key, "a": a, "a_rssi": ar, "a_oracle": best,
            # per-seed paired differences (same seed index for both actions), for the
            # position-cluster bootstrap
            "d_seeds": [float(x) for x in np.asarray(rew[a]) - np.asarray(rew[ar])],
            "reg_seeds": [float(x) for x in np.asarray(rew[best]) - np.asarray(rew[a])],
            "sumLog": float(np.mean(rew[a])), "sumLog_rssi": float(np.mean(rew[ar])),
            "sumLog_oracle": float(np.mean(rew[best])),
            "sumTput": float(np.mean([o["sumTput"] for o in met[a]])),
            "sumTput_rssi": float(np.mean([o["sumTput"] for o in met[ar]])),
            "jain": float(np.mean([o["jain"] for o in met[a]])),
            "tputN5": float(np.mean([o["tput_N5"] for o in met[a]])),
            "e2e": float(np.mean([o["e2eMs"] for o in met[a]])),
        })
    return recs


BOOT_N = 4000
BOOT_SEED = 20260930


def average_reps(rep_recs):
    """Per-context records with per-seed differences averaged over training replicates."""
    out = []
    for i, r in enumerate(rep_recs[0]):
        out.append({"key": r["key"],
                    "d_seeds": list(np.mean([rr[i]["d_seeds"] for rr in rep_recs], axis=0)),
                    "reg_seeds": list(np.mean([rr[i]["reg_seeds"] for rr in rep_recs], axis=0))})
    return out


def cluster_boot(recs, field="d_seeds", n_boot=BOOT_N, seed=BOOT_SEED):
    """Paired two-stage cluster bootstrap of the mean over contexts of a per-seed quantity.

    Estimand: the mean over the grid positions of this region (each position with all
    its N4 rates) of the per-context mean over seeds. Stage 1 resamples positions with
    replacement, keeping the contexts of a position together; stage 2 resamples the
    seeds within each chosen context. The two actions of a context share the seed
    index, so the differences stay paired. Returns [mean, lo95, hi95].
    """
    groups = defaultdict(list)
    for r in recs:
        groups[(r["key"][1], r["key"][2])].append(np.asarray(r[field], float))
    pos = list(groups)
    point = float(np.mean([v.mean() for g in groups.values() for v in g]))
    rng = np.random.default_rng(seed)
    n_pos = len(pos)
    # stage 1: positions drawn with replacement, one per slot -> (n_boot, n_pos)
    draw = rng.integers(n_pos, size=(n_boot, n_pos))
    # stage 2: for every position and every (replicate, slot), an independent resample of
    # the seeds of each of its contexts, so a position drawn twice gets two independent
    # seed resamples -> slot_sum[p, b, s] = sum over the contexts of p of their means
    slot_sum = np.zeros((n_pos, n_boot, n_pos))
    for j, p in enumerate(pos):
        for v in groups[p]:
            slot_sum[j] += v[rng.integers(len(v), size=(n_boot, n_pos, len(v)))].mean(axis=2)
    pos_n = np.array([len(groups[p]) for p in pos], float)
    b_idx = np.arange(n_boot)[:, None]
    s_idx = np.arange(n_pos)[None, :]
    stats_ = slot_sum[draw, b_idx, s_idx].sum(axis=1) / pos_n[draw].sum(axis=1)
    lo, hi = np.percentile(stats_, [2.5, 97.5])
    return [point, float(lo), float(hi)]


def paired_diff_boot(recs_a, recs_b):
    """Bootstrap of policy A minus policy B (same contexts, same seeds): [mean, lo, hi]."""
    b = {r["key"]: r for r in recs_b}
    diff = [{"key": r["key"], "d": [x - y for x, y in zip(r["d_seeds"], b[r["key"]]["d_seeds"])]}
            for r in recs_a]
    return cluster_boot(diff, "d")


def summarize(recs):
    n = len(recs)
    d_log = np.array([r["sumLog"] - r["sumLog_rssi"] for r in recs])
    regret = np.array([r["sumLog_oracle"] - r["sumLog"] for r in recs])
    tput = np.array([r["sumTput"] for r in recs])
    tput_r = np.array([r["sumTput_rssi"] for r in recs])
    return {
        "n_contexts": n,
        "oracle_agree": float(np.mean([r["a"] == r["a_oracle"] for r in recs])),
        "rssi_agree": float(np.mean([r["a"] == r["a_rssi"] for r in recs])),
        "mean_sumLog_gain_vs_rssi": ci95(d_log),
        "mean_regret": ci95(regret),
        "gain_boot": cluster_boot(recs, "d_seeds"),
        "regret_boot": cluster_boot(recs, "reg_seeds"),
        # geometric-mean per-station throughput ratio vs RSSI = exp(delta sumLog / nSta)
        "sumTput": ci95(tput),
        "sumTput_gain_pct_vs_rssi": float(100 * (tput.sum() / tput_r.sum() - 1)),
        "jain": ci95([r["jain"] for r in recs]),
        "e2eMs": ci95([r["e2e"] for r in recs]),
    }


TRAINING = {"constrained": True, "unconstrained": False}  # learner training variants


def policies(filters=None, tag="", rounds=4000, reps=5, learners=LEARNERS, min_positions=1,
             training="constrained"):
    """Leave-one-position-out comparison. training: "constrained" (main result, training
    actions restricted to the candidate set) or "unconstrained" (sensitivity analysis);
    budgets, folds, seeds and the test-time candidate restriction are identical."""
    runs = load_runs(filters)
    idx = index(runs)
    out = {}
    for mode in LINK_MODES:
        data = build_dataset(idx, mode)
        # leave-one-position-out needs other positions to train on
        if len({(k[1], k[2]) for k in data}) < max(2, min_positions):
            continue
        res = {}
        for name, pol in HEURISTICS.items():
            recs = evaluate_policy_choices(data, lambda k, c, p=pol: p(c))
            res[name] = summarize(recs)
            if name == "AirtimeThr":
                thr_recs = recs
        res["Oracle"] = summarize(evaluate_policy_choices(
            data, lambda k, c: oracle_action(c, data[k][1])))
        positions = sorted({(k[1], k[2]) for k in data})
        for kind in learners:
            rep_sums = []
            rep_recs = []
            for rep in range(reps):
                choices = {}
                for pos in positions:  # leave one position out
                    train = [(c, rew) for k, (c, rew, _) in data.items() if (k[1], k[2]) != pos]
                    pol = P.train_learner(kind, train, rounds, seed=1000 * rep + hash(pos) % 997,
                                          constrained=TRAINING[training])
                    for k, (c, _, _) in data.items():
                        if (k[1], k[2]) == pos:
                            choices[k] = pol(c)
                rep_recs.append(evaluate_policy_choices(data, lambda k, c: choices[k]))
                rep_sums.append(summarize(rep_recs[-1]))
            # average the replicate summaries (learner randomness)
            res[kind] = {
                "reps": reps,
                "training": training,
                "oracle_agree": float(np.mean([r["oracle_agree"] for r in rep_sums])),
                "rssi_agree": float(np.mean([r["rssi_agree"] for r in rep_sums])),
                "mean_sumLog_gain_vs_rssi": ci95([r["mean_sumLog_gain_vs_rssi"][0] for r in rep_sums]),
                "mean_regret": ci95([r["mean_regret"][0] for r in rep_sums]),
                "sumTput_gain_pct_vs_rssi": float(np.mean([r["sumTput_gain_pct_vs_rssi"] for r in rep_sums])),
                "jain": ci95([r["jain"][0] for r in rep_sums]),
                "e2eMs": ci95([r["e2eMs"][0] for r in rep_sums]),
                "sumTput": ci95([r["sumTput"][0] for r in rep_sums]),
                # position/seed uncertainty of the replicate-averaged policy, and the
                # training variability (SD of the mean gain over replicates), kept apart
                "gain_boot": cluster_boot(avg_recs := average_reps(rep_recs), "d_seeds"),
                "regret_boot": cluster_boot(avg_recs, "reg_seeds"),
                "train_sd": float(np.std([r["mean_sumLog_gain_vs_rssi"][0] for r in rep_sums], ddof=1))
                if reps > 1 else None,
                "vs_AirtimeThr_boot": paired_diff_boot(avg_recs, thr_recs),
            }
        out[mode] = res
    with open(os.path.join(OUT, f"policies{tag}.json"), "w") as f:
        json.dump({**out, "_meta": {"training": training, "rounds": rounds, "reps": reps}}, f, indent=1)
    return out


# -------------------------------------------------------------------- states
def states(filters=None, tag="", modes=LINK_MODES, version=LEGACY_VERSION):
    runs = load_runs(filters, version)
    idx = index(runs)
    out = {}
    for mode in modes:
        for st in STATES:
            x, y, rate = st["n5X"], st["n5Y"], st["n4Rate"]
            rec = {}
            per_a = {}
            seeds_a = {}
            for a, sc in ((0, 1), (1, 2)):
                seeds_a[a] = [s for s in STATE_SEEDS if (mode, rate, sc, x, y, s) in idx]
                os_ = [idx[(mode, rate, sc, x, y, s)] for s in seeds_a[a]]
                per_a[a] = os_
                keys = ["sumTput", "sumLog", "tput_N5", "tput_N3", "tput_N4", "jain", "e2eMs", "probeMs"]
                # code 2.1: matched per-packet delay split (same delivered packets)
                keys += [k for k in ("dAccMs", "dWbhMs", "dWiredMs", "dE2eMs")
                         if os_ and all(k in o for o in os_)]
                rec[f"MAP{1 if a == 0 else 4}"] = {k: ci95([o[k] for o in os_]) for k in keys}
                rec[f"MAP{1 if a == 0 else 4}"]["n"] = len(os_)
                rec[f"MAP{1 if a == 0 else 4}"]["mcs_N5"] = sorted(
                    {str(o.get("mcs_N5_L0")) + "/" + str(o.get("mcs_N5_L1", "-")) for o in os_})
            pres = [idx[(mode, rate, 0, None, None, s)] for s in STATE_SEEDS
                    if (mode, rate, 0, None, None, s) in idx]
            if pres:
                ctx = context(idx, mode, rate, x, y, STATE_SEEDS[0])
                ctx["util"] = list(np.mean([[p.get("util_MAP1_L0", 0), p.get("util_MAP1_L1", 0),
                                             p.get("util_MAP4_L0", 0), p.get("util_MAP4_L1", 0)]
                                            for p in pres], axis=0))
                rec["context"] = {"rssi": ctx["rssi"], "util": ctx["util"]}
                rec["choice"] = {n: p(ctx) for n, p in HEURISTICS.items()}
            # MAP 1 vs MAP 4 on the seeds both options have (a run excluded on one
            # side removes that seed from the comparison; nothing is imputed)
            common = [s for s in seeds_a[0] if s in seeds_a[1]]
            rec["n_common"] = len(common)
            rec["seeds_excluded"] = sorted(set(STATE_SEEDS) - set(common))
            if common:
                c1 = [idx[(mode, rate, 1, x, y, s)] for s in common]
                c4 = [idx[(mode, rate, 2, x, y, s)] for s in common]
                rec["delta_sumLog_MAP1_minus_MAP4"] = float(np.mean([o["sumLog"] for o in c1])
                                                            - np.mean([o["sumLog"] for o in c4]))
                rec["delta_sumTput_MAP1_minus_MAP4"] = float(np.mean([o["sumTput"] for o in c1])
                                                             - np.mean([o["sumTput"] for o in c4]))
            if len(common) >= 2:
                t = stats.ttest_ind([o["sumLog"] for o in c1], [o["sumLog"] for o in c4], equal_var=False)
                rec["welch_p_sumLog_MAP1_vs_MAP4"] = float(t.pvalue)
                t = stats.ttest_ind([o["sumTput"] for o in c1], [o["sumTput"] for o in c4], equal_var=False)
                rec["welch_p_sumTput_MAP1_vs_MAP4"] = float(t.pvalue)
            out[f"{mode}|state{st['id']}"] = rec
    with open(os.path.join(OUT, f"states{tag}.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    for name in sys.argv[1:]:
        r = {"ablation": ablation, "policies": policies, "states": states}[name]()
        print(json.dumps(r, indent=1)[:6000])
