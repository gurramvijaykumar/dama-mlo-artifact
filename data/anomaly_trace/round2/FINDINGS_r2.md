# Round-2 diagnosis of the zero-throughput anomalies (2026-10-02)

Binary: /home/vijay/ns3-diag/ns-3.48/build/scratch/ns3.48-dama-mlo-diag-optimized (isolated tree; src/ identical to
production; optimized + native, same compiler). Program = dama-mlo-trace.cc + --diagTrace ("D" lines).
Production tree and its validated build untouched.

## Observers do not perturb
All 6 runs (A1 s2/s1, A2 s3/s1, B s8/s1) reproduce their stored runs.jsonl records exactly (92-125 keys, 0 differ),
with --psTrace and --diagTrace on.

## A. Saturated UDP, N5 delivers nothing -- MECHANISM ESTABLISHED (runtime state + ns-3.48 code)

A1 (mloConfined, N5 on MAP1, State 1, seed 2), uplink direction blocked:
- N5's application generated 147.5 MB; N5's IP layer sent ~8,929 packets/s; all were dropped by ARP
  (arpDrop N5 = 105,354; arpCacheDrop N5 = 3).
- N5's ARP entry for its gateway 10.2.1.1 (MAP1): WAIT_REPLY at t = 2 s, DEAD at the end. Control seed: REACHABLE at 2 s.
- N5 -> MAP1 Block Ack agreement: PENDING at 1.213 s; ADDBA Request dropped with EXPIRED_LIFETIME at 1.930 s; still
  PENDING at the end, with the QoS-data queue to MAP1 BLOCKED for reason WAITING_ADDBA_RESP on both links (read from the
  MAC queue scheduler at the end of the run); 1 frame still queued.
- The frames that expired in that blocked queue left at 1.930, 3.200 and 4.200 s -- one second apart, the ARP retry
  interval. In infrastructure mode a station's ARP request goes to its AP as a unicast (To-DS) frame, so N5's ARP
  requests sat in the blocked queue and never reached MAP1.
A2 (mlo, N5 on MAP4, State 4, seed 3), downlink direction blocked:
- N5 -> MAP4 agreement ESTABLISHED (N5's ARP requests reach MAP4).
- MAP4 -> N5 agreement PENDING to the end; MAP4's ADDBA Request dropped with EXPIRED_LIFETIME (round 1: 1.764 s); the
  AP's queue to N5 BLOCKED (WAITING_ADDBA_RESP) on both links at the end. MAP4's unicast ARP replies to N5 sit in that
  queue and expire (round 1: drop_ap_data_EXPIRED_LIFETIME x4).
- N5's ARP entry for 10.2.4.1: WAIT_REPLY at 2 s, DEAD at the end; 105,354 packets dropped at ARP.
Controls (A1 s1, A2 s1): both agreements ESTABLISHED, no blocked queue, gateway ARP REACHABLE at 2 s.

Chain: ADDBA Request expires in the queue (busy channel, ~97% utilization) -> ns-3.48 never sets NO_REPLY/reset on this
path (code: only the retry-limit discard path does, ht-frame-exchange-manager.cc:958-993; the queue-expiry path ends in
BlockAckManager::NotifyDiscardedMpdu, which ignores non-QoS-Data frames) -> agreement PENDING forever -> data queue to
that peer blocked forever (WAITING_ADDBA_RESP) -> the ARP exchange that rides on that queue cannot complete -> ARP entry
goes DEAD (ns-3 ArpCache: MaxRetries 3, then DeadTimeout 100 s default, longer than the run) -> every packet of the flow
is dropped at ARP.
The first link of the chain (agreement never leaves PENDING after the ADDBA Request expires) is an ns-3.48 handling gap:
a demonstrated implementation fault (code path + runtime scheduler state). Retry-limit loss of the same frame would
have triggered NO_REPLY, unblocking and a later retry.

## B. 160 MHz backhaul, seed 8, N5 on MAP1: MAP4's stations deliver nothing -- LOCALIZED, root cause of loss open

- N3 and N4: TCP never reaches ESTABLISHED (no state change until the forced close at 13 s; RTO changed 11 times =
  SYN retransmissions with back-off); application sent 0 bytes. N1, N2, N5 (MAP1 side) normal.
- Their SYNs go up: IP forward counts MAP4 -> MAP5 -> MAP6 small but non-zero, matching SYN retransmission times.
- MAP6 (gateway MAP of MAP4's subtree) never resolves its next hop MAP5 (10.1.1.5) on the backhaul: ARP entry
  WAIT_REPLY at 2 s, DEAD at the end; arpDrop MAP6 = 15, arpCacheDrop MAP6 = 3 (at 5.17 s). Control seed: REACHABLE at 2 s.
  => the server's SYN-ACKs to N3 and N4 are dropped at MAP6; with the entry DEAD (100 s), every later SYN-ACK too.
- Every Block Ack agreement on the path ends ESTABLISHED with no blocked queue (MAP6 -> MAP5 went PENDING -> NO_REPLY at
  1.129 s -> ESTABLISHED at 1.163 s). No MAC drops (retry limit / lifetime) on the backhaul devices. MAP6 sent one data
  frame per second in seconds 2-4 (consistent with ARP request retries every 1 s; the backhaul ARP request is a true
  broadcast, sent once, without Ack or retry).
- NOT established: why the ARP exchange on the backhaul failed (request not received by MAP5, or MAP5's reply lost).
  No Block Ack blocking was found, so the A fault is not shown to apply here. Candidate: broadcast ARP requests lost on
  the shared backhaul channel, then the ARP DEAD state (100 s) prevents recovery within the run (superseded by round 3).
- To close B: sniff ARP frames (MacTx/MacRx + PHY Rx drop reasons) on the backhaul devices of MAP4/5/6 in s8 vs s1.

## Implications (for the user to decide)
- A: demonstrated implementation fault at the start of the chain. A consistent rule would need to identify every run
  with the same signature; the stored run records do not contain BA/ARP state, so a rule needs either a proxy from
  stored outputs (e.g., a station with 0 transmitted data frames although its links decode beacons) or a trace rerun.
- B: as of now NOT a demonstrated implementation fault (ARP loss + ns-3 ARP defaults are model behaviour); under the
  user's rule B stays included unless the ARP-sniff round shows a fault.

## Round 3 (ARP capture), B pair: ROOT CAUSE OF THE ARP LOSS (2026-10-02 ~21:45)
Binary: same isolated build + ARP capture (MacTx/MacRx ARP frames, PHY receive drops of ARP frames) on all devices.
Both B runs again reproduce their stored records exactly (116/125 keys, 0 differ).
Seed 8 (failing):
- MAP6 sends its ARP request for MAP5 (10.1.1.6 -> 10.1.1.5) four times, at 1.1785, 2.1725, 3.1725 and 4.1725 s
  (ns-3 ARP retry every 1 s). Each is a broadcast on the shared 160 MHz backhaul: sent once, no Ack, no MAC retry.
- Every time, MAP5 drops it with PREAMBLE_DETECT_FAILURE, at the same instant as MAP1, MAP2, MAP4, MAP7 and MAP8;
  another backhaul MAP is transmitting at that instant (MAP3 reports TXING at 1.18, 3.18, 4.17 s; MAP1 at 2.17 s).
  Only MAP9 (and MAP3 at 2.17 s) receives the request. => the requests are lost to concurrent transmissions on the
  saturated backhaul (the MAP1-side flows of N1, N2 and N5 cross it); interference as the cause is inferred from the
  simultaneous preamble failures and the concurrent TXING, the interfering frame itself was not traced.
- After the 4th loss the entry becomes DEAD (ns-3 DeadTimeout 100 s): every SYN-ACK for N3/N4 is dropped at MAP6.
Seed 1 (control): MAP6's single ARP request at 1.143 s is received by MAP5, which replies at once (resolved at 1.148 s),
before the MAP1-side flows load the backhaul.
CONCLUSION B: no implementation fault shown. Mechanism = unacknowledged broadcast ARP requests lost to concurrent
backhaul transmissions on every retry, then ns-3's ARP dead state for the rest of the run. Under the user's rule,
B stays INCLUDED. (Wording for the paper, user 2026-10-02: describe the observed losses and concurrent transmissions directly and
call interference the INFERRED cause; distinguish the four ARP-level attempts (initial request + 3 ARP retries, 1 s
apart) from the absence of MAC retransmission of each broadcast; say the 100 s ARP dead-entry timeout PREVENTED
RECOVERY WITHIN THE 13 s SIMULATION -- do not call the loss permanent.)
