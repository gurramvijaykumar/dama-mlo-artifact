# F2 validation batch: frozen specification, AMENDED 2026-11-08 (v2). FOR AUTHOR EXECUTION APPROVAL; NOT EXECUTED.

Amendments v1 -> v2: (1) the seed-1 record's provenance was resolved and V-C restored to mlo seed 1;
(2) condition M now requires the actual AirtimeThr decision, not only similar utilisation; (3) health flags are kept
separate from implementation faults; (4) the negative conclusion is bounded; (5) d is defined for varying station
counts; F1 is described as an input-sensitivity check, not deployment realism.

Scope: bounded validation of scenario v2.2 for family F2 (utilisation masking) only. NOT the F2 campaign, NOT F3/F4,
no further validation runs.
Purpose (tied to the original contribution): F2 tests the corrected core K2 + K3 under the condition the airtime
model predicts can defeat the beacon proxy. The tested claims are: a beacon-only threshold rule captures the
available association gain under MLO, and no learner improves on it. Same question, policies, sum-log metric,
oracle and candidate set J.
Endpoint: the F2 result becomes one generality subsection plus revised limitations in the DAMA-MLO manuscript. No new
policy, mechanism or reframing.

## 1. F1 findings and what they change in F2 (F1_RESULTS.md)
F1 was a quantised, cross-seed input-sensitivity check on the stored grid. Each policy read an 8-bit utilisation
from another seed's pre-arrival run. It did not establish deployment realism: no beacon loss, no load from the
newcomer itself, no time variation.
- Replication exact. Under that input perturbation AirtimeThr stayed practically sufficient in every mode (upper
  bound <= 0.011 vs d = 0.05), and no learner exceeded it by d.
- The robustness came from few contexts lying near delta = 0.2; under SLO a changed choice cost about 0.053 on
  average. -> F2 must place contexts in the masking region deliberately; condition M (Sec. 4) gates this.
- The grid's oracle gain over RSSI was below d in every mode, so SUFFICIENT was weakly informative. -> The F2
  campaign spec (separate approval) must state in advance that F2 is informative only where the available gain
  exceeds d. This validation does not look at gains.
- Perturbed inputs moved the learners little (within 0.0013). -> F2 reports both ideal and perturbed (D3) inputs.
- LinUCB's training spread under MLO-conf. (SD 0.036) was as large as its interval. -> The campaign uses the
  three-stage bootstrap (design Sec. 5).
- Correction: the design note's SLO oracle gain 0.116 had no source; the stored value is 0.046.

## 2. Scenario v2.2 = configuration only (no new C++)
The validated Stage 1 diag build already has the needed option. --newSta=x:y:map adds fast stations (wifiFast, the
same rate manager as N1-N3) on a named MAP. They start traffic with all other stations (1.0 + 0.05 k s), appear in
tput_*, sum-log and util_*, and are traced by the diag sinks. Earlier use: the C6 arrival experiment.
- Binary: build/scratch/ns3.48-dama-mlo-v20-diag-optimized, sha256 746687e279fa6de6164f2acbd3a4f0f796ea4bf56c1026152d4849b93e5c9267
  (source scratch/dama-mlo-v20-diag.cc, 2d93ab4920a160fc...). No rebuild, no src/ edit.
- Composition (fixed):
  - MAP 4 = N3 (fast) + N4 (slow, EhtMcs0), unchanged.
  - MAP 1 = N1, N2 + k extra fast stations, k in {1, 2, 4}, at 20 m from MAP 1 on the side away from the grid, in
    this order: (-20, 300), (0, 280), (-14.1, 314.1), (-14.1, 285.9).
  - No station is co-located. The built-in extraMap1 ring would put the first extra on N2's position, so it is
    not used.
- Geometry (computed, not traced): at the validation position (40, 195), N5 hears every extra above -82 dBm on
  both bands (weakest -80.9 dBm); both MAPs are in J under SLO and MLO; no hidden-station flag; RSSI picks MAP 4.
- All other parameters = simlib BASE (simTime 13 s, warmup 3 s, TCP uplink, 80 MHz 5 GHz backhaul).

## 3. Exact batch: 26 runs (runner run_f2_validation.py; --dry prints the plan)
- V-A, masking precondition: scenario 0 (no N5), k in {1, 2, 4} x {slo, mlo} x seeds {101, 102}. 12 runs.
- V-B, health with N5: N5 at (40, 195), scenario 1 and 2 (N5 -> MAP 1 / MAP 4), k in {1, 2, 4} x {slo, mlo},
  seed 101. 12 runs.
- V-C, control: the stored grid pre-arrival records for slo seed 1 and mlo seed 1, re-executed unchanged. 2 runs.
  These references were fixed before execution and were not chosen by matching.
  Provenance of the earlier "conflicting seed-1 record":
  - results/runs.jsonl holds exactly one grid pre-arrival record for mlo / EhtMcs0 / seed 1 (line 2).
  - The four other matches were C6 arrival-experiment runs (scenario 0 with a --newSta argument). These four are
    the only legacy records with newSta.
  - run_stage1.stored() matched them because it does not reject extra arguments.
  - analyze.load_runs excludes newSta runs, so F1 used line 2 (util MAP 1 L0 0.200083, MAP 4 L0 0.704395).
  - Every earlier stored() call looked up scenario 1 or 2, which none of these records has, so no earlier trace
    or campaign reference was affected.
  - The runner now uses a lookup that excludes newSta and asserts that the reference equals the record
    analyze.py uses.
Seeds 101-102 are outside the campaign seeds (1-5). V-B utilities are NOT used for any F2 claim and are not
inspected beyond the health rules.

## 4. Rules (checker check_f2_validation.py; tested on stored runs, Sec. 7)
Health flags per run (V-A, V-B):
- exit code non-zero, or the 300 s per-run timeout is hit;
- ns-3.48/My is created;
- a station delivers 0 in the measurement window;
- a station is not associated by 3 s, or any DEASSOC occurs.
A health flag is NOT a simulator defect. Zero delivery or late association can come from genuine contention or
hidden stations. Every flagged run is preserved (stdout, diag.txt) and diagnosed from its trace into one of:
- CONTENTION / LOAD (a legitimate network outcome);
- IMPLEMENTATION (only with trace evidence, e.g. the case-A watchdog mechanism confirmed, not inferred from a DEASSOC
  line);
- UNDIAGNOSED.
No flagged run is excluded or relabelled without that diagnosis.
WARNING only: late first delivery (first non-zero 1 s bin after bin 1; the State 1 indicator).
V-C: flag if any output field differs from the stored record.

Masking condition M (V-A), per composition k and mode, both seeds required:
- M1 (similar load): |u4 - u1| <= 0.15. Here u is the link-averaged pre-arrival utilisation that AirtimeThr reads,
  as an absolute difference, and 0.15 = delta - 0.05 allows for seed noise (SD about 0.03).
- M2 (actual decision): at (40, 195), with that seed's utilisation vector, J = {MAP 1, MAP 4}, RSSI chooses MAP 4,
  and the implemented AirtimeThr (delta = 0.2, analyze.HEURISTICS) also chooses MAP 4. The threshold therefore does
  not steer away from the slow-station AP.
- k is a MASKING CANDIDATE in a mode if M1 and M2 hold. That shows only that the rule would not react to load. It
  does NOT show that MAP 4 is the wrong choice; that is an outcome question for the campaign.

Batch outcome (fixed now):
- PASS: no health flag in V-A/V-B, V-C identical, and at least one masking candidate in SLO and in MLO. Next =
  write the F2 campaign spec for a separate approval.
- HEALTH FLAG: stop, preserve, diagnose (categories above), report. No campaign proposal until every flag is
  diagnosed.
- NO CANDIDATE in a mode: report that none of the tested counts (k = 1, 2, 4) qualified under these configurations
  (N4 EhtMcs0, TCP uplink, BASE) and seeds (101, 102). This is NOT a claim that the topology cannot produce masking.
  Return to the author; no redesign without approval.

## 5. The threshold d with more stations (fixed now, for the campaign)
A sum-log difference D over N stations equals a geometric-mean throughput ratio exp(D / N). With N = 5 (grid),
d = 0.05 means 1.0%. With k extras, N = 5 + k (MAP 1 and MAP 4 stations plus N5), so a fixed d = 0.05 means:
- 0.83% for N = 6;
- 0.72% for N = 7;
- 0.56% for N = 9.
That would make SUFFICIENT harder and BOUNDARY easier as k grows.
Primary rule: d is normalised per station, d_N = 0.01 * N (N = 5: 0.05, identical to F1; N = 6: 0.06; N = 7: 0.07;
N = 9: 0.09). This keeps the same meaning of a 1.0% geometric-mean throughput difference.
Secondary: the absolute d = 0.05 is reported alongside.
Utilities are compared only within one composition (same N); no comparison of sum-log values across different k.

## 6. Runtime cap
3 runs in parallel at nice 15. Per-run timeout 300 s (the measured diag-build maximum is 89 s with 5 stations).
Batch cap 30 min of wall time: runs not started by then are recorded as "not run" (a health flag). Expected: about
26 x 60-90 s / 3, roughly 9-13 min. Outputs: f2_masking/runs/<tag>/ (stdout, stderr, diag.txt) and
runs/validation_log.json.

## 7. Checker test (done, on stored runs; no new simulation)
- Case A flagged seed 1: flagged (zero delivery N5; DEASSOC of nodes 14 and 15); diagnosis PENDING (its watchdog
  mechanism was established separately by the case-A trace).
- Case A control seed 4: no flag.
- State 1 MLO MAP 4 seeds 1-10: no flags; late-start warnings in seeds 1, 2, 5, 7 and 10, i.e. 5/10, matching
  STATE1_CAMPAIGN_RESULTS.md.
- M logic on stored grid utilisations (synthetic V-A input):
  - SLO EhtMcs4: |u4 - u1| = 0.155 and 0.159, so M1 fails (above 0.15), while AirtimeThr keeps MAP 4 (M2 holds).
  - MLO EhtMcs0: |u4 - u1| = 0.50 and 0.55, and AirtimeThr switches to MAP 1, so M1 and M2 both fail.
  - Both cases behave as specified.

## 8. Frozen files (sha256)
See F2_VALIDATION_FREEZE.txt (re-frozen for v2).
