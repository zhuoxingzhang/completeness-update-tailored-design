"""Full end-to-end run of ONE declared weather rule (Figure 7, RQ6).

weather_rules.py materializes only the host subschemata, which is exact for
the refresh channel but blind to storage, lookups, reconstruction and the
completion stream.  This script materializes all three designs in full
(1186 / 1217 / 1218 subschemata on china_weather:nulluc) and runs the whole
workload against them.

The declared rule defaults to the one on which the counting census
(weather_census.py) predicts the widest gap.  That is a deliberate deep dive,
not a draw: the selection-free claim is the census, and this run prices its
head in live SQL.

Usage: python weather_full.py [<rule>]        rule = "x,y->a", default "2,16->5"
Writes full_<dataset>_<sem>.json next to this script.
"""
import sys, os, json, time, collections, random
import statistics as st
from weather_common import *

DS, SEM = "china_weather", "nulluc"
RULE_X, RULE_A = parse_rule(sys.argv[1]) if len(sys.argv) > 1 else ((2, 16), 5)
NGROUP = 20                          # groups refreshed per pass
NCOMPL = 200                         # completion events
CMAX_X = 5                           # determinant cap for completion rules
REPS = 15
DB = "weather_full"
OUT = os.path.join(HERE, f"full_{DS}_{SEM}.json")

data, E, Eset, scope, reduct, keys, prep = load(DS, SEM)
m = len(data[0])
seed = find_rule(reduct, RULE_X, RULE_A)
X, A = sorted(seed[0]), RULE_A
lbl = rule_label(seed)
th = {fd: (10 if fd == seed else 1) for fd in reduct}

grp = collections.defaultdict(list)
for r in scope:
    grp[tuple(r[a] for a in X)].append(r)
sz = sorted((len(v) for v in grp.values()), reverse=True)
print(f"declared hot rule {lbl}: groups={len(grp)} gmax={sz[0]} gmean={sum(sz)/len(sz):.1f}", flush=True)

t0 = time.time()
Ds = {k: B.synthesize(Eset, reduct, keys, MODE_OF[k], hot=th, prep=prep) for k in ORDER0}
mets = {k: B.decomp_metrics(Ds[k], th) for k in ORDER0}
print("designs |D| " + "/".join(f"{k}={len(Ds[k])}" for k in ORDER0)
      + "  hmax " + "/".join(f"{k}={mets[k]['hmax']:.0f}" for k in ORDER0)
      + f"  ({time.time()-t0:.0f}s)", flush=True)

# ---- refresh workload -----------------------------------------------------
# A refresh carries a fresh right-hand side value, so rewriting a whole group
# cannot collide with a hosting key; the completion path can, so its receiving
# groups are screened against every hosting key of every design.
rnd = random.Random(20260830)
big = sorted(grp.items(), key=lambda kv: -len(kv[1]))[:NGROUP]
wl = [(seed, xv, rows_g[0][A], f"z{j}") for j, (xv, rows_g) in enumerate(big)]
refresh_scope_tuples = sum(len(rows_g) for _, rows_g in big)

# ---- completion stream ----------------------------------------------------
# A pending row is one value short of E-completeness and completes into the
# rules whose right-hand side is its missing attribute.  Rules whose group does
# not pre-exist are dropped from the event, which changes nothing (the batch
# skips them) but keeps the per-event work proportional to the repairs done.
miss = collections.Counter()
for r in data:
    gap = [a for a in E if r[a] is None]
    if len(gap) == 1:
        miss[gap[0]] += 1
crules = collections.defaultdict(list)
for fd in reduct:
    a = next(iter(fd[1]))
    if a in miss and len(fd[0]) <= CMAX_X:
        crules[a].append(fd)
print("completion rules: " + ", ".join(f"a{a}:{len(crules[a])} rules/{miss[a]} pending"
                                       for a in sorted(crules)), flush=True)

cgrp, cakeys = {}, {}


def cg(fd):
    Xf = tuple(sorted(fd[0]))
    if Xf not in cgrp:
        g = collections.defaultdict(list)
        for r in scope:
            g[tuple(r[a] for a in Xf)].append(r)
        cgrp[Xf] = g
    return cgrp[Xf]


def csafe(fd, rows_g):
    if fd not in cakeys:
        Xf, Af = set(fd[0]), next(iter(fd[1]))
        ks = []
        for k in ORDER0:
            for XA, proj in Ds[k]:
                if Xf <= XA and Af in XA:
                    ks += [sorted(kk - {Af}) for kk in B.minimal_keys(XA, proj) if Af in kk]
        cakeys[fd] = ks
    for Krest in cakeys[fd]:
        seen = set()
        for r in rows_g:
            t = tuple(r[c] for c in Krest)
            if t in seen:
                return False
            seen.add(t)
    return True


pend, n_considered = [], 0
for r in data:
    gap = [a for a in E if r[a] is None]
    if len(gap) != 1 or gap[0] not in crules:
        continue
    Ac = gap[0]
    rules, ok = [], True
    for fd in crules[Ac]:
        xv = tuple(r[a] for a in sorted(fd[0]))
        if xv not in cg(fd):
            continue                      # no pre-existing group: nothing to repair
        if not csafe(fd, cg(fd)[xv]):
            ok = False
            break
        rules.append((fd, xv, True))
    if not ok:
        continue
    n_considered += 1
    nv = "zc%d" % len(pend)
    pend.append((rules, nv, tuple(nv if c == Ac else r[c] for c in range(m))))
rnd.shuffle(pend)
pend = pend[:NCOMPL]
n_join = sum(1 for rules, _, _ in pend if rules)
n_repairs = sum(len(rules) for rules, _, _ in pend)
probes = [rnd.choice(list(grp)) for _ in range(min(1000, len(grp)))]
print(f"workload: refresh {len(wl)} groups covering {refresh_scope_tuples} scope tuples; "
      f"completions {len(pend)} of {n_considered} eligible ({n_join} carry a repair, "
      f"{n_repairs} repairs total); lookups {len(probes)}", flush=True)

lens = RW.col_lens(data, m)
conn, cur = open_db(DB)
drop_all(cur, DB)

res = {"dataset": f"{DS}:{SEM}", "rows": len(data), "E": len(E), "scope": len(scope),
       "reduct": len(reduct), "keys": len(keys), "rule": lbl, "groups": len(grp), "gmax": sz[0],
       "gmean": round(sum(sz) / len(sz), 1), "refresh_groups": len(wl),
       "refresh_scope_tuples": refresh_scope_tuples, "completions": len(pend),
       "compl_with_repair": n_join, "compl_repairs": n_repairs, "designs": {}}


def save():
    json.dump(res, open(OUT, "w"), indent=1)


RW.Q1R = 1                       # one timed reconstruction per design
metas, anchors = {}, {}
for k in ORDER0:
    D = Ds[k]
    t0 = time.time()
    meta = RW.materialize(cur, f"d{k.lower()}", D, th, scope, lens)
    metas[k] = meta
    build = time.time() - t0
    hosts = RW.hosts_of(meta, seed)
    nonkey_hosts = sum(1 for _, nk in hosts if nk)
    # exact stored rows one refresh pass rewrites, summed over hosting subschemata
    stored = 0
    cond = " AND ".join(f"c{a}=%s" for a in X)
    for hm, _ in hosts:
        for _, xv, _, _ in wl:
            cur.execute(f"SELECT COUNT(*) FROM {hm['tbl']} WHERE {cond}", xv)
            stored += cur.fetchone()[0]
    RW.settle(cur)
    r_ms, _ = RW.refresh_batch(cur, meta, wl, reps=1)
    q2, q2_reps = RW.hot_lookups(cur, meta, seed, probes)
    cur.execute("SELECT SUM(data_length+index_length) FROM information_schema.tables"
                " WHERE table_schema=%s AND table_name LIKE %s", (DB, f"d{k.lower()}_%"))
    mb = round(float(cur.fetchone()[0] or 0) / 2 ** 20, 1)
    res["designs"][k] = {"size": len(D), "hmax": mets[k]["hmax"], "hosts": len(hosts),
                         "nonkey_hosts": nonkey_hosts, "rewritten_rows": stored,
                         "build_s": round(build, 1), "first_refresh_ms": r_ms,
                         "lookup_ms": q2, "lookup_reps": q2_reps, "storage_mb": mb}
    save()
    print(f"  {k:3s} |D|={len(D):5d} h={mets[k]['hmax']:5.1f} hosts={len(hosts):3d} "
          f"(nonkey {nonkey_hosts}) rows={stored:7d} build={build:6.0f}s "
          f"refresh1={r_ms:9.1f}ms look={q2:7.4f}ms {mb}MB", flush=True)
    # reconstruction is read-only, so it cannot disturb the interleaved refresh
    t0 = time.time()
    anchor, q1, q1n, q1_reps = RW.query_pass(cur, meta, sorted(E), len(scope), start_tbl=hosts[0][0]["tbl"])
    anchors[k] = tuple(anchor) if anchor else None
    res["designs"][k].update({"recon_s": q1, "recon_tables": q1n, "recon_reps": q1_reps,
                              "recon_wall_s": round(time.time() - t0, 1),
                              "recon_anchor": list(anchor) if anchor else None})
    save()
    print(f"      recon {'dnf' if q1 is None else f'{q1}s'} over {q1n} tables "
          f"(wall {time.time()-t0:.0f}s)", flush=True)

res["recon_anchors_agree"] = len({a for a in anchors.values() if a}) <= 1
save()

# ---- interleaved refresh: the authoritative number -------------------------
RW.settle(cur)
inter = {k: [] for k in ORDER0}
for r_i in range(REPS + 1):
    o = ORDER0[r_i % 3:] + ORDER0[:r_i % 3]
    for k in o:
        ms, _ = RW.refresh_batch(cur, metas[k], wl, reps=1)
        if r_i:
            inter[k].append(ms)
    if r_i:
        print(f"   round {r_i:2d} " + "  ".join(f"{k}={inter[k][-1]:9.1f}" for k in ORDER0), flush=True)
med = {k: st.median(v) for k, v in inter.items()}
for k in ORDER0:
    res["designs"][k]["refresh_ms"] = med[k]
    res["designs"][k]["refresh_reps"] = inter[k]
res["refresh_so_over_ha"] = round(med["SO"] / max(med["HA"], 1e-9), 2)
save()
print("interleaved refresh medians " + " / ".join(f"{k}={med[k]:.1f}" for k in ORDER0)
      + f"  SO/HA={res['refresh_so_over_ha']}x", flush=True)

# ---- completions ----------------------------------------------------------
for k in ORDER0:
    RW.settle(cur)
    c_ms = RW.completion_batch(cur, metas[k], pend)
    res["designs"][k]["completion_ms"] = c_ms
    save()
    print(f"  {k:3s} completions {c_ms:10.1f}ms", flush=True)

conn.close()
print("done", flush=True)
