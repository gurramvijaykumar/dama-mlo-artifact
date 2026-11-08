# DAMA-MLO cross-condition study: Stage B results and per-criterion assessment (2026-11-08)

Inputs:
- frozen spec `CROSS_CONDITION_SPEC.md` with amendments A1-A4 (`SPEC_ERRATA_AND_AMENDMENTS.md`);
- Stage P choices `stageP/stageP_choices.json` (sha 97851f5d...);
- runner `stageP/run_stageB.py` (ff6f0f06...), watcher `stageP/watch_stageB.py` (4e5ee90e...), analysis
  `stageP/stageB_analysis.py` (ff7c6879...). All hashes were checked against the freeze records before the analysis ran.
Outputs:
- `STAGEB_RESULTS.json` (b4fa544b...): frozen tests, OWNSEED (primary) and SEEDMEAN (secondary), and T0 descriptive cells.
- `STAGEB_DESCRIPTIVE.json` (c9b1c8ac...) from `stageP/stageB_descriptive.py` (78d55675...). This is a per-context
  report written AFTER the frozen analysis. It contains no test.

## 1. Execution and health
- Stage B ran 480 of 480 runs from 16:53 to 21:05 (4 h 12 min). With Stage A, this is inside the 6 h cap. No cell is
  incomplete, and no spare run was used.
- Every run exited with code 0. No `ns-3.48/My` directory was created.
- The watcher (A4 denominator = completed runs) checked all 480 runs. It found 0 health flags: no delivery below 0.01
  Mbit/s, no late association and no DEASSOC. The pause rule never triggered, and no warnings appeared on stderr.
- The only flagged input in the study is Stage A's `A_T2_mlo_pre_s1`: N3 and N4 delivered 9e-05 Mbit/s, with backhaul
  ARP unresolved. It sets AirtimeThr's OWNSEED choice for T2 MLO seed 1. As required at gate 3, it stays in the
  primary analysis. It is not a healthy load observation.

## 2. Frozen verdicts (Holm within each family, one-sided alpha = 0.025)
Estimates are sum-log differences with 95% two-stage cluster-bootstrap intervals (B = 10,000). The departure rate is
the share of (position, seed) choices where AirtimeThr differs from RSSI.

PRIMARY (OWNSEED: each seed's own pre-arrival utilisation):
| Cell | d_N | Departure | G = oracle - RSSI | D = Thr - RSSI | S = oracle - Thr | AirtimeThr verdict | Intervention |
|---|---|---|---|---|---|---|---|
| T1 SLO | 0.06 | 1.00 | +1.176 [0.921, 1.451] | +1.176 [0.921, 1.451] | 0 [0, 0] | SUFFICIENT | helps |
| T1 MLO | 0.06 | 1.00 | +0.587 [0.457, 0.723] | +0.587 [0.457, 0.723] | 0 [0, 0] | SUFFICIENT | helps |
| T2 SLO | 0.05 | 1.00 | +0.557 [0.453, 0.669] | +0.557 [0.453, 0.669] | 0 [0, 0] | SUFFICIENT | helps |
| T2 MLO | 0.05 | 0.80 | +0.262 [0.201, 0.328] | +0.214 [0.153, 0.283] | +0.047 [0.017, 0.084] | INCONCLUSIVE | helps |
| T3 SLO | 0.07 | 0.60 | +0.269 [0.177, 0.371] | +0.201 [0.129, 0.287] | +0.068 [0.011, 0.130] | INCONCLUSIVE | helps |
| T3 MLO | 0.07 | 0.00 | +0.090 [0.045, 0.135] | 0 [0, 0] | +0.090 [0.045, 0.135] | INCONCLUSIVE | not shown |

SECONDARY (SEEDMEAN: seed-averaged utilisation):
- T1, T2 and T3 SLO are unchanged.
- T2 MLO is SUFFICIENT (departure 1.00, S = 0 [0, 0]).
- T3 SLO is SUFFICIENT (departure 1.00, S = 0 [0, 0]).
- T3 MLO is identical to the primary analysis (INCONCLUSIVE, departure 0).

F-B ("AirtimeThr fails") was rejected in no cell under either variant. In T3 MLO, the one-sided p for S > d_N is 0.20.
F-D- ("the intervention harms") was rejected in no cell.

Learners (trained on T0, applied unchanged; three-stage bootstrap):
- F-L+ ("learner better by more than d_N") was rejected for none of the 18 learner x cell hypotheses.
- F-L0 ("no practical learner gain") was rejected for 10 of 18 under OWNSEED: all 9 in T1 SLO/MLO and T2 SLO, plus
  DAMA-MLO in T2 MLO. It was rejected for none of the 6 T3 hypotheses.
- In T3 MLO all three learners score above AirtimeThr: DAMA-MLO +0.083 [0.035, 0.131], UCB1 +0.083 [0.038, 0.130],
  LinUCB +0.088 [0.039, 0.135]. For L > d_N the one-sided p is 0.23-0.31, so no learner gain is shown.
- In T3 SLO under SEEDMEAN, DAMA-MLO (-0.048) and UCB1 (-0.056) score below AirtimeThr.

T0 (descriptive only; excluded from every family):
- SLO, 6 positions: G = D = +0.341 [0.247, 0.430], S = 0.
- MLO, 3 positions: G = D = +0.159 [0.082, 0.243], S = 0.

## 3. What the per-context data show (descriptive; STAGEB_DESCRIPTIVE.json)
1. **The oracle choice is almost constant.** The empirical oracle picks MAP 1 in 47 of the 48 (cell, position)
   contexts. The exception is T3 MLO (40, 180): MAP 4 by 0.011, with MAP 1 better in 3 of 5 seeds. RSSI picks MAP 4
   everywhere, by the selection rule. Within each condition, the better destination therefore does not vary with
   position. The study cannot separate AirtimeThr from a fixed "always move to MAP 1" rule at these positions. Where
   AirtimeThr is SUFFICIENT, it is because it always departs and departing is always right. It is not shown to pick
   correctly among positions that need different choices.
2. **MAP 1 is better even when MAP 4 has no slow station.** In T3, MAP 4's high utilisation comes from fast stations.
   This matches the T0 calibration note (Spec Sec. 4): an end-to-end limit that the airtime model omits decides the
   ordering. We do not claim a mechanism.
3. **The primary-versus-secondary difference comes from per-seed decisions near the threshold.**
   - Under OWNSEED, AirtimeThr keeps MAP 4 for seed 1 at all 8 T2 MLO positions. That is the flagged ARP input of
     Sec. 1.
   - It keeps MAP 4 for seeds 1 and 2 at all 8 T3 SLO positions.
   - With the seed-averaged input it departs in every seed.
   So the INCONCLUSIVE verdicts for T2 MLO and T3 SLO come from per-seed variation of the advertised utilisation
   around delta = 0.2. In T2 MLO, the variation comes from a flagged run. This agrees with the F1 input-sensitivity
   finding.
4. **T3 MLO is the only cell where the rule leaves gain on every seed.** Under MLO, MAP 4's link-averaged utilisation
   stays below the threshold, so AirtimeThr behaves as RSSI. The estimated shortfall (0.090) exceeds d_N = 0.07, but
   its interval [0.045, 0.135] includes d_N, so neither sufficiency nor failure is shown. This is a candidate
   boundary, not an established one.
5. **Several agreements are behavioural, not independent evidence.** In T1 SLO/MLO and T2 SLO, AirtimeThr, the
   oracle and all three learners choose MAP 1 in every context and seed, so S = L = 0 exactly. These zero-width
   intervals record identical choices: behavioural agreement, not independent evidence of learner effectiveness. The
   rejections of F-S and F-L0 in these cells are mechanically guaranteed by the identical choices.
6. **Airtime-model check (Spec Sec. 4; no claim rests on it).** The model's predicted better MAP agrees with the
   oracle in 39 of 48 contexts: T1 8/8 and 8/8; T2 6/8 and 5/8; T3 6/8 and 6/8. On the T0 calibration it agreed in
   7/27. The model mostly predicts MAP 1, and the oracle is nearly always MAP 1. This agreement does not repair the
   calibration failure.

## 4. Statements the evidence supports
- S1. In all six new cells, association away from the RSSI choice has an available gain above d_N in five cells
  (Holm), and the gain is positive in all six. In T3 MLO the gain is +0.090 [0.045, 0.135], and G > d_N is not
  rejected.
- S2. Wherever AirtimeThr departs from RSSI, its departures improve the utility (F-D+ supported after Holm, five cells). No statistically supported harmful effect was detected in any cell (F-D- rejected in none). This is not a demonstration that harm is absent.
- S3. AirtimeThr is SUFFICIENT in T1 SLO, T1 MLO and T2 SLO under the primary analysis. With seed-averaged input it is
  also SUFFICIENT in T2 MLO and T3 SLO. The oracle choice is constant in these cells, so they do not test
  position-dependent selection.
- S4. No cell met the predefined failure criterion (F-B rejected in none), and three primary sufficiency verdicts remain inconclusive. T3 MLO, where MAP 4 is busy with fast stations and multi-link averaging keeps
  utilisation below delta, leaves an estimated 0.090 unrealised. This is inconclusive.
- S5. Under transfer, superiority by more than d_N is supported for no learner (F-L+ rejected 0/18). An upper bound
  excluding a practically meaningful gain is established in 10/18 (F-L0 rejected), nine of them identical-choice cells
  (behavioural agreement). In T3 neither is established.
- S6. The rule's decision is sensitive to per-seed variation of the advertised utilisation near delta. This is
  consistent with F1.
Not supported: a predicted failure condition (withdrawn at Stage 0); a mechanism for any verdict; learner benefit;
evidence that AirtimeThr selects correctly where the best MAP varies with position.

## 5. [Section removed from the public copy: internal submission assessment; see REDACTIONS.md]

## 6. Central limitation
The oracle's 47/48 preference for MAP 1 is central, not minor: the study supports sufficiency in some tested conditions
but does not demonstrate adaptive selection where the better AP varies substantially. The T2 MLO primary/secondary
discrepancy depends on the flagged pre-arrival input, and healthy Stage B outcomes do not repair that input.
