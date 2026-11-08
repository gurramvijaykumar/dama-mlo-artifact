# Errata and amendments to CROSS_CONDITION_SPEC.md (frozen spec not edited, so its hash stays valid)

A1 (2026-11-08, before any Stage A run; execution order only): run_stageA.py gained --controls-only. The 4 controls
run first; the 30 pre-arrival runs start only if all 4 exited 0, created no ns-3.48/My and match their stored records
in every field (asserted). Re-frozen in stage0/FREEZE_STAGE0_A1.txt.

Q1 (review, wording): the 7/27 agreement shows poor predictive performance of the model on those T0 contexts. It does
NOT establish that an omitted end-to-end bottleneck determines the ordering. That reading (N5 ~13 Mbit/s on MAP 1
whatever its PHY rate) is an explanation to investigate only within the approved scope. No calibration campaign is
added to recover the withdrawn failure prediction.
Q2 (review, naming): T2 changes access and backhaul geometry together. It is reported as a NETWORK-SPACING condition.
Q3 (review, statistics): Holm controls the familywise error WITHIN each declared family, not across the seven
families. Each one-sided test at alpha = 0.025 corresponds to one endpoint of the two-sided 95% percentile interval.
Bootstrap p-values use the same bootstrap distribution as the intervals (same B = 10,000 and generator seed), so a
one-sided test rejects at 0.025 exactly when the relevant 95% endpoint lies beyond the threshold (up to the
(1 + count) / (B + 1) correction).
Interpretation (review): the study is a bounded empirical comparison across conditions, not a test of predicted
failure mechanisms. Its contribution is not guaranteed.

A2 (2026-11-08, after Stage A, before Stage P was frozen): the health rule "a station delivers 0" was implemented
as tput <= 0. In A_T2_mlo_pre_s1, N3 and N4 delivered 0.00009 Mbit/s with 0 data frames, which that test missed.
The rule is now implemented as tput < 0.01 Mbit/s (the manuscript's starvation threshold). Re-checked: Stage A has
1 flagged run of 34 (2.9%, below the 5% pause rule); the 26 F2 validation runs have none (F2 result unchanged).
Diagnosis of A_T2_mlo_pre_s1 (from its existing diag trace; no new run):
- TCP of N3 and N4 stayed in SYN_SENT for the whole run;
- MAP 6 (node 5) never resolved its backhaul ARP entry for 10.1.1.5 (DELAY, then STALE, empty lladdr; 16 ARPDROP
  events on node 5);
- MAP 4's access-side ARP table stayed empty (seed 2: both entries REACHABLE by 3 s).
This matches the documented fault class "lost broadcast ARP requests on the backhaul" (manuscript appendix). The
root cause of the lost requests is not established, so the category is NOT "implementation" but "known fault class,
root cause undiagnosed". The run is kept (primary analysis keeps every run). Its utilisation enters the T2 MLO
contexts: SEEDMEAN mean u4 - u1 = 0.34 (> delta, AirtimeThr choice unchanged); OWNSEED seed 1 sees an idle MAP 4.

A3 (2026-11-08, gate 3 approval, before any Stage B run):
- Primary input = OWNSEED (per-seed utilisation, as specified in Sec. 4). SEEDMEAN is a SECONDARY analysis, kept
  for comparison with the manuscript protocol. stageB_analysis.py writes both; the report labels OWNSEED primary.
- Workers = 3. Study cap of 6 h: Stage A used 1408 s of wall time (controls 190 s, pre-arrival 1218 s), so Stage B
  runs with STAGEB_CAP_S = 20192 s. Runs not started by then are "not run", and their cells are reported as
  incomplete. No budget extension.
- Health: the amended checker was applied to all Stage A runs; both records are kept (stageP/health_records_stageA.md).
  Pause rule re-assessed: 1/34, no pause.
- Pause rule during Stage B: a watcher (stageP/watch_stageB.py) stops the runner if more than 5% of the 480 Stage B
  runs (i.e. 25 or more) carry a health flag under the amended checker.
- Flagged input: A_T2_mlo_pre_s1 stays in the primary analysis. The T2 MLO seed 1 policy input is identified as
  coming from a run with an unresolved backhaul ARP failure (MAP 4 idle because N3 and N4 never sent). It is NOT a
  healthy load observation.
- Interpretation: where policies make identical choices, identical outcomes establish behavioural agreement on
  those contexts, not independent evidence of learner effectiveness. Identical-choice contexts are reported per
  cell and per learner.

A4 (2026-11-08, during Stage B, before any Stage B health output was read): the spec's pause rule (Sec. 8) reads
"Health flags in more than 5% of a stage's runs: pause, diagnose and report"; the plan adds "before continuing". It
does not say "of all 480 planned runs". Amendment A3 had implemented it as >= 25 of 480. That is not equivalent: for
example, 6 flags among 100 completed runs exceed 5% but would not have paused. Clarified: the denominator is the
COMPLETED Stage B runs at each check (every 120 s), and the run pauses when flagged / completed > 0.05. No minimum
count was added. The clarification follows the spec wording, not any outcome; health_live.json was not read before
it.
Execution note: the first attempt to stop the old watcher used "pkill -f watch_stageB.py". The pattern also matched
the shell issuing it, which was killed before any edit was made. The old watcher stopped; the Stage B runner was
unaffected (verified by an exact process listing). The corrected watcher stops processes by PID from an exact
listing. It was restarted at the time stamped below. Between the old watcher's stop and this restart, no pause
check ran; the restarted watcher checks every completed run, including those finished in that gap.
2026-11-08T16:55:49+05:30

R1 (record, 2026-11-08T16:57:52+05:30): first check of the corrected watcher. 9 Stage B runs completed, 0 flagged
(0%), so the rule did not trigger. The old watcher completed no check (health_live.json was first written by the
corrected watcher). Gap: the runner started 16:53:09, and enforcement resumed 16:55:50. Three runs completed in the
gap (B_T1_slo_x10_y180_MAP1_s1, _s2, _s3), all unflagged, so the threshold was not crossed during the gap. No
executions after a missed pause exist. Stage B continues under the existing cap and rules.
