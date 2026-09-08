"""Rows one refresh of the deepest groups rewrites, counted offline (Table 5, RQ6).

For each rule that weather_rules.py runs live, the stored rows a refresh of the
NGROUP deepest groups rewrites are counted on the subschemata that store the
rule, as deduplicated projections of the scope, on all three designs.  The count
equals the rows the MySQL tables hold for those groups, so it needs no database
and fills the rows column of Table 5 for the runs that timed the refresh only.

Usage: python weather_rows.py <dataset> <sem> <groups> <rule> [<rule> ...]
       rule = "x,y->a" with benchmark attribute indices, e.g. "2,16->5"
Writes results/rq6_weather_rows.json.
"""
import sys, os, json, collections
from weather_common import load, MODE_OF, ORDER0, parse_rule, find_rule, rule_label
import config
import synthesis as B

DS, SEM, NGROUP = sys.argv[1], sys.argv[2], int(sys.argv[3])
RULES = sys.argv[4:]
OUT = os.path.join(config.RESULTS, "rq6_weather_rows.json")

data, E, Eset, scope, reduct, keys, prep = load(DS, SEM)
FIXED = {}
out = []
for s in RULES:
    X, A = parse_rule(s)
    seed = find_rule(reduct, X, A)
    th = {fd: (10 if fd == seed else 1) for fd in reduct}
    for k in ("3NF", "SO"):                 # heat-independent, built once
        if k not in FIXED:
            FIXED[k] = B.synthesize(Eset, reduct, keys, MODE_OF[k], hot=th, prep=prep)
    Ds = dict(FIXED)
    Ds["HA"] = B.synthesize(Eset, reduct, keys, MODE_OF["HA"], hot=th, prep=prep)
    XA = set(seed[0]) | set(seed[1])
    g = collections.defaultdict(list)
    for r in scope:
        g[tuple(r[a] for a in X)].append(r)
    big = sorted(g.items(), key=lambda kv: -len(kv[1]))[:NGROUP]
    rec = {"rule": rule_label(seed), "groups": len(g), "gmax": len(big[0][1]),
           "scope_tuples": sum(len(v) for _, v in big), "hosts": {}, "rows": {}}
    for k in ORDER0:
        hosts = [S for S, _ in Ds[k] if XA <= set(S)]
        n = 0
        for S in hosts:
            cols = sorted(S)
            for _, rows_g in big:
                n += len({tuple(r[c] for c in cols) for r in rows_g})
        rec["hosts"][k] = len(hosts)
        rec["rows"][k] = n
    h, w = rec["hosts"], rec["rows"]
    print(f"{rec['rule']:16s} hosts {h['3NF']}/{h['SO']}/{h['HA']} | "
          f"rows {w['3NF']}/{w['SO']}/{w['HA']} | "
          f"3NF/HA={w['3NF']/w['HA']:.2f} SO/HA={w['SO']/w['HA']:.2f}", flush=True)
    out.append(rec)
    json.dump(out, open(OUT, "w"), indent=1)
