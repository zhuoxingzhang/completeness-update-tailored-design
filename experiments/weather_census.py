"""The selection-free census behind Figure 6 (RQ6): counting only, no MySQL.

Every rule of the reduct with at most four determinant attributes whose groups
average at least three scope tuples is declared hot in turn, and for each we
count the stored rows one refresh of its worst (and its mean) group rewrites,
summed over the hosting subschemata, on all three designs.  Nothing is selected
for being favourable to any design.

Usage: python weather_census.py [<dataset> [<sem>]]      default china_weather nulluc
Writes census_<dataset>_<sem>.json next to this script.
"""
import sys, os, json, collections
from weather_common import *

DS = sys.argv[1] if len(sys.argv) > 1 else "china_weather"
SEM = sys.argv[2] if len(sys.argv) > 2 else "nulluc"
OUT = os.path.join(HERE, f"census_{DS}_{SEM}.json")

data, E, Eset, scope, reduct, keys, prep = load(DS, SEM)


def gstat(X):
    g = collections.Counter(tuple(r[a] for a in X) for r in scope)
    s = sorted(g.values(), reverse=True)
    return len(g), s[0], sum(s) / len(s)


def refresh(D, seed):
    """Rows one refresh rewrites, summed over hosting subschemata: worst group,
    mean group, host count, and how many hosts keep the determinant non-key."""
    X, XA = sorted(seed[0]), seed[0] | seed[1]
    worst = mean = 0.0
    nhost = nonkey = 0
    for S, proj in D:
        if not XA <= S:
            continue
        nhost += 1
        mk = B.minimal_keys(S, proj)
        if not any(set(k) <= set(X) for k in mk):
            nonkey += 1
        cols = sorted(S)
        seen = collections.defaultdict(set)
        for r in scope:
            seen[tuple(r[a] for a in X)].add(tuple(r[c] for c in cols))
        sz = [len(v) for v in seen.values()]
        worst += max(sz)
        mean += sum(sz) / len(sz)
    return worst, mean, nhost, nonkey


seeds = []
for fd in reduct:
    X = tuple(sorted(fd[0]))
    if not (1 <= len(X) <= 4):
        continue
    ng, gmax, gmean = gstat(X)
    if gmean >= 3:
        seeds.append((gmean, gmax, ng, fd))
seeds.sort(reverse=True, key=lambda t: t[0])
print(f"census: {len(seeds)} rules with mean group >= 3", flush=True)

out = []
for gmean, gmax, ng, seed in seeds:
    th = {fd: (10 if fd == seed else 1) for fd in reduct}
    rec = {"rule": rule_label(seed), "groups": ng, "gmax": gmax, "gmean": round(gmean, 2), "designs": {}}
    sig = {}
    for k in ORDER0:
        D = B.synthesize(Eset, reduct, keys, MODE_OF[k], hot=th, prep=prep)
        w, mn, nh, nk = refresh(D, seed)
        rec["designs"][k] = {"size": len(D), "hmax": B.decomp_metrics(D, th)["hmax"],
                             "worst": round(w, 1), "mean": round(mn, 2), "hosts": nh, "nonkey_hosts": nk}
        sig[k] = tuple(sorted(tuple(sorted(S)) for S, _ in D))
    rec["so_ha_same_design"] = sig["SO"] == sig["HA"]
    h = rec["designs"]
    rec["worst_so_over_ha"] = round(h["SO"]["worst"] / max(h["HA"]["worst"], 1e-9), 2)
    rec["worst_3nf_over_ha"] = round(h["3NF"]["worst"] / max(h["HA"]["worst"], 1e-9), 2)
    out.append(rec)
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{rec['rule']:22s} grp={ng:6d} gmax={gmax:6d} | worst 3NF/SO/HA = "
          f"{h['3NF']['worst']:9.0f}/{h['SO']['worst']:9.0f}/{h['HA']['worst']:9.0f} "
          f"| SO/HA={rec['worst_so_over_ha']:8.2f}x | hosts "
          f"{h['3NF']['hosts']}/{h['SO']['hosts']}/{h['HA']['hosts']}"
          f"{'  [SO==HA design]' if rec['so_ha_same_design'] else ''}", flush=True)

n_sep = sum(1 for r in out if r["worst_so_over_ha"] > 1.01)
n_worse = sum(1 for r in out if r["worst_so_over_ha"] < 0.99)
print(f"\ncensus of {len(out)}: HA cooler on {n_sep}, worse on {n_worse}, "
      f"max SO/HA = {max(r['worst_so_over_ha'] for r in out)}", flush=True)
