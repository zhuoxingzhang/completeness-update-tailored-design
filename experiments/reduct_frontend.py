"""RQ2 draft: schema-level comparison on the reduct Sigma[E] of real incomplete data.

Inputs: atomic closures of FDs mined from benchmark datasets under BOTH NULL
semantics (NULL EQUALITY / NULL UNCERTAINTY), shipped under data/fd/.
Positioning for the paper: each mined FD set is the reduct Sigma[E] the design
operates on; the two semantics bracket how a completeness reading turns the
same incomplete table into constraints.

Compared synthesizers (all on the same reduct, same keys):
  3nf        classical 3NF synthesis (Bernstein-style baseline)
  so         structure-optimal (fewest procedurally maintained FDs), frequency-blind
  ha         heat-aware (Algorithm 1 of the paper)
Heat protocol: each atomic FD is a mode, active with
probability p, active modes draw a level uniformly from {1..SCALE}; 3 seeds.

Datasets are discovered per semantics folder, processed in ascending atomic
size, and skipped above CAP atomic FDs (pathological closures such as diabetic
with 40k-144k atomic FDs are noted, not run).  Results are dumped to
rq2_draft.json incrementally after every dataset.
"""
import sys, os, json, time, statistics as st

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B

BASE = config.FD_BASE
SEMS = config.SEMS
MODES = ["3nf", "so", "ha"]
PS = [0.25, 0.5, 0.75]
SEEDS = list(range(10))
CAP = 10_000
HERE = os.path.dirname(os.path.abspath(__file__))

def atomic_count(path):
    d = json.load(open(path, encoding="utf-8"))
    return sum(len(fd["rhs"]) for fd in d["fds"])

def run_one(path):
    R, sigma, keys = B.load(path)
    prep = B.prepare(sigma)
    rows = {}
    for p in PS:
        acc = {m: {"hmax": [], "htot": [], "size": [], "crit": [], "t": []} for m in MODES}
        for seed in SEEDS:
            hot = B.levels(sigma, p, seed)
            for m in MODES:
                t0 = time.perf_counter()
                D = B.synthesize(R, sigma, keys, m, hot=hot, prep=prep)
                dt = time.perf_counter() - t0
                met = B.decomp_metrics(D, hot)
                acc[m]["hmax"].append(met["hmax"])
                acc[m]["htot"].append(met["htot"])
                acc[m]["size"].append(met["size"])
                acc[m]["crit"].append(met["crit"])
                acc[m]["t"].append(dt)
        rows[str(p)] = {m: {**{k: st.mean(v) for k, v in acc[m].items()},
                            "hmax_raw": acc[m]["hmax"]} for m in MODES}
    return {"R": len(R), "fds": len(sigma), "keys": len(keys), "ps": rows}

def write_md(out, skipped):
    lines = ["# RQ2: three synthesizers on the reduct Sigma[E]", "",
             "Data: atomic closures mined from real relations under two NULL readings, "
             "giving two reducts per relation.",
             "Heat protocol: every atomic FD is one mode, active with probability p, "
             "an active mode drawing its level uniformly from {1..10}; means over 10 seeds.",
             "hmax = maximal subschema heat of the design; crit = number of critical "
             "subschemata; size = number of subschemata.",
             f"Closures with |atomic| > {CAP} are skipped: "
             f"{', '.join(skipped) if skipped else 'none'}.", "",
             "| dataset | sem | R | atomic | p | 3NF hmax | SO hmax | HA hmax | SO crit | HA crit | SO size | HA size |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(out):
        ds, sem = key.split(":")
        res = out[key]
        for p, row in res["ps"].items():
            lines.append(
                f"| {ds} | {sem} | {res['R']} | {res['fds']} | {p} "
                f"| {row['3nf']['hmax']:.1f} | {row['so']['hmax']:.1f} | **{row['ha']['hmax']:.1f}** "
                f"| {row['so']['crit']:.1f} | {row['ha']['crit']:.1f} "
                f"| {row['so']['size']:.1f} | {row['ha']['size']:.1f} |")
    open(os.path.join(HERE, "rq2-draft.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

def main():
    jobs = []
    for sem, folder in SEMS.items():
        fdir = os.path.join(BASE, folder, "FD")
        for f in sorted(os.listdir(fdir)):
            if f.endswith(".json"):
                path = os.path.join(fdir, f)
                jobs.append((atomic_count(path), f[:-5], sem, path))
    jobs.sort()
    out, skipped = {}, []
    for n_atomic, ds, sem, path in jobs:
        tag = f"{ds}:{sem}"
        if n_atomic > CAP:
            skipped.append(f"{tag}({n_atomic})")
            print(f"SKIP {tag} atomic={n_atomic} > {CAP}", flush=True)
            continue
        t0 = time.perf_counter()
        try:
            res = run_one(path)
        except Exception as e:
            print(f"FAIL {tag}: {e}", flush=True)
            continue
        out[tag] = res
        json.dump({"_skipped": skipped, **out},
                  open(os.path.join(HERE, "rq2_draft.json"), "w"), indent=1)
        print(f"{ds:14s} {sem}  R={res['R']:3d} |A|={res['fds']:6d} keys={res['keys']:4d}"
              f"  ({time.perf_counter()-t0:6.1f}s)", flush=True)
        for p, row in res["ps"].items():
            cells = "  ".join(
                f"{m[:4]}: hmax={row[m]['hmax']:6.1f} crit={row[m]['crit']:5.1f}" for m in MODES)
            print(f"    p={p}: {cells}", flush=True)
    write_md(out, skipped)
    print(f"\nwrote rq2_draft.json / rq2-draft.md  ({len(out)} runs, {len(skipped)} skipped)")

if __name__ == "__main__":
    main()
