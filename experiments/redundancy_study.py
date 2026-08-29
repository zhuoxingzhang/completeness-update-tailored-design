"""Instance-level redundancy study on the RQ2 benchmark reducts.

For every (dataset, semantics) run of RQ2:
  1.  Pull the raw incomplete relation (benchmark MySQL variant table, biocase CSV).
  2.  Calibrate the column mapping between the FD JSON (attribute = column index
      at mining time) and the data by requiring every mined FD to HOLD on the
      data under the respective NULL reading; candidate mappings are identity /
      drop-first / drop-last, candidate RHS readings for uncertainty are
      "skip NULL" and "NULL differs from everything".  A run with no surviving
      mapping is reported and skipped.
  3.  Count redundant data value occurrences in the relation (Vincent-style:
      occurrence t[A] such that some implied X->A and a second tuple agreeing
      on X force the value), plus the per-FD counts that rank the atomic FDs.
  4.  Derive a data heat map from the ranking (theta = ceil(10*red/red_max),
      cold 1 when red = 0) and keep the RQ2 graded protocol (p=0.5, seed 0) as
      the synthetic channel.
  5.  Synthesize 3NF / SO / HA under both heat channels, materialize every
      subschema over the data (set projection, DISTINCT with NULLs equal), and
      count the redundant occurrences each design stores, split by the heat
      level of the causing FD (hot = top fifth of the scale, theta >= 8).
  6.  For the HA design, count nullable columns in each subschema's cheapest
      minimal key (certain-key enforcement practicality).

Results are dumped incrementally to redundancy_study.json.
Usage:  python redundancy_study.py [--limit N_ROWS_CAP] [--only ds:sem]
"""
import sys, os, json, csv, time, math, argparse
from collections import defaultdict

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "redundancy_study.json")
FD_BASE = config.FD_BASE
SEMS = config.SEMS
BIOCASE_CSV = _os.environ.get("CUTD_BIOCASE_CSV",
                              _os.path.join(config.REPO, "data", "raw",
                                            "t_biocase_identification_r91800_c38.csv"))
BIOCASE_JSON = "t_biocase_identification_r91800_c38"

# benchmark table base names per FD JSON base name (biocase handled separately)
TABLES = {"routes": "routes", "claims": "claims", "breast": "breast",
          "pdbx": "pdbx", "hospital": "hospital", "bridges": "bridges",
          "echo": "echo", "ncvoter": "ncvoter", "china_weather": "china_weather",
          "dblp10k": "dblp10k", "uniprot": "uniprot", "hepatitis": "hepatitis"}

SCALE = 10        # theta scale, matches baselines.SCALE
TOP = 8           # theta >= TOP counts as "hot" in the split
GRADED_P, GRADED_SEED = 0.5, 0
MODES = ["3nf", "so", "ha"]
NULLTOK_CANDS = [("",), ("", "?"), ("", "?", "NULL")]


# ---------------- data loading ----------------------------------------------
def load_mysql(tbl):
    conn = config.connect(config.MYSQL_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ORDINAL_POSITION",
                (config.MYSQL_DB, tbl))
    cols = [r[0] for r in cur.fetchall()]
    cur.close()
    # stream rows and pool repeated values, so wide tables like pdbx (17M rows)
    # keep one str object per distinct value instead of one per cell
    scur = conn.cursor(pymysql.cursors.SSCursor)
    scur.execute(f"SELECT * FROM `{tbl}`")
    pool, rows = {}, []
    for r in scur:
        rows.append(tuple(None if v is None else pool.setdefault(s, s)
                          for v in r for s in (str(v),)))
    scur.close()
    conn.close()
    return rows, cols


def load_biocase(null_tokens):
    with open(BIOCASE_CSV, encoding="utf-8", errors="replace", newline="") as fh:
        rdr = csv.reader(fh)
        header = next(rdr)
        rows = [tuple(None if v in null_tokens else v for v in r) for r in rdr]
    return rows, header


def mysql_variant(base):
    conn = config.connect(config.MYSQL_DB)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name LIKE %s",
                (config.MYSQL_DB, base + "%"))
    names = {r[0] for r in cur.fetchall()}
    conn.close()
    return names


# ---------------- FD checking / counting ------------------------------------
def fd_groups(rows, lhs, sem):
    """Group row indices by their LHS value tuple under the semantics.
    nulleq: NULL is a value (None participates).  nulluc: rows with a NULL on
    the LHS join no group (NULL agrees with nothing)."""
    g = defaultdict(list)
    if sem == "nulleq":
        for i, r in enumerate(rows):
            g[tuple(r[c] for c in lhs)].append(i)
    else:
        for i, r in enumerate(rows):
            key = tuple(r[c] for c in lhs)
            if None in key:
                continue
            g[key].append(i)
    return g


def violates(rows, fds_multi, mapping, sem, rhs_mode, sample=None):
    """Return the number of violated multi-RHS FDs (early exit at first hit)."""
    data = rows if sample is None else rows[:sample]
    for fd in fds_multi:
        lhs = [mapping[a] for a in fd["lhs"]]
        rhs = [mapping[a] for a in fd["rhs"] if a not in fd["lhs"]]
        if not rhs:
            continue
        for idxs in fd_groups(data, lhs, sem).values():
            if len(idxs) < 2:
                continue
            for c in rhs:
                vals = {data[i][c] for i in idxs}
                if sem == "nulleq":
                    if len(vals) > 1:
                        return 1
                else:
                    nn = vals - {None}
                    if len(nn) > 1:
                        return 1
                    if rhs_mode == "strict" and nn and None in vals:
                        return 1
    return 0


def calibrate(rows, ncols_json, fds_multi, sem):
    """Find (mapping, rhs_mode) making every mined FD hold; None if impossible."""
    ncols = len(rows[0])
    cands = []
    if ncols == ncols_json:
        cands.append(list(range(ncols_json)))
    if ncols == ncols_json + 1:
        cands.append(list(range(1, ncols)))         # drop first data column
        cands.append(list(range(ncols_json)))       # drop last data column
    rhs_modes = ["skip"] if sem == "nulleq" else ["skip", "strict"]
    for mapping in cands:
        for rm in rhs_modes:
            if violates(rows, fds_multi, mapping, sem, rm, sample=20000):
                continue
            if violates(rows, fds_multi, mapping, sem, rm):
                continue
            return mapping, rm
    return None, None


def count_redundancy(rows, atomic, sem, mark=None, theta=None):
    """Count redundant value occurrences caused by the atomic FDs.

    atomic: list of (lhs_tuple, rhs_col) in DATA coordinates.
    Returns (occurrence-level red count, per-fd red dict).  When `mark` is
    given (dict (row,col)->level) it records max theta of a causing FD instead
    of a plain set, using theta[fd] (default 1)."""
    red = {}                                  # (row,col) -> max theta
    fd_red = {}
    by_lhs = defaultdict(list)
    for lhs, a in atomic:
        by_lhs[lhs].append(a)
    for lhs, rhss in by_lhs.items():
        groups = fd_groups(rows, lhs, sem)
        for a in rhss:
            th = 1 if theta is None else theta.get((lhs, a), 1)
            n_red = 0
            for idxs in groups.values():
                if len(idxs) < 2:
                    continue
                seen = defaultdict(list)
                for i in idxs:
                    v = rows[i][a]
                    if v is not None:
                        seen[v].append(i)
                for v, occ in seen.items():
                    if len(occ) >= 2:
                        n_red += len(occ)
                        for i in occ:
                            k = (i, a)
                            if red.get(k, 0) < th:
                                red[k] = th
            fd_red[(lhs, a)] = n_red
    total = len(red)
    hot = sum(1 for th in red.values() if th >= TOP)
    return total, hot, fd_red


# ---------------- designs over the data --------------------------------------
def subschema_causes(rows, XA, proj, sem):
    """Occurrence -> causing-FD map for one materialized subschema.
    Returns ({(row,col): [fd,...]}, pos) with fd in ORIGINAL (lhs,rhs) form."""
    cols = sorted(XA)
    pos = {a: i for i, a in enumerate(cols)}
    sub = list({tuple(r[c] for c in cols) for r in rows})
    causes = defaultdict(list)
    by_lhs = defaultdict(list)
    for lhs, rhs in proj:
        by_lhs[tuple(sorted(pos[x] for x in lhs))].append((pos[next(iter(rhs))], (lhs, rhs)))
    for lhs_cols, rhss in by_lhs.items():
        groups = fd_groups(sub, list(lhs_cols), sem)
        for a, fd in rhss:
            for idxs in groups.values():
                if len(idxs) < 2:
                    continue
                seen = defaultdict(list)
                for i in idxs:
                    v = sub[i][a]
                    if v is not None:
                        seen[v].append(i)
                for v, occ in seen.items():
                    if len(occ) >= 2:
                        for i in occ:
                            causes[(i, a)].append(fd)
    return dict(causes)


def design_redundancy(rows, D, sem, theta, cache):
    """Stored redundant occurrences of a design, split by causing heat.
    `cache` maps frozenset(XA) -> causes map, shared across designs/channels
    since the same subschema costs the same regardless of who selected it."""
    tot = hot = 0
    n_sub = 0
    for XA, proj in D:
        n_sub += 1
        if not proj:
            continue
        key = frozenset(XA)
        if key not in cache:
            cache[key] = subschema_causes(rows, XA, proj, sem)
        causes = cache[key]
        tot += len(causes)
        hot += sum(1 for fds in causes.values()
                   if max(theta.get(fd, 1) for fd in fds) >= TOP)
    return tot, hot, n_sub


def ck_nullable(D, rows):
    """Per subschema of D: nullable columns in its cheapest minimal key."""
    has_null = [any(r[c] is None for r in rows) for c in range(len(rows[0]))]
    out = []
    for XA, proj in D:
        keys = B.minimal_keys(XA, proj)
        best = min(sum(1 for a in k if has_null[a]) for k in keys)
        out.append(best)
    return out


# ---------------- per-run driver ---------------------------------------------
def run_one(ds, sem, json_path):
    with open(json_path, encoding="utf-8") as fh:
        d = json.load(fh)
    ncols_json = d["R"]
    fds_multi = d["fds"]

    if ds == BIOCASE_JSON:
        rows = header = None
        for toks in NULLTOK_CANDS:
            rows, header = load_biocase(toks)
            mapping, rm = calibrate(rows, ncols_json, fds_multi, sem)
            if mapping:
                null_toks = toks
                break
        else:
            return {"skip": "no calibration (biocase null tokens)"}
    else:
        names = mysql_variant(TABLES[ds])
        want = f"{TABLES[ds]}({sem})"
        tbl = want if want in names else (TABLES[ds] if TABLES[ds] in names else None)
        if tbl is None:
            return {"skip": f"no benchmark table among {sorted(names)}"}
        rows, header = load_mysql(tbl)
        null_toks = None
        mapping, rm = calibrate(rows, ncols_json, fds_multi, sem)
    if mapping is None:
        return {"skip": f"no column mapping makes the {len(fds_multi)} FDs hold"}

    # remap the data once so JSON coordinates ARE data coordinates
    data = [tuple(r[c] for c in mapping) for r in rows]
    n, m = len(data), ncols_json
    complete = sum(1 for r in data for v in r if v is not None)

    R, sigma, keys = B.load(json_path)
    atomic = [(tuple(sorted(lhs)), next(iter(rhs))) for lhs, rhs in sigma]

    t0 = time.perf_counter()
    red, _, fd_red = count_redundancy(data, atomic, sem)
    t_count = time.perf_counter() - t0

    red_max = max(fd_red.values(), default=0)
    theta_data = {}
    for (lhs, a), r_ in fd_red.items():
        fd = (frozenset(lhs), frozenset({a}))
        theta_data[fd] = 1 if (r_ == 0 or red_max == 0) else max(1, math.ceil(SCALE * r_ / red_max))
    hist = defaultdict(int)
    for v in theta_data.values():
        hist[v] += 1

    prep = B.prepare(sigma)
    theta_graded = B.levels(sigma, GRADED_P, GRADED_SEED)
    channels = {}
    ckn = None
    xa_cache = {}
    for cname, th in (("graded", theta_graded), ("data", theta_data)):
        ch = {}
        for mmode in MODES:
            D = B.synthesize(R, sigma, keys, mmode, hot=th, prep=prep)
            met = B.decomp_metrics(D, th)
            dtot, dhot, nsub = design_redundancy(data, D, sem, th, xa_cache)
            ch[mmode] = {"red": dtot, "red_hot": dhot, "hmax": met["hmax"],
                         "size": nsub}
            if cname == "data" and mmode == "ha":
                ckn = ck_nullable(D, data)
        channels[cname] = ch

    return {"n_rows": n, "n_cols": m, "mapping": ("identity" if mapping == list(range(m))
            else ("drop_first" if mapping[0] == 1 else "drop_last")),
            "rhs_mode": rm, "null_tokens": null_toks,
            "complete": complete, "red": red,
            "pct_red": round(100 * red / complete, 2) if complete else 0.0,
            "t_count": round(t_count, 3),
            "fd_red_max": red_max, "theta_hist": dict(hist),
            "channels": channels,
            "ck_nullable": {"per_sub": ckn, "max": max(ckn) if ckn else 0}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()

    rq2 = json.load(open(os.path.join(HERE, "rq2_draft.json")))
    runs = [k for k in rq2 if k != "_skipped"]

    jobs = []
    for tag in runs:
        ds, sem = tag.rsplit(":", 1)
        path = os.path.join(FD_BASE, SEMS[sem], "FD", ds + ".json")
        cost = rq2[tag]["fds"] * (17_000_000 if ds == "pdbx" else 1)
        jobs.append((cost, ds, sem, path))
    jobs.sort()

    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT))
    for _, ds, sem, path in jobs:
        tag = f"{ds}:{sem}"
        if args.only and args.only != tag:
            continue
        if tag in out and "skip" not in out[tag]:
            print(f"done already: {tag}", flush=True)
            continue
        t0 = time.perf_counter()
        try:
            res = run_one(ds, sem, path)
        except Exception as e:
            import traceback; traceback.print_exc()
            res = {"skip": f"error: {e}"}
        out[tag] = res
        json.dump(out, open(OUT, "w"), indent=1)
        if "skip" in res:
            print(f"SKIP {tag}: {res['skip']}", flush=True)
        else:
            g, dt = res["channels"]["graded"], res["channels"]["data"]
            print(f"{tag:28s} n={res['n_rows']:8d} red={res['red']:9d} ({res['pct_red']:5.2f}%) "
                  f"map={res['mapping']}/{res['rhs_mode']} t={time.perf_counter()-t0:6.1f}s",
                  flush=True)
            for cn, ch in (("graded", g), ("data", dt)):
                print("   " + cn + "  " + "  ".join(
                    f"{m[:4]}: red={ch[m]['red']:8d} hot={ch[m]['red_hot']:8d} hmax={ch[m]['hmax']:4.1f}"
                    for m in MODES), flush=True)
    print("wrote redundancy_study.json", flush=True)


if __name__ == "__main__":
    main()
