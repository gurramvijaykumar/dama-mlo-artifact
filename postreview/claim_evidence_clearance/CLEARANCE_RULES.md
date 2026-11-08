# DAMA-MLO claim-evidence clearance: rules fixed before any result was computed (2026-11-08)
Bounded task from the author: separate submission risks from evidence problems. Existing stored runs only. No new
simulation. Author acceptance or disclosure does not repair an evidence problem: a claim that fails here is narrowed or
removed before submission.

## A. Central claim
Claim: on the 14 common-candidate positions (N4 at MCS 0, 5 seeds, 80 MHz backhaul), the oracle gain over RSSI is 0.074
lower under MLO than under SLO, 95% paired two-stage bootstrap interval 0.020 to 0.135.
- A1 Reproduction: the stored runs must reproduce 0.0736 and its interval exactly.
- A2 Fault inventory: in all 280 runs of the estimator, count runs with any station below 0.01 Mbit/s and below
  0.05 Mbit/s. Name them, and state whether each enters the estimate through the RSSI or oracle action.
- A3 Floor rescoring: utility floor raised to 0.01, 0.1 and 1 Mbit/s.
- A4 Paired exclusion: remove every (position, seed) with a flagged run (below 0.05 Mbit/s) in either MAP and either
  mode, from both modes.
- A5 Position exclusion: remove every position with any flagged run.
- A6 Selection optimism: cross-fit the oracle. Choose its action on 4 seeds, score it on the fifth, over all 5 folds.
- A7 Leave one position out: report the range of the estimate.
Pass: A1 exact; the estimate is positive and the lower 95% bound is above zero in A3 (each floor), A4, A5 and A6; every A7
estimate is positive. If an item fails, the claim is narrowed to what passes, or removed if A1 or all of A3-A6 fail.
The size statement must cover the range found, not only 0.074.

## B. Share wording (bootstrap as in A or as in the manuscript's policy comparison)
- "most" of a gain requires the lower 95% bound of the share above 0.5. "nearly all" requires it at or above 0.9.
- Otherwise the sentence reports the estimate and interval, without the quantifier.
Applies to: "MLO took away most of the gain"; AirtimeThr "nearly all" under SLO; AirtimeThr "most" under MLO.

## C. Learner conclusions
Each statement must be limited to what was analysed: the evaluated fitted learners, on the evaluated contexts. Single-arrival
intervals are conditional on the five fitted replicates. Equivalence is not claimed, so no equivalence test is needed. Any
statement that generalises to learned policies at large is narrowed.

## D. Other claims resting on a documented fault
A claim whose stated result is set by a run with a documented fault must say so where it is made, or be removed.
