#!/usr/bin/env python3
"""tables/tab_inputsens.tex from desk_checks_2026-11-03/f1_bss_load/*.json (F1, input sensitivity)."""
import json, os
F1 = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2/desk_checks_2026-11-03/f1_bss_load"
fx = json.load(open(os.path.join(F1, "f1_fixed_rules.json")))["modes"]
f = lambda v: f"${v:+.3f}$".replace("+0.000", "0.000").replace("-0.000", "0.000") if abs(v) >= 0.0005 else "$0.000$"
ci = lambda t: f"{f(t[0])} [{f(t[1])}, {f(t[2])}]".replace("$ [$", " [").replace("$, $", ", ").replace("$]", "]$")
rows = []
for mode, name in (("slo", "SLO"), ("mlo", "MLO"), ("mloConfined", "MLO-conf.")):
    L = json.load(open(os.path.join(F1, f"f1_learners_{mode}.json")))["learners"]
    m = fx[mode]
    rows.append(f"{name} & {ci(m['AirtimeThr|D0']['shortfall'])} & {ci(m['AirtimeThr|D3']['shortfall'])} & "
                + " & ".join(ci(L[k]["D3"]["vs_AirtimeThr"]) for k in ("neural", "ucb1", "linucb")) + r" \\")
tex = r"""\begin{table*}[t]
\caption{Sensitivity to the utilization input: regret of AirtimeThr and learner minus AirtimeThr.}
\label{tab:inputsens}
\centering
\footnotesize
\setlength{\tabcolsep}{2.5pt}
\begin{tabular}{llllll}
\toprule
 & \multicolumn{2}{c}{AirtimeThr regret} & \multicolumn{3}{c}{Learner $-$ AirtimeThr, other-seed 8-bit input} \\
Config. & original input & other-seed 8-bit & DAMA-MLO & UCB1 & LinUCB \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table*}
"""
open("tables/tab_inputsens.tex", "w").write(tex)
print(tex)
