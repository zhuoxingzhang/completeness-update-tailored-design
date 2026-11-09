r"""Which rules each design of the release window stores as non-key FDs, with their heat and group depth.

The designs are rebuilt exactly as release_live.py builds them, from the reduct in the order the
constraint file lists it, so the rules listed are the ones the run pays for.  For each design: every
non-key atomic FD with its heat, mined before the release, the subschema storing it, and the
mean size of its determinant's groups over the scope; and for each priced attribute, how many
subschemata store it and in how many of them it is the right-hand side of a non-key FD.  The
heat of each design in Table 7 of the paper is read from this record, since it rebuilds the
designs under the heat convention in force (release_cost.HEAT_FLOOR).  Offline, no MySQL.

Usage: python release_rules.py [<tag>]          default owid
Environment: SLICE as in release_cost.py
Writes results/rq7_real_rules.json
"""
import collections
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import synthesis as B

B.HEAT = "all"
import release_cost as W

TAG = sys.argv[1] if len(sys.argv) > 1 else "owid"
ORDER = ["3NF", "SO", "HA"]
MODE_OF = {"3NF": "3nf", "SO": "so", "HA": "ha"}

R = W.Rel(TAG)
plan = W.coalesce(R)
theta = W.declare(R)
prep = B.prepare(R.reduct)
priced = {a for a, p in plan.items() if p["X"]}
depth_memo = {}


def depth(X):
    if X not in depth_memo:
        depth_memo[X] = R.n / len(np.unique(R.gid(X)))
    return depth_memo[X]


res = {"tag": TAG, "reduct": [[sorted(l), sorted(r)] for l, r in R.reduct],
       "designs": {},
       "priced_attrs": {R.attrs[a]: {"refreshes": int(plan[a]["events"]), "updates": int(plan[a]["updates"])}
                        for a in sorted(priced)},
       "declared": {R.attrs[a]: h for a, h in sorted({next(iter(fd[1])): h for fd, h in theta.items()}.items())}}
print("heat mined before the release, by attribute: "
      + ", ".join(f"{a} {h:,}" for a, h in res["declared"].items()))
for k in ORDER:
    D = B.synthesize(R.E, R.reduct, R.keys, MODE_OF[k], hot=theta, prep=prep)
    met = B.decomp_metrics(D, theta)
    hot_nonkey, stored, as_nonkey = [], collections.Counter(), collections.Counter()
    for i, (XA, proj) in enumerate(D):
        for a in XA:
            if a in priced:
                stored[R.attrs[a]] += 1
        for fd in B.schema_nonkey(XA, proj, B.minimal_keys(XA, proj), theta):
            a = next(iter(fd[1]))
            if a in priced:
                as_nonkey[R.attrs[a]] += 1
            h = B.fd_hot(fd, theta)
            if h <= 0:
                continue
            X = tuple(sorted(fd[0]))
            hot_nonkey.append({"subschema": i, "schema": [R.attrs[x] for x in sorted(XA)],
                               "lhs": [R.attrs[x] for x in X], "rhs": R.attrs[a], "heat": h,
                               "mean_group": round(depth(X), 1)})
    hot_nonkey.sort(key=lambda r: (-r["heat"], r["rhs"], r["lhs"], r["subschema"]))
    assert sum(r["heat"] for r in hot_nonkey) == met["htot"], f"{k}: the rules do not add up to the total heat"
    rules = collections.Counter((tuple(r["lhs"]), r["rhs"], r["heat"], r["mean_group"]) for r in hot_nonkey)
    ranked = sorted(rules.items(), key=lambda kv: (-kv[0][2], -kv[1], kv[0][0]))
    res["designs"][k] = {"size": len(D), "hmax": met["hmax"],
                         "htot": met["htot"], "hot_nonkey": hot_nonkey,
                         "rules": [{"lhs": list(l), "rhs": a, "heat": h, "mean_group": g, "subschemata": n}
                                   for (l, a, h, g), n in ranked],
                         "stored": dict(stored), "as_nonkey": dict(as_nonkey)}
    print(f"\n{k}: |D| {len(D)}, hmax {met['hmax']:,}, htot {met['htot']:,}")
    for (l, a, h, g), n in ranked:
        print(f"   {{{','.join(l)}}} -> {a}: heat {h:,} in {n} subschemata, mean group {g}")
    print("   priced attributes, subschemata storing it / storing it as a non-key right-hand side:")
    for a in sorted(stored, key=lambda x: -stored[x]):
        print(f"     {a:32s} {stored[a]:4d} / {as_nonkey.get(a, 0)}")

out = os.environ.get("OUT", os.path.join(CFG.RESULTS, "rq7_real_rules.json"))
json.dump(res, open(out, "w"), indent=1)
print(f"\nwritten {out}")
