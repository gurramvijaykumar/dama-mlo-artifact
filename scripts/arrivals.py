"""Multi-station sequential-arrival experiment for the DAMA-MLO revision.

K fast stations arrive one at a time at random positions in the contested
region between MAP 1 and MAP 4. Before each arrival, the policy observes the
network as it stands (earlier arrivals already placed by the same policy):
beacon RSSI of the newcomer, the per-link utilization each AP advertises, and
the client count of each AP. It then picks MAP 1 or MAP 4. The network after
every step is one ns-3 run (scenario 0 plus --newSta), so each step's utility
is measured, not modelled.

GreedyOracle tries both candidate MAPs at every step and keeps the better sumLog
(where only one MAP passes the per-link floor it takes that one); it is
the one-step-lookahead reference, not a global optimum.

Usage: python3 arrivals.py [--trials 15] [--k 5] [--mode mlo] [--rate EhtMcs0]
                           [--learners] [--workers 4] [--train-seed 0]
Writes results/arrivals_<mode>_<rate>.json. With --train-seed N > 0 the learners are trained
with seed N and the output goes to results/arrivals_<mode>_<rate>_trainseed<N>.json, so the
seed-0 result of the manuscript is never overwritten. Placement trials do not depend on N.
"""

import argparse
import json
import os

import numpy as np

import policies as P
from analyze import HEURISTICS, OUT, build_dataset, ci95, index, load_runs
from experiments import GRID_X, GRID_Y
from simlib import run_many

REGION_X = (min(GRID_X), max(GRID_X))
REGION_Y = (min(GRID_Y), max(GRID_Y))


def sta_arg(placed):
    """--newSta string for a list of (x, y, action)."""
    return ",".join(f"{x:.1f}:{y:.1f}:{1 if a == 0 else 4}" for x, y, a in placed)


def run_args(mode, rate, seed, placed):
    a = {"scenario": 0, "linkMode": mode, "n4Rate": rate, "rngRun": seed}
    if placed:
        a["newSta"] = sta_arg(placed)
    return a


def make_context(out, mode, x, y, placed):
    n1 = 2 + sum(1 for *_, a in placed if a == 0)
    n4 = 2 + sum(1 for *_, a in placed if a == 1)
    return {
        "rssi": (P.rssi_dbm(x, y, 0), P.rssi_dbm(x, y, 1)),
        "util": [out.get("util_MAP1_L0", 0.0), out.get("util_MAP1_L1", 0.0),
                 out.get("util_MAP4_L0", 0.0), out.get("util_MAP4_L1", 0.0)],
        "nlinks": 1 if mode == "slo" else 2,
        "nclients": (n1, n4),
        "pos": (x, y),
    }


def trained_learners(mode, rounds=4000, seed=0):
    """Learners trained on the whole single-arrival grid of this link mode."""
    idx = index(load_runs())
    data = build_dataset(idx, mode)
    if not data:
        print(f"no grid data for {mode}: learners skipped", flush=True)
        return {}
    train = [(c, rew) for c, rew, _ in data.values()]
    return {kind: P.train_learner(kind, train, rounds, seed) for kind in ("ucb1", "linucb", "neural")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=15)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--mode", default="mlo")
    ap.add_argument("--rate", default="EhtMcs0")
    ap.add_argument("--learners", action="store_true")
    ap.add_argument("--policies", default="", help="comma list to restrict policies")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--train-seed", type=int, default=0,
                    help="learner training seed (0 = manuscript result)")
    opt = ap.parse_args()

    pols = dict(HEURISTICS)
    if opt.learners:
        pols.update(trained_learners(opt.mode, seed=opt.train_seed))
    if opt.policies:
        keep = set(opt.policies.split(",")) | {"RSSI"}  # RSSI is the baseline of every gain
        pols = {n: p for n, p in pols.items() if n in keep}
    names = list(pols) + ["GreedyOracle"]

    rng = np.random.default_rng(2026)
    trials = []
    for t in range(opt.trials):
        pos = [(float(rng.uniform(*REGION_X)), float(rng.uniform(*REGION_Y))) for _ in range(opt.k)]
        trials.append({"seed": t + 1, "pos": pos})

    # state[(trial, policy)] = placed list; hist = per-step metrics after each arrival
    placed = {(t, n): [] for t in range(opt.trials) for n in names}
    hist = {key: [] for key in placed}
    label = f"arrivals-{opt.mode}-{opt.rate}"

    for step in range(opt.k + 1):
        # 1. observe the current network of every (trial, policy)
        keys = list(placed)
        cur = run_many([run_args(opt.mode, opt.rate, trials[t]["seed"], placed[(t, n)])
                        for t, n in keys], workers=opt.workers, label=f"{label} step{step}",
                       allow_fail=False)  # trajectories need every run
        for key, o in zip(keys, cur):
            if step > 0:
                hist[key].append({m: o[m] for m in ("sumLog", "sumTput", "jain", "e2eMs")}
                                 | {"tput_new": o.get(f"tput_S{step - 1}", 0.0)})
        if step == opt.k:
            break
        # 2. decide the next arrival
        oracle_try = []
        for (t, n), o in zip(keys, cur):
            x, y = trials[t]["pos"][step]
            ctx = make_context(o, opt.mode, x, y, placed[(t, n)])
            if n == "GreedyOracle":
                forced = P.forced_action(ctx)
                if forced is None:
                    oracle_try.append((t, x, y))
                else:  # only one candidate passes the per-link floor (Sec. 4.1)
                    placed[(t, n)] = placed[(t, n)] + [(x, y, forced)]
                continue
            placed[(t, n)] = placed[(t, n)] + [(x, y, int(pols[n](ctx)))]
        # 3. the greedy oracle simulates both choices and keeps the better one
        tries = []
        for t, x, y in oracle_try:
            for a in (0, 1):
                tries.append(run_args(opt.mode, opt.rate, trials[t]["seed"],
                                      placed[(t, "GreedyOracle")] + [(x, y, a)]))
        res = run_many(tries, workers=opt.workers, label=f"{label} oracle{step}", allow_fail=False)
        for i, (t, x, y) in enumerate(oracle_try):
            best = int(np.argmax([res[2 * i]["sumLog"], res[2 * i + 1]["sumLog"]]))
            placed[(t, "GreedyOracle")] = placed[(t, "GreedyOracle")] + [(x, y, best)]

    out = {"trials": opt.trials, "k": opt.k, "mode": opt.mode, "rate": opt.rate, "policies": {},
           "learnerTraining": "constrained" if opt.learners else None, "trainSeed": opt.train_seed}
    for n in names:
        per_step = []
        for s in range(opt.k):
            rows = [hist[(t, n)][s] for t in range(opt.trials)]
            base = [hist[(t, "RSSI")][s] for t in range(opt.trials)] if "RSSI" in names else rows
            per_step.append({
                "sumLog": ci95([r["sumLog"] for r in rows]),
                "sumTput": ci95([r["sumTput"] for r in rows]),
                "jain": ci95([r["jain"] for r in rows]),
                "e2eMs": ci95([r["e2eMs"] for r in rows]),
                "tput_new": ci95([r["tput_new"] for r in rows]),
                "sumLog_gain_vs_rssi": ci95([r["sumLog"] - b["sumLog"] for r, b in zip(rows, base)]),
            })
        frac_map1 = float(np.mean([a == 0 for t in range(opt.trials) for *_, a in placed[(t, n)]]))
        out["policies"][n] = {"per_step": per_step, "frac_map1": frac_map1}
    out["decisions"] = {f"{t}|{n}": placed[(t, n)] for t in range(opt.trials) for n in names}
    suffix = f"_trainseed{opt.train_seed}" if opt.train_seed else ""
    path = os.path.join(OUT, f"arrivals_{opt.mode}_{opt.rate}{suffix}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    final = {n: out["policies"][n]["per_step"][-1]["sumLog_gain_vs_rssi"] for n in names}
    print(json.dumps({"final_sumLog_gain_vs_rssi": final}, indent=1))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
