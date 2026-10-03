"""Write the runs file of the secondary analysis ("excluding trace-confirmed
ADDBA-expiry cases"): every record of runs.jsonl except the version-2.1
records whose arguments are listed in excluded_addba.jsonl.

usage: python3 make_excl_runs.py RUNS.jsonl EXCLUDED.jsonl OUT.jsonl
"""
import json
import sys

runs, excl, out = sys.argv[1:4]
drop = []
with open(excl) as fh:
    for line in fh:
        e = json.loads(line)
        drop.append((e["version"], json.dumps(e["args"], sort_keys=True)))
kept = removed = 0
with open(runs) as fi, open(out, "w") as fo:
    for line in fi:
        r = json.loads(line)
        key = (r.get("codeVersion", "2.0"), json.dumps(r["args"], sort_keys=True))
        if key in drop:
            removed += 1
            continue
        fo.write(line)
        kept += 1
print(f"kept {kept}, removed {removed} (expected {len(drop)})")
if removed != len(drop):
    sys.exit("excluded records not matched one to one")
