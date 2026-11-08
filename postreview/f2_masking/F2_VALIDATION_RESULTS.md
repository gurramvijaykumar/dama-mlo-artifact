# F2 validation batch: results (executed 2026-11-08 with author approval; 26 runs)

Rules: F2_VALIDATION_SPEC.md v2 (frozen; all five hashes verified before execution) + F2_VALIDATION_SPEC_ERRATA.md
(wording only). Checker: check_f2_validation.py -> F2_VALIDATION_CHECK.json. All outputs preserved under runs/.

## 1. Execution
26/26 runs executed, all exit 0, none hit the 300 s timeout, ns-3.48/My not created. Wall time per run 64-107 s
(median about 94 s); the batch finished well inside the 30 min cap.

## 2. Health (V-A, V-B)
No health flag in any of the 24 runs: every station associated by 3 s, no DEASSOC, every station delivered traffic.
Warnings (not flags): 13/24 runs show a late first delivery (first non-zero bin = 2 s), mostly N3 and N4 together;
once only an extra station (S1). These are recorded and not interpreted; the start stagger grows with station
count (1.0 + 0.05 k s), and this indicator was calibrated on 5-station runs.

## 3. Control (V-C)
slo seed 1 and mlo seed 1 pre-arrival: every output field identical to the stored record (0 mismatches). The diag
binary and harness reproduce the stored grid.

## 4. Masking condition M (V-A)
| k | Mode | u1 (s101, s102) | u4 (s101, s102) | abs(u4 - u1) | AirtimeThr choice at (40, 195) | M1 | M2 | Candidate |
|---|---|---|---|---|---|---|---|---|
| 1 | SLO | 0.468, 0.466 | 0.888, 0.881 | 0.420, 0.416 | MAP 1, MAP 1 | no | no | no |
| 2 | SLO | 0.528, 0.507 | 0.824, 0.862 | 0.296, 0.355 | MAP 1, MAP 1 | no | no | no |
| 4 | SLO | 0.555, 0.558 | 0.777, 0.777 | 0.222, 0.219 | MAP 1, MAP 1 | no | no | no |
| 1 | MLO | 0.233, 0.233 | 0.663, 0.658 | 0.430, 0.425 | MAP 1, MAP 1 | no | no | no |
| 2 | MLO | 0.259, 0.256 | 0.580, 0.601 | 0.321, 0.345 | MAP 1, MAP 1 | no | no | no |
| 4 | MLO | 0.276, 0.281 | 0.539, 0.533 | 0.263, 0.252 | MAP 1, MAP 1 | no | no | no |
(u = link-averaged pre-arrival utilisation; RSSI chooses MAP 4 at (40, 195) and both MAPs are in J in every row.)

## 5. Batch outcome (per the frozen rules): NO CANDIDATE in either mode
None of the tested counts (k = 1, 2, 4 extra fast stations on MAP 1) qualified as a masking candidate under these
configurations (N4 EhtMcs0, TCP uplink, BASE parameters) and seeds (101, 102). In every case the utilisation gap
stayed above delta = 0.2, and the implemented AirtimeThr steered the newcomer away from the slow-station AP (MAP 4).
This is NOT a claim that the topology cannot produce masking.

## 6. Descriptive observation (preserved outputs; not a tested explanation)
Total uplink throughput stays near 57-63 Mbit/s as k grows. Extra MAP 1 stations raise MAP 1's throughput and lower
MAP 4's: SLO MAP 1 40.9 -> 50.5 Mbit/s and MAP 4 15.9 -> 12.3 from k = 0 to 4; MLO 36.6 -> 47.8 and 22.1 -> 15.7. The
k = 0 values are the stored grid, seeds 1-2. The utilisation gap therefore closes from both sides but slowly: about
0.42 -> 0.22 (SLO) and 0.43 -> 0.26 (MLO). This pattern is consistent with a shared end-to-end bottleneck coupling the
two MAPs. That cause is not established here, and no other counts, rates or traffic types were tested.

## 7. What this means for the study (no further work proposed in this file)
F2 as specified (masking by adding fast stations to MAP 1) did not reach its precondition in the tested range, so the
F2 campaign as designed has no qualifying composition to run. The decision on what follows returns to the author.

## 8. Closure (author decision 2026-11-08)
F2 is CLOSED as designed: no masking candidate qualified, so the F2 campaign does not run. Supported statements only:
(i) both controls reproduced the stored outputs; (ii) the tested configurations passed the specified health checks;
(iii) AirtimeThr continued to distinguish the MAPs in these configurations. General sufficiency is NOT established
(the challenging condition was never reached). The shared-bottleneck reading stays a hypothesis. The late-start
warnings are not interpreted with the five-station timing baseline. No increase of station counts, change of traffic
or pursuit of the bottleneck to obtain masking. In the manuscript F2 is labelled exploratory (Appendix app:masking).
