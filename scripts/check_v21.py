"""After switch_to_v21.sh: the rebuilt dama-mlo-v2 binary must report code 2.1 and
reproduce the validation runs of the 2.1 development build (results/validate_v21.json)
key for key: one uplink run and the downlink run with N4 at MCS 4."""
import json, os, subprocess, sys
import simlib
ref = json.load(open(os.path.join(simlib.HERE, "results", "validate_v21.json")))
ok = True
for name in ("id_mlo_s3", "dl_mlo_mcs4"):
    args = ref[name]["_args"]
    cmd = ["nice", simlib.BINARIES["2.1"]] + [f"--{k}={v}" for k, v in sorted(args.items())]
    p = subprocess.run(cmd, cwd=simlib.NS3_DIR, capture_output=True, text=True)
    out = simlib.parse(p.stdout)
    want = {k: v for k, v in ref[name].items() if not k.startswith("_")}
    diff = [k for k in want if out.get(k) != want[k]]
    print(f"[check] {name}: rc {p.returncode}, codeVersion {out.get('codeVersion')}, "
          f"{len(want)} keys, {len(diff)} differ {diff[:5]}")
    ok &= p.returncode == 0 and str(out.get("codeVersion")) == "2.1" and not diff
sys.exit(0 if ok else 1)
