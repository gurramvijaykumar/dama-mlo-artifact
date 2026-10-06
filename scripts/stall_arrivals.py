"""Stalled final runs in the sequential-arrival experiment (revision, 2026-10-06).

One criterion for every policy, training seed and link configuration, the same as
screen_zero_delivery.py: the final run of a trial (after the k-th placement) is STALLED if any
station delivered < 0.05 Mbit/s or transmitted no data frame on any link.

Writes, under results/arrival_stall_trace/:
  candidates.json + jobs.txt  -- unique stalled final runs, in the format of results/addba_screen,
                                 so run.sh (isolated diag build, --diagTrace) and
                                 summarize_addba_screen.py <dir> can trace and classify them;
  stalls.json                 -- which (mode, seed, policy, trial) final runs stalled, and the
                                 sensitivity analysis: final-step gain over RSSI with every trial in
                                 which the policy's or RSSI's final run stalled removed.
The primary result (summarize_arrival_seeds.py) keeps every trial; this is a sensitivity check only.

Usage: python3 stall_arrivals.py [--rate EhtMcs0]
"""

import argparse
import glob
import json
import os
import re

import numpy as np

from analyze import OUT
from arrivals import run_args
from simlib import BASE, CODE_VERSION, _key, _load

TPUT_ZERO = 0.05  # Mbit/s, as screen_zero_delivery.py
MODES = ("mlo", "mloConfined")


def stalled_stations(o):
    hits = []
    for st in sorted({k[5:] for k in o if k.startswith("tput_")}):
        frames = [v for k, v in o.items() if k.startswith("frames_" + st + "_")]
        zero_tx = bool(frames) and sum(frames) == 0
        if o["tput_" + st] < TPUT_ZERO or zero_tx:
            hits.append(st + ("(0tx)" if zero_tx else ""))
    return hits


def crossed_boot(mats, rng, n=10000):
    """Crossed bootstrap as summarize_arrival_seeds.py; NaN marks a removed trial."""
    boot = []
    for _ in range(n):
        pick = rng.integers(mats.shape[0], size=mats.shape[0])
        trials = rng.integers(mats.shape[1], size=mats.shape[1])
        boot.append(np.nanmean(mats[np.ix_(pick, trials)]))
    return [float(x) for x in np.nanpercentile(boot, [2.5, 97.5])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", default="EhtMcs0")
    rate = ap.parse_args().rate
    cache = _load()
    out_dir = os.path.join(OUT, "arrival_stall_trace")
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(20261006)
    cands, seen, report = [], {}, {}
    for mode in MODES:
        files = {0: os.path.join(OUT, f"arrivals_{mode}_{rate}.json")}
        for f in glob.glob(os.path.join(OUT, f"arrivals_{mode}_{rate}_trainseed*.json")):
            files[int(re.search(r"trainseed(\d+)", f).group(1))] = f
        stalls, gains, kept = [], {}, {}
        for s in sorted(files):
            res = json.load(open(files[s]))
            dec = res["decisions"]
            pols = [p for p in res["policies"] if f"0|{p}" in dec]
            final = {}
            for p in pols:
                for t in range(res["trials"]):
                    args = run_args(mode, rate, t + 1, [tuple(x) for x in dec[f"{t}|{p}"]])
                    full = dict(BASE)
                    full.update(args)
                    o = cache[_key(full, CODE_VERSION)]
                    final[(p, t)] = o
                    hits = stalled_stations(o)
                    if not hits:
                        continue
                    argstr = " ".join(f"--{k}={v}" for k, v in sorted(full.items()))
                    if argstr not in seen:
                        seen[argstr] = f"a{len(cands):04d}"
                        cands.append({"name": seen[argstr], "version": str(CODE_VERSION), "args": full,
                                      "hits": hits, "out": o})
                    stalls.append({"seed": s, "policy": p, "trial": t, "stations": hits,
                                   "run": seen[argstr]})
            for p in pols:
                if p == "RSSI":
                    continue
                g, m = [], []
                for t in range(res["trials"]):
                    g.append(final[(p, t)]["sumLog"] - final[("RSSI", t)]["sumLog"])
                    m.append(not stalled_stations(final[(p, t)]) and not stalled_stations(final[("RSSI", t)]))
                gains.setdefault(p, {})[s] = g
                kept.setdefault(p, {})[s] = m
        sens = {}
        for p in gains:
            seeds = sorted(gains[p])
            full_m = np.array([gains[p][s] for s in seeds])
            excl_m = np.where(np.array([kept[p][s] for s in seeds]), full_m, np.nan)
            sens[p] = {
                "seeds": seeds,
                "trials_removed_per_seed": {str(s): int(np.sum(~np.array(kept[p][s]))) for s in seeds},
                "all_trials": {"pooled_mean": float(full_m.mean(axis=1).mean()),
                               "per_seed_mean": {str(s): float(np.mean(gains[p][s])) for s in seeds}},
                "excl_stalled": {"pooled_mean": float(np.nanmean(excl_m, axis=1).mean()),
                                 "per_seed_mean": {str(s): float(np.nanmean(excl_m[i]))
                                                   for i, s in enumerate(seeds)},
                                 "crossed_boot_95": crossed_boot(excl_m, rng)},
            }
            r = sens[p]
            print(f"{mode:12s} {p:12s} seeds {seeds} removed {r['trials_removed_per_seed']}  "
                  f"all {r['all_trials']['pooled_mean']:+.3f}  excl {r['excl_stalled']['pooled_mean']:+.3f} "
                  f"[{r['excl_stalled']['crossed_boot_95'][0]:+.3f}, {r['excl_stalled']['crossed_boot_95'][1]:+.3f}]")
        report[mode] = {"stalled_final_runs": stalls, "sensitivity_excl_stalled": sens}
    with open(os.path.join(out_dir, "jobs.txt"), "w") as f:
        for c in cands:
            f.write(c["name"] + " " + " ".join(f"--{k}={v}" for k, v in sorted(c["args"].items())) + "\n")
    with open(os.path.join(out_dir, "candidates.json"), "w") as f:
        json.dump(cands, f)
    with open(os.path.join(out_dir, "stalls.json"), "w") as f:
        json.dump({"criterion": f"any station < {TPUT_ZERO} Mbit/s or no data frame transmitted, "
                                "final run of the trial", **report}, f, indent=1)
    print(f"unique stalled final runs: {len(cands)} -> {out_dir}")


if __name__ == "__main__":
    main()
