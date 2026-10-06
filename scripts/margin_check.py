"""Candidate-check margin sensitivity (offline, no new simulations).

The candidate check of Sec. 4.1 admits a MAP when the estimated beacon power of the
weakest link the station would set up is at least the preamble-detection level. The
receiver-matched estimate (path loss minus the 0.029 dB in-band offset) is exact in the
simulator; a deployed station would instead need a safety margin m:

    MAP j is a candidate  <=>  P_hat_j(weakest link) >= -82 dBm + m

m = -0.029 dB is the nominal check (estimate 0.029 dB too high), m = 0 the receiver-matched
check of the paper. When no MAP passes, the station joins the MAP with the larger
weakest-link power. Every choice is scored on the existing grid runs. The reference is
fixed for all margins: RSSI and the oracle under the receiver-matched check (m = 0), so a
margin can cost gain (it forces a MAP that is worse) as well as prevent a stall.

  python3 margin_check.py run MODE MARGIN [--no-learners]   -> results/margin_check/MODE_mMARGIN.json
  python3 margin_check.py table                            -> tables/tab_margin.tex
"""

import json
import os
import sys

import numpy as np

import analyze as A
import policies as P

OUTDIR = os.path.join(A.OUT, "margin_check")
MARGINS = [-0.029, 0.0, 0.5, 1.0, 2.0, 3.0]
MODES = ["slo", "mlo", "mloConfined"]
REPS = 5
ROUNDS = 4000
EXACT_OFFSET_DB = -0.029  # receiver-matched in-band offset (policies.CAND_RX_OFFSET_DB default)


def set_margin(m):
    """Make policies.forced_action use margin m on top of the receiver-matched estimate."""
    P.CAND_RX_OFFSET_DB = EXACT_OFFSET_DB

    def forced_action(ctx):
        pw = [P.weakest_link_rssi(ctx, ap) for ap in (0, 1)]
        ok = [p >= P.CAND_FLOOR_DBM + m for p in pw]
        if sum(ok) == 1:
            return ok.index(True)
        if sum(ok) == 0:
            return int(np.argmax(pw))  # nothing passes: join the MAP with the larger margin
        return None

    P.forced_action = forced_action


def reference(data):
    """RSSI and oracle actions under the receiver-matched check (m = 0)."""
    set_margin(0.0)
    ref = {}
    for k, (c, rew, _) in data.items():
        ref[k] = (A.HEURISTICS["RSSI"](c), A.oracle_action(c, rew))
    return ref


def score(data, ref, choices):
    recs = []
    for k, (c, rew, met) in data.items():
        a = choices[k]
        ar, ao = ref[k]
        recs.append({
            "key": k, "a": a, "a_rssi": ar, "a_oracle": ao,
            "d_seeds": [float(x) for x in np.asarray(rew[a]) - np.asarray(rew[ar])],
            "reg_seeds": [float(x) for x in np.asarray(rew[ao]) - np.asarray(rew[a])],
            "starved": int(sum(min(o.get("tput_N5", 0.0), 1e9) < 0.01 for o in met[a])),
        })
    return recs


def summ(recs):
    return {
        "gain_boot": A.cluster_boot(recs, "d_seeds"),
        "regret_boot": A.cluster_boot(recs, "reg_seeds"),
        "oracle_agree": float(np.mean([r["a"] == r["a_oracle"] for r in recs])),
        "n5_starved_runs": int(sum(r["starved"] for r in recs)),
        "n_runs": int(sum(len(r["d_seeds"]) for r in recs)),
    }


def run(mode, m, learners=True):
    idx = A.index(A.load_runs())
    data = A.build_dataset(idx, mode)
    ref = reference(data)
    set_margin(m)
    out = {"mode": mode, "margin_db": m,
           "both_candidates": sorted({(k[1], k[2]) for k, (c, _, _) in data.items()
                                      if P.forced_action(c) is None})}
    out["n_positions_both"] = len(out["both_candidates"])
    pols = {"RSSI": A.HEURISTICS["RSSI"], "Airtime": A.HEURISTICS["Airtime"],
            "AirtimeThr": A.HEURISTICS["AirtimeThr"]}
    res = {}
    for name, pol in pols.items():
        res[name] = summ(score(data, ref, {k: pol(c) for k, (c, _, _) in data.items()}))
    res["Oracle_m"] = summ(score(data, ref, {k: A.oracle_action(c, rew)
                                             for k, (c, rew, _) in data.items()}))
    if learners:
        positions = sorted({(k[1], k[2]) for k in data})
        for kind in A.LEARNERS:
            rep_recs = []
            for rep in range(REPS):
                choices = {}
                for pos in positions:
                    train = [(c, rew) for k, (c, rew, _) in data.items() if (k[1], k[2]) != pos]
                    pol = P.train_learner(kind, train, ROUNDS, seed=1000 * rep + hash(pos) % 997,
                                          constrained=True)
                    for k, (c, _, _) in data.items():
                        if (k[1], k[2]) == pos:
                            choices[k] = pol(c)
                rep_recs.append(score(data, ref, choices))
            avg = A.average_reps(rep_recs)
            res[kind] = {"gain_boot": A.cluster_boot(avg, "d_seeds"),
                         "regret_boot": A.cluster_boot(avg, "reg_seeds"),
                         "train_sd": float(np.std([np.mean([np.mean(r["d_seeds"]) for r in rr])
                                                   for rr in rep_recs], ddof=1)),
                         "n5_starved_runs_mean": float(np.mean([sum(r["starved"] for r in rr)
                                                                for rr in rep_recs]))}
    out["policies"] = res
    os.makedirs(OUTDIR, exist_ok=True)
    fn = os.path.join(OUTDIR, f"{mode}_m{m:+.3f}.json")
    with open(fn, "w") as f:
        json.dump(out, f, indent=1)
    print(fn)


LABEL = {"slo": "SLO", "mlo": "MLO", "mloConfined": "MLO-conf."}
COLS = [("AirtimeThr", "AirtimeThr"), ("Airtime", "Airtime"), ("neural", "DAMA-MLO"),
        ("ucb1", "UCB1"), ("linucb", "LinUCB"), ("Oracle_m", "Oracle")]


def fmt(b):
    v = f"{b[0]:+.3f}".replace("-0.000", "+0.000")
    return f"${v}$" if b[1] <= 0 <= b[2] else f"$\\mathbf{{{v}}}$"


def table():
    rows = []
    for mode in MODES:
        for m in MARGINS:
            fn = os.path.join(OUTDIR, f"{mode}_m{m:+.3f}.json")
            if not os.path.exists(fn):
                continue
            r = json.load(open(fn))
            p = r["policies"]
            mlab = "nominal" if m < 0 else ("matched" if m == 0 else f"{m:g}~dB")
            cells = [fmt(p[c]["gain_boot"]) if c in p else "--" for c, _ in COLS]
            rows.append(f"{LABEL[mode]} & {mlab} & {r['n_positions_both']} & " + " & ".join(cells) + r" \\")
        rows.append(r"\midrule")
    rows = rows[:-1]
    tex = [r"\begin{table*}[t]",
           r"\caption{Utility gain over RSSI against the margin of the candidate check.}",
           r"\label{tab:margin}", r"\centering", r"\small",
           r"\begin{tabular}{llr" + "r" * len(COLS) + "}", r"\toprule",
           r"Config. & Margin & Both & " + " & ".join(n for _, n in COLS) + r" \\", r"\midrule",
           *rows, r"\bottomrule", r"\end{tabular}",
           r"\par\smallskip\footnotesize Nominal: estimate 0.029~dB too high; matched: receiver-matched check ($m = 0$). "
           r"Both: grid positions where both MAPs are candidates. Reference for every row: RSSI and the oracle under the matched check. "
           r"Bold: paired two-stage bootstrap 95\% interval excludes zero.", r"\end{table*}"]
    path = os.path.join(A.HERE, "tables", "tab_margin.tex")
    with open(path, "w") as f:
        f.write("\n".join(tex) + "\n")
    print(path)


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], float(sys.argv[3]), learners="--no-learners" not in sys.argv)
    else:
        table()
