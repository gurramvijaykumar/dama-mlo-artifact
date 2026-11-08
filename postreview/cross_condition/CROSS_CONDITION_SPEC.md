# DAMA-MLO cross-condition study: frozen specification (Stage 0 output, 2026-11-08). NO SIMULATION RUN.

Implements CROSS_CONDITION_STUDY_PLAN_2026-11-08.md (gate 1 approved), with the five review points resolved. The
plan's budget and conditions are unchanged. Gates: (2) this spec -> Stage A, 34 runs; (3) frozen predictions and
analysis code -> Stage B, 480 runs. Endpoint: a revised manuscript and one Q1 submission assessment, with no
automatic further campaign.

## 1. Question, identity and the claims that can be made
When is AirtimeThr (delta = 0.2) practically sufficient for an arriving station under SLO and MLO, and where does it
fail? The study keeps:
- two candidate APs;
- the existing policies, the empirical oracle and sum-log utility;
- saturated TCP uplink.
Possible claims are per cell (condition x mode):
(a) whether association helps;
(b) whether AirtimeThr's departures from RSSI help or harm;
(c) whether AirtimeThr is practically sufficient or fails;
(d) how learners trained on T0 perform when transferred unchanged.
Claim (d) is about TRANSFER. It does not test whether learners retrained on a condition could outperform AirtimeThr.

## 2. Conditions and the exact configuration changes
All runs use simlib BASE (TCP uplink, simTime 13 s, warmup 3 s, 80 MHz 5 GHz backhaul, accessExp 2.5, staDist 20 m,
n4X = 120 m) and the v2.2 diag build.
| Id | Arguments that differ from BASE | Stations (N incl. N5) | d_N = 0.01 N |
|---|---|---|---|
| T0 | none (stored v2.0 grid; desk only) | 5 | 0.05 |
| T1 | n4Rate EhtMcs0, extraMap4Slow = 1 (second slow station, EhtMcs0, at (14.1, 164.1)) | 6 | 0.06 |
| T2 | n4Rate EhtMcs0, mapSpacing = 100 | 5 | 0.05 |
| T3 | n4Rate EhtMcs4, extraMap4 = 2 (fast stations at (20, 150) and (-25, 150)) | 7 | 0.07 |
d_N corresponds to about a 1% geometric-mean throughput difference (exp(0.01) - 1 = 1.005%); the absolute 0.05 is
reported alongside.

What mapSpacing S changes (source diff: stage0/make_v22_source.py; default S = 150 m reproduces v2.0):
- the nine MAP positions (S times the v2.0 grid divided by 150): MAP 1 (0, 2S), MAP 4 (0, S), MAP 7 (0, 0), and so
  on;
- N1 at (0, 2S + staDist), N2 at (staDist, 2S), N3 at (0, S - staDist);
- N4 at (n4X, S) (its y follows MAP 4; n4X stays an absolute 120 m);
- the extraMap rings, centred on (0, 2S) and (0, S).
Unchanged: the gateway (450, 150) and server (600, 150), which are wired point-to-point nodes without radios;
n5X/n5Y; newSta; every other parameter. With S = 100 the backhaul hops are also 100 m. T2 therefore changes the
backhaul and the access geometry together, and its effect is not attributed to one of them.

## 3. Selected positions (frozen; stage0/stage0_screen.json)
Rule from the plan:
- lattice x in {10, 25, 40, 55, 70, 85, 100}, y = S + {0.2, 0.4} S;
- both MAPs above -82 dBm + 1 dB on every link under SLO and MLO, with the 0.029 dB offset included;
- RSSI chooses MAP 4;
- at most 8 positions, at evenly spaced ranks.
Results:
- T1 and T3 (S = 150): 10 positions qualify. The 8 selected are (10,180), (10,210), (25,210), (40,180), (40,210),
  (55,180), (70,210) and (85,210). Hidden-station flag: N1 at (40,180) and (55,180), where N5 cannot hear N1.
- T2 (S = 100): 14 positions qualify. The 8 selected are (10,120), (25,120), (40,120), (55,120), (55,140), (70,140),
  (85,140) and (100,140). No hidden-station flag.
- All three conditions are feasible (at least 6 positions).
- T0 reference: the stored-grid positions that satisfy the same J/RSSI rule (6 under SLO, 3 under MLO; different
  lattice). T0 is descriptive only.

## 4. Airtime model: assumptions, predicted orderings, calibration, and what this means for predictions
Model (stage0/screen_and_model.py, model()):
- every station is saturated, and CSMA/CA gives each station on a link one frame per round (Heusse 2003);
- frame time is T = T_oh + L/R;
- no aggregation, collisions, hidden stations, backhaul or TCP;
- under MLO the per-link throughputs add;
- the ideal rate comes from SNR through an approximate EHT 20 MHz threshold table (anchored on the v2.0 MCS 4 decode
  observation);
- the utility is sum-log over both cells.
Robustness was checked over L in {1500, 15000} B and T_oh in {50, 150} us.

Predicted orderings at the selected positions (MAP 1 minus MAP 4, model sum-log):
- T1: MAP 1 better at 8/8 under SLO and MLO, robust at 7/8. The model gain over RSSI is about 0.4-0.5, against
  d_N = 0.06.
- T2: MAP 1 better at 6/8 (SLO) and 5/8 (MLO).
- T3: MAP 1 better at 6/8 (SLO) and 5/8 (MLO), but robust at only 3/8 and 4/8.

Calibration on stored data (T0 decision-relevant contexts, desk):
- the model's direction agreed with the stored oracle in 7 of 27 contexts (SLO: 1/6, 1/6 and 5/6 for MCS 0, 2
  and 4; MLO: 0/3 at each rate);
- the cause, visible in the stored outputs: the model gives N5 a high PHY rate to MAP 4 and prefers it, while in
  the simulation N5 delivers about 13 Mbit/s on MAP 1 whatever its PHY rate (e.g. at (10, 165): 13.0 on MAP 1 vs
  8.6 on MAP 4);
- an end-to-end limit that the model omits (backhaul / TCP) therefore decides the ordering.

Consequences, fixed now:
- The model is NOT a credible predictor of the better MAP in this mesh. Its orderings are recorded as a model check
  only. Its agreement with the Stage B oracle will be reported, and no claim rests on it.
- T3's expected failure is WITHDRAWN as a prediction. High MAP 4 utilisation from fast stations does not establish
  that MAP 4 is the better destination. The model itself favours MAP 1 at most T3 positions, and it is poorly
  calibrated. T3 is kept because it is the only condition in which high utilisation is not caused by a slow
  station, so it tests whether AirtimeThr's response to load helps or harms. Its outcome is open, and any
  mechanism stays unconfirmed until tested.
- No condition carries a justified failure prediction. Any BOUNDARY found is reported as observed, without a
  claimed mechanism.
- The only prediction frozen at Stage P is the deterministic one: AirtimeThr's choice at every (position, mode,
  seed), computed from the Stage A pre-arrival utilisation before any Stage B run.

## 5. Estimands per cell (condition x mode; context = selected position; 5 seeds; paired by seed)
- G = mean over contexts of (oracle - RSSI): the AVAILABLE GAIN. Does association help?
- D = mean of (AirtimeThr - RSSI): the INTERVENTION EFFECT. It is reported with the departure rate (the share of
  (context, seed) choices where AirtimeThr differs from RSSI). Do its departures help or harm?
- S = mean of (oracle - AirtimeThr): the SHORTFALL. Is it sufficient?
- For each learner l (DAMA-MLO, UCB1, LinUCB; trained on T0, unchanged): L_l = mean of (learner - AirtimeThr).
G and D are reported separately and are not pooled into one "informative" label. The oracle is the empirical
hindsight oracle over J, as in the manuscript, and includes selection optimism.

## 6. Uncertainty and tests (exact)
- Fixed rules: a paired two-stage cluster bootstrap, as in analyze.cluster_boot. B = 10,000, generator seed
  20261108. Positions are resampled with replacement, then the seeds within each position. 95% percentile
  intervals.
- Learners: a three-stage bootstrap. Positions are resampled, then the 5 training replicates (with replacement;
  their choices averaged), then the seeds. Training variation is therefore inside the interval. The replicate SD is
  reported.
- One-sided bootstrap p-value for H1: theta > c is p = (1 + #{b : theta*_b <= c}) / (B + 1). For H1: theta < c, it
  is p = (1 + #{b : theta*_b >= c}) / (B + 1).
- Each test is at one-sided alpha = 0.025, which matches the 95% two-sided intervals.
Families (Holm step-down within each family, alpha = 0.025; T0 cells excluded from every family because their data
were examined before):
| Family | Hypotheses | Size |
|---|---|---|
| F-G "association helps practically" | H1: G > d_N | 6 cells |
| F-D+ "intervention helps" | H1: D > 0 | 6 |
| F-D- "intervention harms" | H1: D < 0 | 6 |
| F-S "AirtimeThr sufficient" | H1: S < d_N | 6 |
| F-B "AirtimeThr fails" | H1: S > d_N | 6 |
| F-L+ "learner better under transfer" | H1: L_l > d_N | 18 (3 learners x 6 cells) |
| F-L0 "no practical learner gain under transfer" | H1: L_l < d_N | 18 |
Verdicts per cell:
- SUFFICIENT: F-S rejected AND F-G rejected. If F-S is rejected but F-G is not, the cell is labelled "sufficient
  but uninformative: no demonstrated available gain".
- FAILS: F-B rejected.
- INCONCLUSIVE: otherwise.
- Intervention verdicts come from F-D+ and F-D-. Their size is also compared with d_N, descriptively.
- A learner verdict needs Holm rejection over its 18-member family.
Unadjusted intervals and p-values are reported for every quantity.

## 7. Validity checks
- Controls (Stage A): v2.2 at its defaults must reproduce four stored v2.0 records field for field: slo and mlo,
  pre-arrival and scenario 2 at (40, 195), seed 1. Each reference is unique and equal to the record analyze.py uses
  (asserted in run_stageA.py).
- Health flags (every run), as in F2: non-zero exit or timeout; ns-3.48/My created; a station with zero delivery; no
  association by 3 s; any DEASSOC. A flag is diagnosed from its trace (contention / implementation / undiagnosed)
  and never excluded or relabelled without that diagnosis. The primary analysis keeps every run. Late-start
  warnings are recorded and not interpreted with the five-station baseline.
- Analysis geometry: a wrapper sets the MAP positions of each condition for the context, J and RSSI code
  (policies.py is not edited). It must reproduce the stored T0 results exactly at S = 150 before it is used.

## 8. Run budget and cap (exact)
| Stage | Calculation | Runs |
|---|---|---|
| A controls | 2 modes x 2 configurations x 1 seed | 4 |
| A pre-arrival | 3 conditions x 2 modes x 5 seeds | 30 |
| B outcomes | 3 conditions x 8 positions x 2 arms (N5 -> MAP 1, N5 -> MAP 4) x 2 modes x 5 seeds | 480 |
| Total | | 514 |
Cap and rules:
- Hard cap: 560 runs and 6 h of wall time (measured 64-107 s per diag run, 3 in parallel, about 4 h expected).
- The 46 spare runs may be used ONLY to re-execute a run that the HOST killed (OOM, disk full, power loss), at most
  once per run, logged.
- A run that exits non-zero, times out or carries a health flag is a data point. It is kept and not re-run.
- An infeasible condition: none now. If a condition later became unusable, for example because its controls fail,
  its runs are not reallocated.
- If a cap is reached, unfinished cells are reported as incomplete and no verdict is given for them.
Stopping rules:
- Any control mismatch: stop.
- Health flags in more than 5% of a stage's runs: pause, diagnose and report.
- No added seeds, positions or conditions after outcomes are seen.

## 9. What is frozen when
- Now (gate 2): this spec, the v2.2 source and binary, the position lists, the model check, and run_stageA.py.
- Stage P (gate 3, before any Stage B run): AirtimeThr's choices from the Stage A utilisation, the Stage B runner,
  the analysis code (wrapper, bootstrap, Holm), and its reproduction of T0.
Hashes: stage0/FREEZE_STAGE0.txt.
