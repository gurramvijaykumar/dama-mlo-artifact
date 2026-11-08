# DAMA-MLO cross-condition study: plan for approval (2026-11-08). NOTHING RUN.

## 1. Question and intended contribution
Question (unchanged identity): when is a simple beacon-only association rule (AirtimeThr, delta = 0.2) practically
sufficient for an arriving station under SLO and MLO, and where does it fail? Two candidate APs, the existing
policies (RSSI, LoadAware, Airtime, AirtimeThr, UCB1, LinUCB, DAMA-MLO, oracle) and the sum-log metric are kept.
Intended contribution, IF the evidence supports it: a condition-level answer, i.e. AirtimeThr's shortfall against the
oracle in conditions that differ in anomaly strength, cell geometry and load composition, with the failure
conditions predicted from pre-arrival measurements before outcomes were simulated. Whether the evidence will
support it is not known. If every condition is uninformative or sufficient, the paper gains breadth, not a boundary.

## 2. Conditions: three new, one reference (each under SLO and MLO; MLO-confined dropped to bound the budget)
Factors chosen because they change the association decision, not to repeat the topology:
| Id | Condition | Factor | Change from T0 | Code change |
|---|---|---|---|---|
| T0 | Reference: stored grid, restricted to the position rule of Sec. 3 | none | none (desk re-scoring) | none |
| T1 | Strong anomaly: two slow stations on MAP 4 (N4 + one extra slow, both EhtMcs0) | anomaly strength, i.e. the size of the available gain | extraMap4Slow = 1 | none |
| T2 | Dense cells: MAP spacing 100 m instead of 150 m, same path loss (exponent 2.5) | geometry: both candidates strong, decision driven by load, not reach | mapSpacing = 100 | YES: scratch only, new parameter mapSpacing (default 150 must reproduce v2.0) |
| T3 | Busy MAP 4 without a slow station: N4 at EhtMcs4 (fastest decodable) + two extra fast stations on MAP 4 | load composition: high utilisation that is NOT an anomaly | n4Rate = EhtMcs4, extraMap4 = 2 | none |
Desk geometry check (done): exponent 3.0 with 100 m cells leaves no position with both MAPs above -81 dBm under
MLO, so steeper path loss is infeasible and not used. With 100 m and exponent 2.5, 27 lattice positions have both
MAPs in J with a 1 dB margin and RSSI towards MAP 4.

## 3. Positions (fixed rule, before any run)
The decision-relevant region is where RSSI chooses MAP 4, the AP that holds the slow station or the load. Elsewhere
every policy agrees.
- Lattice: x in {10, 25, 40, 55, 70, 85, 100} m, y = MAP 4 + {0.2, 0.4} x spacing.
- Rule: both MAPs in J with a 1 dB margin under SLO and MLO (0.029 dB offset included), and RSSI chooses MAP 4.
- Take the qualifying positions in (x, y) order. If more than 8 qualify, keep 8 at evenly spaced ranks. If fewer
  than 6 qualify, the condition is infeasible and is reported, not replaced.
- Hidden-station flags are computed and labelled, never excluded.
- T0 uses the stored grid positions that satisfy the same rule (desk only).
The estimand is the mean over the decision-relevant positions of a condition. This is a narrower estimand than the
manuscript's whole-grid mean, and it is stated as such; T0 is recomputed on it for comparison.

## 4. Practical-effect threshold
d_N = 0.01 N in sum-log, about a 1% geometric-mean throughput difference (exp(0.01) - 1 = 1.005%). N = stations
including N5: T0 and T2 have N = 5 (d = 0.05), T1 N = 6 (0.06), T3 N = 7 (0.07). The absolute value 0.05 is
reported alongside.

## 5. Predictions (made before outcome runs; Stage P)
The airtime model in the manuscript is directional and ignores the backhaul, and the F2 runs showed that utilisation
here is coupled through an end-to-end bottleneck. Advertised utilisation is therefore measured, not modelled:
- Stage A measures pre-arrival utilisation for each condition.
- AirtimeThr's choice at every position is then fixed from the measurements, because it is a deterministic rule.
- A per-cell airtime model predicts the better MAP at each position: equal transmission opportunities, per-station
  time L/R + overheads, and N5's rate from its SNR as the ideal rate manager would choose it.
- Positions where the two disagree are the predicted failures.
Directional expectations, stated now:
- T1: a larger available gain than T0, and AirtimeThr steers correctly, so SUFFICIENT is expected.
- T2: both candidates are viable, so the available gain is larger than in T0. The outcome is open; it is decided by
  the measured utilisation.
- T3: utilisation on MAP 4 is high without an anomaly. AirtimeThr is expected to steer N5 to MAP 1, where N5 is the
  slowest station, while the model favours MAP 4. A shortfall (BOUNDARY) is expected.
The prediction file (choices, predicted failures, expected verdicts) is hashed before Stage B. Prediction accuracy
is reported as a check of the model, not as a claim.

## 6. Outcomes per condition and mode (fixed now)
- INFORMATIVE if the oracle gain over RSSI has its lower 95% bound > d_N, OR AirtimeThr departs from RSSI in at least
  25% of the contexts. Otherwise the condition is UNINFORMATIVE: it is reported, and it supports neither
  sufficiency nor failure.
- If informative, using the shortfall S = oracle - AirtimeThr:
  - SUFFICIENT: upper bound of S < d_N.
  - BOUNDARY: lower bound of S > d_N.
  - INCONCLUSIVE: otherwise.
- Learners (H-LRN):
  - NO LEARNER GAIN: every learner's upper bound of (learner - AirtimeThr) < d_N.
  - LEARNER GAIN: a lower bound > d_N.
  - Otherwise inconclusive.
- Multiplicity: Holm over the 6 condition-mode cells for every BOUNDARY or LEARNER GAIN claim; unadjusted intervals
  are also reported.
- A verdict that contradicts its prediction is reported as observed. A BOUNDARY that was not predicted is not
  claimed as a mechanism.

## 7. Uncertainty
- Fixed rules: two-stage cluster bootstrap (positions, then seeds), as in the manuscript.
- Learners: trained as in the manuscript on the stored T0 grid (all 20 positions, 5 training replicates), then
  executed unchanged on T1-T3. This is a transfer test, with no retraining.
- Learner intervals: a three-stage bootstrap (positions, training replicates, seeds), so training variation is
  inside the interval.
- Seeds: 5 per context (1-5); Stage A uses the same seeds for its pre-arrival runs.

## 8. Validity checks
- Build: scratch/dama-mlo-v22-diag.cc = the validated diag source plus a mapSpacing parameter. No src/ edit. A new
  binary hash, frozen.
- Analysis: a wrapper passes each condition's geometry to the context and candidate-set code. policies.py is not
  edited.
- Controls (Stage A): v2.2 at its defaults must reproduce four stored v2.0 records field for field (slo and mlo
  pre-arrival seed 1, slo and mlo scenario 2 at (40, 195) seed 1).
- Health flags and diagnosis as in F2: no exclusion without a trace diagnosis; the primary analysis keeps every run;
  the late-start indicator is not interpreted with the five-station baseline.
- Geometry screen before runs: J with the margin, hidden-station flags, N5's predicted MCS on both MAPs.

## 9. Run budget and stopping rule
Plan:
- Stage 0, desk: build v2.2, the geometry and position screen, the frozen specs. No runs.
- Stage A: 4 controls + pre-arrival runs, 3 conditions x 2 modes x 5 seeds = 30. 34 runs.
- Stage P, desk: freeze the predictions.
- Stage B: 3 conditions x 8 positions x 2 modes x 2 actions x 5 seeds = 480 runs.
Total 514 runs. The diag build ran 64-107 s per run with 5-9 stations, so about 4 h of wall time at 3 in parallel.
Hard caps: 560 runs and 6 h of wall time.
Stopping rules (fixed now):
- Any control mismatch: stop.
- Health flags in more than 5% of a stage's runs: pause, diagnose and report before continuing.
- No added seeds, positions or conditions after outcomes are seen.
- An uninformative or infeasible condition is not replaced.

## 10. Approval gates
1. This plan.
2. Stage 0 output (v2.2 code diff, frozen hashes, selected positions) -> approval to execute Stage A (34 runs).
3. Frozen predictions -> approval to execute Stage B (480 runs).

## 11. What this study cannot do
- It keeps one mesh, two candidates and saturated TCP uplink.
- The learners are tested on transfer, not retrained.
- T2 changes the backhaul distances together with the access geometry, so its effect is not attributed to one
  factor.
