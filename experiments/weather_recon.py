"""Reconstruction re-measurement on the designs weather_full.py left in place.

The main run may leave a reconstruction cell empty: the join of more than a
thousand subschemata trips the intermediate-growth guard when it starts at a
narrow key subschema.  The tables are still in place after weather_full.py, so
this re-measures all three designs against the same post-completion content,
trying several start tables per design and reporting the first that completes.

No table is created or dropped here beyond the join's own scratch tables.

Usage: python weather_recon.py [<rule>]       the rule weather_full.py was run with
Writes recon_<dataset>_<sem>.json next to this script.
"""
import sys, os, json, time
from weather_common import *

DS, SEM = "china_weather", "nulluc"
RULE_X, RULE_A = parse_rule(sys.argv[1]) if len(sys.argv) > 1 else ((2, 16), 5)
DB = "weather_full"
OUT = os.path.join(HERE, f"recon_{DS}_{SEM}.json")

data, E, Eset, scope, reduct, keys, prep = load(DS, SEM)
seed = find_rule(reduct, RULE_X, RULE_A)
th = {fd: (10 if fd == seed else 1) for fd in reduct}
Ds = {k: B.synthesize(Eset, reduct, keys, MODE_OF[k], hot=th, prep=prep) for k in ORDER0}
print("designs " + "/".join(f"{k}={len(Ds[k])}" for k in ORDER0), flush=True)

conn = config.connect(DB, autocommit=True)
cur = conn.cursor()

# Rebuild the meta structures without touching the tables: materialize names
# table i of design k as d<k>_s<i> over the i-th subschema, and synthesis is
# deterministic, so the i-th entry of Ds[k] is exactly that table.
metas = {}
for k in ORDER0:
    meta = []
    for i, (XA, proj) in enumerate(Ds[k]):
        tbl = f"d{k.lower()}_s{i}"
        mkeys = B.minimal_keys(XA, proj)
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        meta.append({"tbl": tbl, "cols": sorted(XA), "keys": mkeys,
                     "F": B.schema_nonkey(XA, proj, mkeys, th), "nrows": cur.fetchone()[0]})
    metas[k] = meta
    print(f"  {k:3s} meta rebuilt: {len(meta)} tables, {sum(mm['nrows'] for mm in meta)} stored rows", flush=True)

nscope = max(mm["nrows"] for mm in metas["3NF"])
RW.Q1R = 1                      # one timed run per start table
res = {}


def candidates(k):
    """Start tables to try, in order: the hot rule's host (what the main run
    used), then the widest subschema, then the one with the most rows."""
    meta = metas[k]
    out = []
    h = RW.hosts_of(meta, seed)
    if h:
        out.append(("hot host", h[0][0]["tbl"]))
    out.append(("widest", max(meta, key=lambda mm: len(mm["cols"]))["tbl"]))
    out.append(("most rows", max(meta, key=lambda mm: mm["nrows"])["tbl"]))
    seen, uniq = set(), []
    for why, t in out:
        if t not in seen:
            seen.add(t)
            uniq.append((why, t))
    return uniq


for k in ORDER0:
    res[k] = {"size": len(Ds[k]), "attempts": []}
    for why, tbl in candidates(k):
        print(f"  {k:3s} start={tbl} ({why}) ...", flush=True)
        t0 = time.time()
        anchor, q1, q1n, q1_reps = RW.query_pass(cur, metas[k], sorted(E), nscope, start_tbl=tbl)
        wall = round(time.time() - t0, 1)
        res[k]["attempts"].append({"start": tbl, "why": why, "recon_s": q1, "tables": q1n,
                                   "wall_s": wall, "anchor": list(anchor) if anchor else None})
        json.dump(res, open(OUT, "w"), indent=1)
        print(f"      {'dnf' if q1 is None else str(q1)+'s'} over {q1n} tables (wall {wall}s)", flush=True)
        if q1 is not None:
            res[k]["recon_s"] = q1
            res[k]["recon_start"] = tbl
            res[k]["anchor"] = list(anchor)
            break
    json.dump(res, open(OUT, "w"), indent=1)

good = {k: tuple(v["anchor"]) for k, v in res.items() if v.get("anchor")}
res["anchors_agree"] = len(set(good.values())) <= 1
res["anchors"] = {k: list(v) for k, v in good.items()}
json.dump(res, open(OUT, "w"), indent=1)
print("anchors:", good, "agree:", res["anchors_agree"], flush=True)
conn.close()
print("done", flush=True)
