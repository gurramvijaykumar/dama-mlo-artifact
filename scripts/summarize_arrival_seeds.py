"""Training-seed variation of the sequential-arrival learners (revision, reviewer item 5).

arrivals.py --learners trains each learner once (seed 0, the manuscript result). Runs with
--train-seed N write results/arrivals_<mode>_<rate>_trainseed<N>.json. This script reads
every available seed, recovers the per-trial final utility of each placement from the run
cache, and reports the final-step sum-log gain over RSSI per learner:
  - per training seed (mean over the placement trials);
  - pooled over seeds, with the between-seed standard deviation and a crossed bootstrap
    interval (resample seeds and shared placement trials independently).

--estimate SEEDS (e.g. 1,2,3,4) instead counts, without simulating, how many ns-3 runs
arrivals.py would need for those seeds: decisions are replayed through the cache and a
trajectory is counted as uncached from its first missing step to the end (upper bound
for that trajectory, since later steps depend on the missing run).

Usage: python3 summarize_arrival_seeds.py [--mode mlo] [--rate EhtMcs0]
       python3 summarize_arrival_seeds.py --mode mlo --estimate 1,2,3,4
Read-only on results/ (except writing results/arrival_seeds_<mode>_<rate>.json).
"""

import argparse
import glob
import json
import os
import re

import numpy as np

import policies as P
from analyze import OUT
from arrivals import make_context, run_args, trained_learners
from simlib import BASE, CODE_VERSION, _key, _load

LEARNERS = ("ucb1", "linucb", "neural")


def cached(cache, args):
    full = dict(BASE)
    full.update(args)
    return cache.get(_key(full, CODE_VERSION))


def final_sumlog(cache, mode, rate, seed, placed):
    o = cached(cache, run_args(mode, rate, seed, placed))
    if o is None:
        raise KeyError(f"final run not in cache: trial seed {seed}, {placed}")
    return o["sumLog"]


def per_trial_gains(cache, res):
    """Final-step gain over RSSI per trial, for every learner in one arrivals result."""
    mode, rate, trials = res["mode"], res["rate"], res["trials"]
    dec = res["decisions"]
    out = {}
    for n in LEARNERS:
        if f"0|{n}" not in dec:
            continue
        g = []
        for t in range(trials):
            base = final_sumlog(cache, mode, rate, t + 1, [tuple(p) for p in dec[f"{t}|RSSI"]])
            mine = final_sumlog(cache, mode, rate, t + 1, [tuple(p) for p in dec[f"{t}|{n}"]])
            g.append(mine - base)
        out[n] = g
    return out


def summarize(mode, rate):
    cache = _load()
    files = {0: os.path.join(OUT, f"arrivals_{mode}_{rate}.json")}
    for f in glob.glob(os.path.join(OUT, f"arrivals_{mode}_{rate}_trainseed*.json")):
        files[int(re.search(r"trainseed(\d+)", f).group(1))] = f
    gains = {}
    reference_trials = None
    for s in sorted(files):
        with open(files[s]) as f:
            res = json.load(f)
        if res.get("trainSeed", 0) != s:
            raise ValueError(f"training seed does not match filename: {files[s]}")
        trial_signature = (res["trials"], res["k"],
                           [res["decisions"][f"{t}|RSSI"] for t in range(res["trials"])])
        if reference_trials is None:
            reference_trials = trial_signature
        elif trial_signature != reference_trials:
            raise ValueError("training seeds must share the same placement trials and RSSI baseline")
        gains[s] = per_trial_gains(cache, res)
    rng = np.random.default_rng(20261006)
    report = {"mode": mode, "rate": rate, "seeds": sorted(gains), "learners": {}}
    print(f"{mode} {rate}: training seeds {sorted(gains)}")
    for n in LEARNERS:
        by_seed = {s: np.asarray(g[n]) for s, g in gains.items() if n in g}
        if not by_seed:
            continue
        means = np.array([v.mean() for v in by_seed.values()])
        mats = np.stack(list(by_seed.values()))
        boot = []
        for _ in range(10000):
            pick = rng.integers(mats.shape[0], size=mats.shape[0])
            # A placement is shared across training seeds. Resample its column
            # once, preserving that dependence for every selected seed.
            trials = rng.integers(mats.shape[1], size=mats.shape[1])
            boot.append(mats[np.ix_(pick, trials)].mean())
        lo, hi = np.percentile(boot, [2.5, 97.5])
        report["learners"][n] = {
            "per_seed_mean": {str(s): float(v.mean()) for s, v in by_seed.items()},
            "pooled_mean": float(means.mean()),
            "between_seed_sd": float(means.std(ddof=1)) if len(means) > 1 else 0.0,
            "crossed_boot_95": [float(lo), float(hi)],
        }
        seeds_txt = "  ".join(f"s{s}={v.mean():+.3f}" for s, v in by_seed.items())
        print(f"  {n:7s} {seeds_txt}  pooled {means.mean():+.3f} "
              f"(between-seed sd {report['learners'][n]['between_seed_sd']:.3f}) [{lo:+.3f}, {hi:+.3f}]")
    path = os.path.join(OUT, f"arrival_seeds_{mode}_{rate}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"wrote {path}")


def estimate(mode, rate, seeds):
    cache = _load()
    ref = json.load(open(os.path.join(OUT, f"arrivals_{mode}_{rate}.json")))
    trials, k = ref["trials"], ref["k"]
    pos = {t: [tuple(p[:2]) for p in ref["decisions"][f"{t}|RSSI"]] for t in range(trials)}
    total = 0
    for s in seeds:
        pols = trained_learners(mode, seed=s)
        need = 0
        for n in LEARNERS:
            for t in range(trials):
                placed = []
                for step in range(k):
                    o = cached(cache, run_args(mode, rate, t + 1, placed))
                    if o is None:  # this run and every later step must be simulated
                        need += k - step + 1
                        break
                    x, y = pos[t][step]
                    placed = placed + [(x, y, int(pols[n](make_context(o, mode, x, y, placed))))]
                else:
                    need += cached(cache, run_args(mode, rate, t + 1, placed)) is None
        print(f"{mode} train seed {s}: at most {need} of {len(LEARNERS) * trials * k} runs to simulate",
              flush=True)
        total += need
    print(f"{mode} total: at most {total} runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="mlo")
    ap.add_argument("--rate", default="EhtMcs0")
    ap.add_argument("--estimate", default="", help="comma list of training seeds to cost")
    opt = ap.parse_args()
    if opt.estimate:
        estimate(opt.mode, opt.rate, [int(s) for s in opt.estimate.split(",")])
    else:
        summarize(opt.mode, opt.rate)


if __name__ == "__main__":
    main()
