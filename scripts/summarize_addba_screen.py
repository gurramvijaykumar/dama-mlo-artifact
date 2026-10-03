"""Classify the traced zero-delivery candidates (screen_zero_delivery.py + results/addba_screen/run.sh), 2026-10-02.

Rule (user, 2026-10-02): a run is AFFECTED only if the trace shows that an ADDBA Request expired in the MAC queue
(drop <dev> action EXPIRED_LIFETIME to <peer>) and, at the end of the run, the agreement <dev> -> <peer> is still
PENDING with the QoS-data queue to <peer> blocked for WAITING_ADDBA_RESP, i.e. blocked from the expiry through the
rest of the run. Zero throughput or ARP failure alone does not count.
A classification is valid only if the traced run reproduces the stored result (every stored key equal).

Usage: python3 summarize_addba_screen.py [dir]   (default results/addba_screen)
Writes <dir>/classification.json and prints a summary.
"""

import json
import os
import re
import sys

import simlib as S

d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(S.HERE, "results", "addba_screen")
cands = json.load(open(os.path.join(d, "candidates.json")))


def base(label):
    """'MAP1/ap1L0(00:..)' or 'MAP1/ap1(00:..)' -> 'MAP1/ap1'"""
    return re.sub(r"L\d+$", "", label.split("(")[0])


rows = []
for c in cands:
    p = os.path.join(d, c["name"] + ".txt")
    if not os.path.exists(p):
        rows.append({"name": c["name"], "status": "not run"})
        continue
    text = open(p).read()
    rc = int(re.search(r"^rc (-?\d+)$", text, re.M).group(1))
    out = S.parse(text) if rc == 0 else {}
    diff = [k for k, v in c["out"].items() if out.get(k) != v]
    reproduced = rc == 0 and not diff
    expired = {}  # (dev, peer) -> first expiry time
    for t, dev, peer in re.findall(r"^D ([\d.]+) drop (\S+) action EXPIRED_LIFETIME to (\S+)", text, re.M):
        expired.setdefault((dev, base(peer)), float(t))
    stuck = []
    for dev, peer, st, blocked in re.findall(r"^D end ba (\S+) -> (\S+) tid=0 state=(\S+) queued=\d+ blocked=(\S+)",
                                             text, re.M):
        key = (dev, base(peer))
        if st == "PENDING" and "WAITING_ADDBA_RESP" in blocked and key in expired:
            stuck.append({"dev": dev, "peer": base(peer), "expiredAt": expired[key], "blocked": blocked})
    arp_dead = sorted(set(re.findall(r"^D arp end (\S+) if\d+ (\S+) dev \d+ lladdr \S+ STALE", text, re.M)))
    rows.append({
        "name": c["name"], "version": c["version"], "hits": c["hits"], "rc": rc,
        "reproduced": reproduced, "diffKeys": diff[:5],
        "affected": bool(stuck) and reproduced, "stuck": stuck, "arpDead": arp_dead,
        "args": {k: c["args"][k] for k in ("linkMode", "scenario", "n4Rate", "rngRun", "useTcp", "downlink",
                                            "backhaulWidth", "staDist") if k in c["args"]}
        | {k: c["args"].get(k) for k in ("n5X", "n5Y", "newSta") if k in c["args"]},
    })

json.dump(rows, open(os.path.join(d, "classification.json"), "w"), indent=1)
done = [r for r in rows if r.get("status") != "not run"]
print(f"traced {len(done)}/{len(rows)}; reproduced {sum(r['reproduced'] for r in done)}; "
      f"NOT reproduced {sum(not r['reproduced'] for r in done)}; AFFECTED {sum(r['affected'] for r in done)}; "
      f"stuck-but-not-reproduced {sum(bool(r['stuck']) and not r['reproduced'] for r in done)}")
for r in done:
    if r["affected"] or (r["stuck"] and not r["reproduced"]) or not r["reproduced"]:
        print(r["name"], r["version"], r["args"], r["hits"], "rc", r["rc"], "repro", r["reproduced"],
              [(s["dev"], s["peer"], s["expiredAt"]) for s in r["stuck"]], r["diffKeys"])
