"""Single-hot-rule sweep over every RQ2 reduct: for each atomic rule, declare
it the sole hot rule (theta 10 vs 1) and ask whether heat-aware synthesis can
land strictly below the structure-optimal design.

Pruning: 3NF and SO are frequency-blind, so their designs are synthesized once
(uniform heat); under a single-hot theta only tables containing the hot rule
can change their heat, so the swept SO hmax is recomputed
incrementally per rule.  Rules that lift the SO hmax above its uniform level
are candidates; only candidates trigger a fresh SO and HA synthesis (the SO
resynthesis guards against theta-dependent tie-breaking).
Results -> sweep_skew.json (incremental).
"""
import sys, os, json, time

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B

BASE = config.FD_BASE
SEMS = config.SEMS
CAP = 10_000
RESYNTH_CAP = 300
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sweep_skew.json")


def table_heat(XA, proj, mkeys, theta):
    F = B.schema_nonkey(XA, proj, mkeys, theta)
    return sum(theta[f] for f in F) if F else 0


def sweep(tag, path):
    R, sigma, keys = B.load(path)
    prep = B.prepare(sigma)
    ones = {fd: 1 for fd in sigma}
    D_so = B.synthesize(R, sigma, keys, "so", hot=ones, prep=prep)
    tables = []
    for XA, proj in D_so:
        mkeys = B.minimal_keys(XA, proj)
        tables.append((XA, proj, mkeys, table_heat(XA, proj, mkeys, ones)))
    base = max((h for *_, h in tables), default=0)

    cands = []
    for fd in sigma:
        X, A = fd[0], next(iter(fd[1]))
        theta = dict(ones); theta[fd] = 10
        hot_h = base
        for XA, proj, mkeys, h0 in tables:
            if X <= XA and A in XA:
                hot_h = max(hot_h, table_heat(XA, proj, mkeys, theta))
        if hot_h > base:
            cands.append((hot_h, fd))
    cands.sort(key=lambda t: -t[0])
    capped = len(cands) > RESYNTH_CAP
    n_sep, best = 0, None
    for est, fd in cands[:RESYNTH_CAP]:
        theta = dict(ones); theta[fd] = 10
        hso = B.decomp_metrics(B.synthesize(R, sigma, keys, "so", hot=theta, prep=prep), theta)["hmax"]
        hha = B.decomp_metrics(B.synthesize(R, sigma, keys, "ha", hot=theta, prep=prep), theta)["hmax"]
        if hha < hso:
            n_sep += 1
            if best is None or hso - hha > best["so"] - best["ha"]:
                h3 = B.decomp_metrics(B.synthesize(R, sigma, keys, "3nf", hot=theta, prep=prep), theta)["hmax"]
                best = {"rule": f"{sorted(fd[0])}->{next(iter(fd[1]))}",
                        "3nf": h3, "so": hso, "ha": hha}
    return {"rules": len(sigma), "candidates": len(cands), "capped": capped,
            "separations": n_sep, "best": best, "so_uniform_hmax": base}


def main():
    jobs = []
    for sem, folder in SEMS.items():
        fdir = os.path.join(BASE, folder, "FD")
        for f in sorted(os.listdir(fdir)):
            if f.endswith(".json"):
                path = os.path.join(fdir, f)
                d = json.load(open(path, encoding="utf-8"))
                n = sum(len(fd["rhs"]) for fd in d["fds"])
                jobs.append((n, f[:-5], sem, path))
    jobs.sort()
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for n, ds, sem, path in jobs:
        tag = f"{ds}:{sem}"
        if n > CAP:
            continue
        if tag in out:
            print("done already:", tag, flush=True)
            continue
        t0 = time.perf_counter()
        try:
            out[tag] = sweep(tag, path)
        except Exception as e:
            import traceback; traceback.print_exc()
            out[tag] = {"skip": str(e)}
        json.dump(out, open(OUT, "w"), indent=1)
        r = out[tag]
        if "skip" not in r:
            print(f"{tag:44s} |A|={r['rules']:5d} cand={r['candidates']:4d}"
                  f"{'^' if r['capped'] else ' '} sep={r['separations']:4d} "
                  f"best={r['best']}  ({time.perf_counter()-t0:.1f}s)", flush=True)
    print("wrote sweep_skew.json", flush=True)


if __name__ == "__main__":
    main()
