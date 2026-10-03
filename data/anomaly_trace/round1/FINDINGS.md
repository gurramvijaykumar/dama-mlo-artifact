# Zero-throughput anomalies in the code-2.1 sensitivity/backhaul runs (2026-10-02)

Traced with the existing binary (build/scratch/ns3.48-dama-mlo-trace-optimized, no rebuild), --psTrace=true.
Pairs: failing seed vs control seed with identical settings (jobs.txt). Compare: python3 compare.py.
All anomalous runs STAY in the analysis (user rule): zero throughput alone is not grounds for exclusion.

## Reproduction
All 6 traced runs reproduce their stored runs.jsonl records exactly (92-116 keys, 0 differ).

## A. Saturated UDP, N5 delivers nothing at a well-covered position

A1: mloConfined, N5 on MAP1, State 1 (70,225), UDP, seed 2 (control seed 1).
A2: mlo, N5 on MAP4, State 4 (70,225, N4 EhtMcs2), UDP, seed 3 (control seed 1).

OBSERVED (trace):
- Association is NOT the failure. In both failing runs N5 associates and sets up both links at ~0.122 s and
  stays associated to the end (S lines: assoc=1, links=0;1 every second). Beacons decoded at 15.7-16.9 dB SNR.
- A Block Ack agreement for N5's traffic never completes:
  - A1 s2 (uplink, N5 is the originator): ba_n5 PENDING at 1.213 s; N5's ADDBA Request got no Ack
    6 times (mpduTimeout_n5_action 6) and was dropped with EXPIRED_LIFETIME at 1.930 s. No later BA event
    (no NO_REPLY, RESET or ESTABLISHED) to the end of the run.
  - A2 s3 (downlink direction, MAP4 is the originator towards N5): ba_ap PENDING at 1.2245 s; the AP's ADDBA
    Request got no Ack 6 times (mpduTimeout_ap_action 6) and was dropped with EXPIRED_LIFETIME at 1.764 s.
    No later BA event. (N5's own uplink agreement was ESTABLISHED at 1.213 s.)
  - Control seeds: every agreement ESTABLISHED within ~0.3-35 ms of PENDING.
- After that, the affected flow carries no data: A1 s2 N5 sends 0 data MPDUs on L0, 1 on L1 (at t<1 s),
  N5 queue holds 1-3 packets for the whole run; A2 s3 N5 sends ~1 frame/s on L1 for 5 s and 6 on L0 at 2 s,
  then nothing; N5 queue 0. Channels ~97% busy (saturated UDP), so the ADDBA exchange competes with
  saturated traffic.

ESTABLISHED FROM ns-3.48 SOURCE (code reading):
- Creating an originator agreement (ADDBA Request queued) BLOCKS the QoS data queue to that recipient/TID
  (block-ack-manager.cc:214 m_blockPackets -> qos-txop.cc:112-120 BlockQueues(WAITING_ADDBA_RESP)).
- The queue is UNBLOCKED only when the agreement becomes ESTABLISHED, REJECTED, NO_REPLY or is reset
  (block-ack-manager.cc:280/1081/1103).
- NO_REPLY (+ a scheduled ResetBa after FailedAddBaTimeout) is set only in
  HtFrameExchangeManager::NotifyPacketDiscarded (ht-frame-exchange-manager.cc:958-993), the retry-limit
  discard path. The AddBaResponseTimeout path starts only after the ADDBA Request has been ACKED.
- An ADDBA Request that EXPIRES in the MAC queue (MSDU lifetime) leaves via WifiMacQueue's "Expired" trace,
  which is connected to (a) the dropped-MPDU trace (txop.cc:218), (b) BlockAckManager::NotifyDiscardedMpdu
  (qos-txop.cc:144), which returns at once for non-QoS-Data frames (block-ack-manager.cc:848-852), and
  (c) WifiMac::NotifyRsmOfExpiredMpdu (wifi-mac.cc:790). None of them calls NotifyOriginatorAgreementNoReply.
=> In ns-3.48, if an ADDBA Request expires in the queue instead of reaching the retry limit, the agreement stays
   PENDING and the data queue to that recipient/TID stays blocked for the rest of the simulation.
   The traces match this exactly (PENDING, ADDBA dropped with EXPIRED_LIFETIME, no further BA event, no data).

NOT YET ESTABLISHED (needs the new instrumentation):
- That the queue stayed blocked with reason WAITING_ADDBA_RESP to the end (inferred from code + traces, not
  read from the scheduler at runtime).
- Why so few packets reach N5's MAC queue in A1 s2 (1-3 instead of ~1000) and why N5 stops sending in A2 s3.
  Hypothesis: ARP. A2: MAP4's unicast ARP reply to N5 sits behind the blocked AP->N5 queue, so N5 never
  resolves the gateway and its ~1 frame/s for 5 s are ARP retries. A1: packets beyond the ArpCache pending
  queue (default 3) or beyond the blocked queue are lost before the MAC. To verify: ARP cache state, app tx
  count, IP drops.
- Whether this is a known/fixed upstream ns-3 issue.

## B. 160 MHz backhaul, seed 8, N5 on MAP1: MAP4's stations N3 and N4 deliver nothing

B: mloConfined, N5 on MAP1, State 3 (10,180), TCP, backhaul 160 MHz, seed 8 (control seed 1).
Status: REPRODUCTION + LOCALIZATION only (existing trace has no N3/N4 MAC/BA hooks and no MAP4 forwarding counts).

OBSERVED:
- Reproduces: N3 0, N4 0 Mbit/s; N1, N2, N5 higher than in the control (MAP1 cell gets the backhaul alone).
- N3 and N4 DID start: multi-link setup of N3 with MAP4 at 0.121 s and N4 at 0.122 s (P lines), identical to
  the control; each sent an ARP request for its gateway 10.2.4.1 (MAP4) at ~1.10 s / ~1.15 s (relayed as
  group frames by MAP4), as in the control. dN_N3 = dN_N4 = 2: two packets of each were delivered end to end.
- After that MAP4's cell is silent: util MAP4 L0 0.004, L1 0.003 (control 0.94 / 0.25); N3 and N4 send
  0 data frames in the window (control 1413 and 2044).
- The backhaul runs on its own channel object, isolated from the access channels (dama-mlo-v2.cc:470-496),
  so channel overlap is ruled out.
=> Localization: association and traffic start are fine; the flows stall after the first packets, before
   steady state, and MAP4's access channel goes idle. Not yet known whether the stall is on the access link,
   at MAP4, or on the backhaul. Candidate (hypothesis only): the same ADDBA-expiry block on one hop
   (N3/N4 -> MAP4, or MAP4's backhaul device -> next hop), which would stop all TCP after the first segments.

## Next (after the sweep chain and the PS full set finish)
New trace target (not an in-place edit; adding a scratch file triggers a CMake regen):
- BA agreement state events + ADDBA drops for ALL devices incl. N3, N4, AP and backhaul devices;
- queue-scheduler blocked reasons per recipient/TID at the end of the run;
- per-node IP forward/drop counts at MAP4 and backhaul hops; backhaul MAC drops; routing state;
- application packets generated (BulkSend/OnOff tx), TCP state + bytes acked + cwnd per flow;
- ARP cache events (request/reply/drop) at N5, N3, N4 and the MAPs.
Then: if the ADDBA-expiry block is confirmed as the cause, decide a consistent rule with the user (e.g. scan all
runs for the signature) -- exclusion only with a demonstrated fault and a consistent rule.
