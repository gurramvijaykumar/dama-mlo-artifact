"""Diagnostics for the manuscript text of Sec. 7.2 (pass 20). Read-only on results/.

For every link configuration of the version-2.0 grid:
  - per-position breakdown of the mean sum-log gain over RSSI, for the heuristics and the
    constrained learners (same training seeds as analyze.policies, so the means must equal
    results/policies.json; asserted);
  - the share of the mean gain that comes from the edge position (100, 195) m, and the
    mean gain over the other positions;
  - utility-floor sensitivity: every policy's choices are kept fixed (learners are NOT
    retrained) and rescored with the station-throughput floor at 1e-3 (the paper's
    floor), 1e-2, 1e-1 and 1 Mbit/s;
  - the number of grid runs in which some station delivers less than 0.01 Mbit/s.
Also the grid details quoted in Sec. 7.1 (SLO, N4 at MCS 0).

Writes results/diag_policy_breakdown.json. Does not touch policies.json or the tables.
"""

import json
import math
import os
from collections import defaultdict

import numpy as np

import analyze as A
import policies as P
from experiments import GRID_SEEDS, GRID_X, GRID_Y, LINK_MODES, N4_RATES

EDGE = (100.0, 195.0)
FLOORS = (1e-3, 1e-2, 1e-1, 1.0)
STARVE = 0.01


def utility(o, floor):
    return sum(math.log(max(o[f"tput_N{k}"], floor)) for k in range(1, 6))


def main():
    runs = A.load_runs()
    idx = A.index(runs)
    ref = json.load(open(os.path.join(A.OUT, "policies.json")))
    out = {}
    for mode in LINK_MODES:
        data = A.build_dataset(idx, mode)
        positions = sorted({(k[1], k[2]) for k in data})
        # the stored sumLog must be the 1e-3 floor utility
        for k, (c, rew, met) in data.items():
            for a in (0, 1):
                for r, o in zip(rew[a], met[a]):
                    assert abs(r - utility(o, 1e-3)) < 1e-4, (mode, k, a, r, utility(o, 1e-3))
        choices = {}
        for name, pol in A.HEURISTICS.items():
            choices[name] = {k: pol(c) for k, (c, _, _) in data.items()}
        choices["Oracle"] = {k: A.oracle_action(c, data[k][1]) for k, (c, _, _) in data.items()}
        for kind in A.LEARNERS:
            reps = []
            for rep in range(5):
                ch = {}
                for pos in positions:
                    train = [(c, rew) for k, (c, rew, _) in data.items() if (k[1], k[2]) != pos]
                    pol = P.train_learner(kind, train, 4000, seed=1000 * rep + hash(pos) % 997,
                                          constrained=True)
                    for k, (c, _, _) in data.items():
                        if (k[1], k[2]) == pos:
                            ch[k] = pol(c)
                reps.append(ch)
            choices[kind] = reps
        res = {}
        for name, ch in choices.items():
            reps = ch if isinstance(ch, list) else [ch]
            per_floor = {}
            for floor in FLOORS:
                rep_gain = []
                rep_pos = []
                for chr_ in reps:
                    g = {}
                    for k, (c, rew, met) in data.items():
                        ar = A.HEURISTICS["RSSI"](c)
                        a = chr_[k]
                        g[k] = np.mean([utility(o, floor) for o in met[a]]) - \
                            np.mean([utility(o, floor) for o in met[ar]])
                    rep_gain.append(float(np.mean(list(g.values()))))
                    pos_g = defaultdict(list)
                    for k, v in g.items():
                        pos_g[(k[1], k[2])].append(v)
                    rep_pos.append({p: float(np.sum(v)) / len(data) for p, v in pos_g.items()})
                mean_gain = float(np.mean(rep_gain))
                contrib = {f"{p[0]:g},{p[1]:g}": float(np.mean([rp[p] for rp in rep_pos]))
                           for p in positions}
                edge = contrib.get(f"{EDGE[0]:g},{EDGE[1]:g}", 0.0)
                # mean gain over the contexts of the other positions
                n_edge = sum(1 for k in data if (k[1], k[2]) == EDGE)
                others = (mean_gain - edge) * len(data) / (len(data) - n_edge)
                per_floor[str(floor)] = {"mean_gain": mean_gain, "edge_contrib": edge,
                                         "mean_gain_other_positions": others,
                                         "contrib_by_position": contrib}
            ref_gain = ref[mode][name]["mean_sumLog_gain_vs_rssi"][0]
            assert abs(per_floor["0.001"]["mean_gain"] - ref_gain) < 1e-6, (mode, name, ref_gain,
                                                                           per_floor["0.001"])
            res[name] = per_floor
        starved = 0
        total = 0
        for rate in N4_RATES:
            for x in GRID_X:
                for y in GRID_Y:
                    for s in GRID_SEEDS:
                        for sc in (1, 2):
                            o = idx.get((mode, rate, sc, x, y, s))
                            if o is None:
                                continue
                            total += 1
                            starved += any(o[f"tput_N{k}"] < STARVE for k in range(1, 6))
        res["_starved_runs"] = [starved, total]
        out[mode] = res
    # grid details, SLO / MLO, N4 at MCS 0
    det = {}
    for mode in LINK_MODES:
        data = A.build_dataset(idx, mode)
        rows = []
        for (rate, x, y), (c, rew, met) in sorted(data.items()):
            if rate != "EhtMcs0":
                continue
            rows.append({"pos": [x, y], "rssi_choice": A.HEURISTICS["RSSI"](c),
                         "feasible": P.feasible_actions(c),
                         "d_map1_minus_map4": float(np.mean(rew[0]) - np.mean(rew[1])),
                         "n5_map1": float(np.mean([o["tput_N5"] for o in met[0]])),
                         "n5_map4": float(np.mean([o["tput_N5"] for o in met[1]]))})
        det[mode] = rows
    out["_grid_mcs0"] = det
    with open(os.path.join(A.OUT, "diag_policy_breakdown.json"), "w") as f:
        json.dump(out, f, indent=1)
    for mode in LINK_MODES:
        print(mode, "starved", out[mode]["_starved_runs"])
        for name in choices:
            pf = out[mode][name]
            print(f"  {name:11s}", "  ".join(
                f"f={fl}: {pf[fl]['mean_gain']:+.3f} (edge {pf[fl]['edge_contrib']:+.3f}, "
                f"other {pf[fl]['mean_gain_other_positions']:+.3f})" for fl in pf))


if __name__ == "__main__":
    main()
