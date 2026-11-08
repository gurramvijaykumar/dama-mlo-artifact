#!/usr/bin/env python3
"""tables/tab_crosscond.tex and tables/tab_crosslearn.tex from the frozen cross-condition analysis
(desk_checks_2026-11-03/cross_condition/STAGEB_RESULTS.json; OWNSEED primary, SEEDMEAN secondary)."""
import json, os
CC = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2/desk_checks_2026-11-03/cross_condition"
d = json.load(open(os.path.join(CC, "STAGEB_RESULTS.json")))
f = lambda v: "0.000" if abs(v) < 0.0005 else f"{v:+.3f}"
ci = lambda q: f"${f(q['est'])}$ [${f(q['lo'])}$, ${f(q['hi'])}$]"
NAME = {"T1": "T1 two slow stations", "T2": "T2 network spacing 100 m", "T3": "T3 busy MAP 4, no slow station"}
VER = {"SUFFICIENT": "sufficient", "INCONCLUSIVE": "inconclusive", "FAILS": "fails"}
rows, lrows = [], []
for cid in ("T1", "T2", "T3"):
    for mode in ("slo", "mlo"):
        k = f"{cid}|{mode}"; o = d["OWNSEED"]["cells"][k]; s = d["SEEDMEAN"]["cells"][k]
        vo = VER[d["OWNSEED"]["verdicts"][k]["AirtimeThr"]]; vs = VER[d["SEEDMEAN"]["verdicts"][k]["AirtimeThr"]]
        lab = NAME[cid] if mode == "slo" else ""
        rows.append(f"{lab} & {mode.upper()} & {o['dN']:.2f} & {o['departure_rate']:.2f} & {ci(o['G'])} & {ci(o['D'])} & "
                    f"{ci(o['S'])} & {vo} & {s['departure_rate']:.2f} & {ci(s['S'])} & {vs} \\\\")
        fl = d["OWNSEED"]["families"]
        def lc(l):
            mark = "$^{\\dagger}$" if fl["F-L0"][f"{k}|{l}"] else ""
            return ci(o["L_" + l]) + mark
        lrows.append(f"{cid} & {mode.upper()} & " + " & ".join(lc(l) for l in ("neural", "ucb1", "linucb")) + r" \\")
tab = r"""\begin{table*}[t]
\caption{Cross-condition check: available gain, effect of AirtimeThr's departures, and shortfall, with per-seed and seed-mean input.}
\label{tab:crosscond}
\centering
\footnotesize
\setlength{\tabcolsep}{2pt}
\resizebox{\textwidth}{!}{
\begin{tabular}{llcclllllll}
\toprule
 & & & \multicolumn{5}{c}{Per-seed input (primary)} & \multicolumn{3}{c}{Seed-mean input (secondary)} \\
\cmidrule(lr){4-8}\cmidrule(lr){9-11}
Condition & Mode & $d_N$ & Dep. & $G$ = oracle $-$ RSSI & $D$ = Thr $-$ RSSI & $S$ = oracle $-$ Thr & Verdict & Dep. & $S$ & Verdict \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
}
\par\smallskip{\scriptsize Sum-log differences with 95\% two-stage bootstrap intervals; 8 positions, 5 seeds. Dep.: share of choices in which AirtimeThr departs from RSSI. T2 under MLO, seed~1: utilization taken from a flagged pre-arrival run (Section~\ref{sec:res-cross}).}
\end{table*}
"""
ltab = r"""\begin{table}[t]
\caption{Cross-condition check: learner minus AirtimeThr under transfer, per-seed input.}
\label{tab:crosslearn}
\centering
\footnotesize
\setlength{\tabcolsep}{2pt}
\resizebox{\columnwidth}{!}{
\begin{tabular}{llccc}
\toprule
Cond. & Mode & DAMA-MLO & UCB1 & LinUCB \\
\midrule
""" + "\n".join(lrows) + r"""
\bottomrule
\end{tabular}
}
\par\smallskip{\scriptsize Learners trained on the main grid, applied unchanged. Intervals include training variation. $^{\dagger}$: difference below $d_N$ supported after the Holm correction.}
\end{table}
"""
open("tables/tab_crosscond.tex", "w").write(tab); open("tables/tab_crosslearn.tex", "w").write(ltab)
print(tab); print(ltab)
