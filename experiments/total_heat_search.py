"""Exhaustive search for the least total heat over the elimination orders of synthesis (RQ2).

For one reduct and one heat declaration, branch and bound over the subsets F of the critical
members of the atomic closure such that F together with every E-BCNF member implies the closure,
which are exactly the outcomes of eliminating redundant members in some order.  The design of F
keeps the schemata Xa of its members, absorbs a schema into a proper superset, and costs the sum of
the heats of its maximal critical schemata.  Members are branched on in decreasing schema heat, the
order of Alg. 1, and the heat-aware design gives the first upper bound.

    python total_heat_search.py <reduct> <g<seed> | worst> [time limit s]   one line of JSON
    python total_heat_search.py --all [time limit s]                         every reduct, 20 graded
                                                                             draws at p = 0.5 and the
                                                                             worst single attribute

--all writes results/rq2_total_heat_search.json, on CUTD_WORKERS processes (default 18), with a
time limit of 300 s per search.  A search that ends by the limit is marked "timeout"; the paper
reports the reducts on which every search ends.
"""
import os, sys, json, time, threading, subprocess
from concurrent.futures import ThreadPoolExecutor
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B

REDUCTS = ["routes", "claims", "breast", "t_biocase_identification_r91800_c38", "hospital", "pdbx",
           "bridges", "echo", "ncvoter", "dblp10k", "hepatitis", "china_weather"]
DECLS = [f"g{s}" for s in range(20)] + ["worst"]
OUT = os.path.join(config.RESULTS, "rq2_total_heat_search.json")
SKEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_skew.json")  # sweep_skew.py


def search(ds, decl, tlim):
    R, sigma, keys = B.load(os.path.join(config.FD_BASE, config.SEMS["nulluc"], "FD", ds + ".json"))
    if decl == "worst":
        w = json.load(open(SKEW))[ds + ":nulluc"]
        if not w.get("best"):
            return {"ds": ds, "decl": decl, "skip": "no separating attribute"}
        theta = B.attribute_heat(sigma, {w["best"]["attribute"]: 10})
    else:
        theta = B.levels(sigma, 0.5, int(decl[1:]))

    t0 = time.perf_counter()
    prep = B.prepare(sigma)
    proj, crit, noncrit = prep["proj"], prep["crit"], prep["noncrit"]

    def H(S):
        return sum(B.fd_hot(fd, theta) for fd in B.nonkey_atomic(S, proj[S]))

    def mask(X):
        m = 0
        for a in X:
            m |= 1 << a
        return m

    LHS = np.array([mask(fd[0]) for fd in sigma], dtype=np.uint64)
    RHS = np.array([mask(fd[1]) for fd in sigma], dtype=np.uint64)
    idx = {fd: i for i, fd in enumerate(sigma)}

    def clos(x, active):
        c = np.uint64(x)
        while True:
            fire = active & ((LHS & ~c) == 0)
            n = c | np.bitwise_or.reduce(RHS[fire]) if fire.any() else c
            if n == c:
                return int(c)
            c = n

    crit = sorted(crit, key=lambda fd: -H(fd[0] | fd[1]))
    sch = [fd[0] | fd[1] for fd in crit]
    hs = {S: H(S) for S in set(sch)}
    n = len(crit)
    cidx = [idx[fd] for fd in crit]
    base = np.zeros(len(sigma), dtype=bool)
    for fd in noncrit:
        base[idx[fd]] = True
    lhsm = [mask(fd[0]) for fd in crit]
    rhsm = [mask(fd[1]) for fd in crit]

    def implied(active, j):
        return bool(clos(lhsm[j], active) & rhsm[j])

    def cost(kept):
        S = {sch[j] for j in kept}
        return sum(hs[s] for s in S if not any(s < t for t in S))

    allact = base.copy()
    allact[cidx] = True
    must = set()
    for j in range(n):                      # members that no elimination order can drop
        allact[cidx[j]] = False
        if not implied(allact, j):
            must.add(j)
        allact[cidx[j]] = True

    ref = {m: B.decomp_metrics(B.synthesize(R, sigma, keys, m, hot=theta, prep=prep), theta)
           for m in ("3nf", "so", "ha")}
    best = [ref["ha"]["htot"], None]
    state = {"nodes": 0, "timeout": False}
    deadline = time.perf_counter() + tlim

    def lower(kept, k):
        # kept schemata that no undecided member can absorb count in full, the others at least
        # the largest of them
        S = {sch[j] for j in kept}
        top = [s for s in S if not any(s < t for t in S)]
        und = {sch[j] for j in range(k, n)}
        sure = [s for s in top if not any(s < t for t in und)]
        rest = [hs[s] for s in top if any(s < t for t in und)]
        return sum(hs[s] for s in sure) + (max(rest) if rest else 0)

    def dfs(k, kept, active):
        state["nodes"] += 1
        if time.perf_counter() > deadline:
            state["timeout"] = True
            return
        if best[1] is not None and lower(kept, k) >= best[0]:
            return
        if k == n:
            c = cost(kept)
            if best[1] is None or c < best[0]:
                best[0], best[1] = c, list(kept)
            return
        if k not in must:
            active[cidx[k]] = False             # drop k while it stays implied, so every
            if implied(active, k):              # earlier drop stays implied as well
                dfs(k + 1, kept, active)
            active[cidx[k]] = True
            if state["timeout"]:
                return
        dfs(k + 1, kept + [k], active)

    sys.setrecursionlimit(1 << 20)
    threading.stack_size(256 * 1024 * 1024 - 4096)  # the recursion is as deep as the critical members
    th = threading.Thread(target=dfs, args=(0, [], allact.copy()))
    th.start()
    th.join()
    return {"ds": ds, "decl": decl, "closure": len(sigma), "critical": n, "nodes": state["nodes"],
            "timeout": state["timeout"], "least_total": best[0],
            "ha_total": ref["ha"]["htot"], "so_total": ref["so"]["htot"], "3nf_total": ref["3nf"]["htot"],
            "ha_max": ref["ha"]["hmax"], "seconds": round(time.perf_counter() - t0, 1)}


def run_all(tlim):
    jobs = [(d, x) for d in reversed(REDUCTS) for x in DECLS]      # the large reducts first
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def one(job):
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), job[0], job[1], str(tlim)],
                               capture_output=True, text=True, timeout=tlim * 4 + 600, env=env)
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, IndexError, ValueError):
            return {"ds": job[0], "decl": job[1], "timeout": True, "error": "no result within the limit"}

    with ThreadPoolExecutor(int(os.environ.get("CUTD_WORKERS", 18))) as ex:
        rows = list(ex.map(one, jobs))
    json.dump({"protocol": {"p": 0.5, "draws": DECLS, "time_limit_s": tlim}, "runs": rows},
              open(OUT, "w"), indent=1)
    print(summary(rows))


def summary(rows):
    out = []
    for d in REDUCTS:
        rs = [r for r in rows if r["ds"] == d and "skip" not in r]
        done = [r for r in rs if not r.get("timeout")]
        lower = [r for r in rs if "least_total" in r and r["least_total"] < r["ha_total"]]
        out.append(f"{d:40} searches {len(rs):2}  ended {len(done):2}  lower total than HA {len(lower)}")
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1] == "--all":
        run_all(float(sys.argv[2]) if len(sys.argv) > 2 else 300.0)
    else:
        print(json.dumps(search(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 300.0)))
