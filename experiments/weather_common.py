"""Shared front end of the weather end-to-end scripts (RQ6).

Loads and calibrates the relation, chooses the scope E as in real_workload
(attributes join E in ascending order of their null counts while at least a
third of the tuples stay E-complete), and computes the reduct Sigma[E] with its
minimal keys.  The calibrated relation is cached under the scratch directory.
"""
import os, sys, json, pickle, time
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import config
import synthesis as B
import redundancy_study as rs
import real_workload as RW

HERE = os.path.dirname(os.path.abspath(__file__))
MODE_OF = {"3NF": "3nf", "SO": "so", "HA": "ha"}
ORDER0 = ["3NF", "SO", "HA"]


def load(ds, sem):
    jp = os.path.join(rs.FD_BASE, rs.SEMS[sem], "FD", ds + ".json")
    cache = os.path.join(config.scratch_dir(), f"data_{ds}_{sem}.pkl")
    if os.path.exists(cache):
        data, E = pickle.load(open(cache, "rb"))
    else:
        dj = json.load(open(jp, encoding="utf-8"))
        rows, _ = rs.load_mysql(f"{rs.TABLES[ds]}({sem})")
        mapping, _ = rs.calibrate(rows, dj["R"], dj["fds"], sem)
        data = [tuple(r[c] for c in mapping) for r in rows]
        E = RW.choose_E(data, dj["R"])
        pickle.dump((data, E), open(cache, "wb"))
    Eset = frozenset(E)
    scope = [r for r in data if all(r[a] is not None for a in E)]
    _, sigma, _ = B.load(jp)
    reduct = [fd for fd in sigma if (fd[0] | fd[1]) <= Eset]
    print(f"{ds}:{sem} rows={len(data)} |E|={len(E)} scope={len(scope)} |reduct|={len(reduct)}", flush=True)
    t0 = time.time()
    keys = B.minimal_keys(Eset, reduct)
    prep = B.prepare(reduct)
    print(f"keys={len(keys)} prep={time.time()-t0:.0f}s", flush=True)
    return data, E, Eset, scope, reduct, keys, prep


def open_db(db):
    admin = config.connect(autocommit=True)
    admin.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {db}")
    admin.close()
    conn = config.connect(db, autocommit=True)
    return conn, conn.cursor()


def drop_all(cur, db):
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (db,))
    for (t,) in list(cur.fetchall()):
        cur.execute(f"DROP TABLE IF EXISTS `{t}`")


def rule_label(fd):
    return f"{sorted(fd[0])}->{sorted(fd[1])}"


def find_rule(reduct, X, A):
    return next(fd for fd in reduct if tuple(sorted(fd[0])) == tuple(X) and next(iter(fd[1])) == A)


def parse_rule(s):
    """'2,16->5' -> ((2, 16), 5)"""
    lhs, rhs = s.split("->")
    return tuple(int(x) for x in lhs.split(",")), int(rhs)
