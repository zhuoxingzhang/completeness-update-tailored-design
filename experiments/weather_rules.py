"""Live runs of the refresh workload on declared weather rules (RQ6).

Each rule named on the command line is declared hot in turn (heat 10, every
other rule of the reduct at 1), the three designs are synthesized, and the
subschemata that store the rule are materialized in MySQL.  A refresh of X->A
writes no other subschema, so materializing the hosts is exactly equivalent
for this measurement and is what makes a run over designs of more than
1000 subschemata affordable; storage, lookups, reconstruction and completions
need the full materialization of weather_full.py.

3NF and SO are heat-independent, so their designs are the same for every rule.
When SO and HA return the same design the run is a tie by construction and
is reported without materialization.  Timing is the interleaved round-robin of
real_workload: 15 rounds after a warm-up round, the visiting order rotated.

Usage: python weather_rules.py <dataset> <sem> <groups> <rule> [<rule> ...]
       rule = "x,y->a" with attribute indices, e.g. "2,16->5"
       "census" in place of the rules runs every rule of the census
Writes rules_<dataset>_<sem>.json next to this script (resumable).
"""
import sys, os, json, time, collections
import statistics as st
from weather_common import *

DS, SEM, NGROUP = sys.argv[1], sys.argv[2], int(sys.argv[3])
RULES = sys.argv[4:]
REPS = 15
DB = "weather_rules"
OUT = os.path.join(HERE, f"rules_{DS}_{SEM}.json")

data, E, Eset, scope, reduct, keys, prep = load(DS, SEM)
m = len(data[0])

groups = {}
def gof(fd):
    X = tuple(sorted(fd[0]))
    if X not in groups:
        g = collections.defaultdict(list)
        for r in scope:
            g[tuple(r[a] for a in X)].append(r)
        groups[X] = g
    return groups[X]

if RULES == ["census"]:
    seeds = []
    for fd in reduct:
        X = tuple(sorted(fd[0]))
        if not (1 <= len(X) <= 4):
            continue
        g = gof(fd)
        if len(g) < 2:
            continue
        sz = sorted((len(v) for v in g.values()), reverse=True)
        if sum(sz) / len(sz) >= 3:
            seeds.append((sum(sz) / len(sz), fd))
    seeds.sort(reverse=True, key=lambda t: t[0])
    seeds = [fd for _, fd in seeds]
else:
    seeds = []
    for s in RULES:
        X, A = parse_rule(s)
        try:
            seeds.append(find_rule(reduct, X, A))
        except StopIteration:
            print(f"rule {s} is not in the reduct; skipped", flush=True)

lens = RW.col_lens(data, m)
conn, cur = open_db(DB)
FIXED = {}
out = json.load(open(OUT)) if os.path.exists(OUT) else []
done = {o["rule"] for o in out}
for i, seed in enumerate(seeds):
    th = {fd: (10 if fd == seed else 1) for fd in reduct}
    lbl = rule_label(seed)
    if lbl in done:
        print(f"{lbl} already measured; skipped", flush=True)
        continue
    order = ORDER0[i % 3:] + ORDER0[:i % 3]
    for k in ("3NF", "SO"):
        if k not in FIXED:
            FIXED[k] = B.synthesize(Eset, reduct, keys, MODE_OF[k], hot=th, prep=prep)
    Ds = dict(FIXED)
    Ds["HA"] = B.synthesize(Eset, reduct, keys, MODE_OF["HA"], hot=th, prep=prep)
    sizes = {k: len(Ds[k]) for k in ORDER0}
    hmax = {k: B.decomp_metrics(Ds[k], th)["hmax"] for k in ORDER0}
    sig = {k: tuple(sorted(tuple(sorted(S)) for S, _ in Ds[k])) for k in ORDER0}
    g = gof(seed)
    sz = sorted((len(v) for v in g.values()), reverse=True)
    if sig["SO"] == sig["HA"]:
        print(f"{lbl:20s} |D| {sizes['3NF']}/{sizes['SO']}/{sizes['HA']} | SO design == HA design "
              f"-> structural tie, not materialized", flush=True)
        out.append({"rule": lbl, "groups": len(g), "gmax": sz[0], "gmean": round(sum(sz) / len(sz), 2),
                    "sizes": sizes, "hmax": hmax, "structural_tie": True})
        json.dump(out, open(OUT, "w"), indent=1)
        continue
    XA = set(seed[0]) | set(seed[1])
    Dh = {k: [(S, p) for S, p in Ds[k] if XA <= set(S)] for k in ORDER0}
    if not all(Dh[k] for k in ORDER0):
        print(f"{lbl:20s} no host in some design -> skipped", flush=True)
        continue
    drop_all(cur, DB)
    metas = {}
    tb = time.time()
    for k in order:
        metas[k] = RW.materialize(cur, f"d{k.lower()}", Dh[k], th, scope, lens)
    RW.settle(cur)
    tbuild = time.time() - tb
    X, A = sorted(seed[0]), next(iter(seed[1]))
    big = sorted(g.items(), key=lambda kv: -len(kv[1]))[:NGROUP]
    wl = [(seed, xv, rows_g[0][A], f"z{j}") for j, (xv, rows_g) in enumerate(big)]
    # stored rows one refresh pass rewrites per design, from the materialized tables
    rewritten = {}
    cond = " AND ".join(f"c{a}=%s" for a in X)
    for k in ORDER0:
        n = 0
        for hm, _ in RW.hosts_of(metas[k], seed):
            for _, xv, _, _ in wl:
                cur.execute(f"SELECT COUNT(*) FROM {hm['tbl']} WHERE {cond}", tuple(xv))
                n += cur.fetchone()[0]
        rewritten[k] = n
    inter = {k: [] for k in ORDER0}
    for r_i in range(REPS + 1):
        o = ORDER0[r_i % 3:] + ORDER0[:r_i % 3]
        for k in o:
            ms, _ = RW.refresh_batch(cur, metas[k], wl, reps=1)
            if r_i:
                inter[k].append(ms)
    med = {k: st.median(v) for k, v in inter.items()}
    hosts = {k: len(RW.hosts_of(metas[k], seed)) for k in ORDER0}
    print(f"{lbl:20s} grp={len(g):6d} gmax={sz[0]:6d} gmean={sum(sz)/len(sz):8.1f} | "
          f"|D| {sizes['3NF']}/{sizes['SO']}/{sizes['HA']} | hmax {hmax['3NF']}/{hmax['SO']}/{hmax['HA']} | "
          f"hosts {hosts['3NF']}/{hosts['SO']}/{hosts['HA']} | "
          f"rows {rewritten['3NF']}/{rewritten['SO']}/{rewritten['HA']} | "
          f"ms {med['3NF']:9.1f}/{med['SO']:9.1f}/{med['HA']:9.1f} | "
          f"SO/HA={med['SO']/max(med['HA'],1e-9):6.2f}x 3NF/HA={med['3NF']/max(med['HA'],1e-9):6.2f}x  "
          f"build={tbuild:.0f}s total={time.time()-tb:.0f}s", flush=True)
    out.append({"rule": lbl, "groups": len(g), "gmax": sz[0], "gmean": round(sum(sz) / len(sz), 2),
                "build_order": order, "sizes": sizes, "hmax": hmax, "hosts": hosts,
                "structural_tie": False, "hosts_only": True, "ngroups": NGROUP,
                "refresh_scope_tuples": sum(len(rows_g) for _, rows_g in big),
                "rewritten_rows": rewritten, "median_ms": med, "reps": inter, "build_s": round(tbuild, 1)})
    json.dump(out, open(OUT, "w"), indent=1)
conn.close()
print("done", flush=True)
