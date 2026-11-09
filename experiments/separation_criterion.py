"""The separation criterion of the paper (Thm. "Separation criterion") on the 12 reducts (RQ2).

For the structure-optimal design D of each reduct, the two conditions of the theorem are decided by
implication tests on the atomic closure A, before any heat is declared:

  (1) every cover of A contains, for each subschema S of D, a member X->a whose schema Xa dominates S,
      that is, has at least as many non-key FDs as S on every right-hand side.  Then D has the least
      heat h* under every heat map.  The test: for each S, the members whose schema does not dominate
      S do not imply A.
  (2) some cover avoids an attribute b that D stores under a non-key FD.  Then a declaration of b
      makes D arbitrarily hotter than h*; otherwise D is at most N times hotter, N the largest number
      of non-key FDs of a subschema of D.  The test: for each such b, the members whose schema
      stores no non-key FD on b imply A.

The second part also runs both synthesizers with every attribute D stores at heat 1000 and every
other attribute at the default 1, and records the two maximal heats: the ratio grows with the heat
exactly on the attributes of (2), and stays at most N on the others.

    python separation_criterion.py            writes results/rq2_separation_criterion.json
"""
import os, sys, json, time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B

REDUCTS = ["routes", "claims", "breast", "t_biocase_identification_r91800_c38", "hospital", "pdbx",
           "bridges", "echo", "ncvoter", "dblp10k", "hepatitis", "china_weather"]
HOT = 1000
OUT = os.path.join(config.RESULTS, "rq2_separation_criterion.json")


class Closure:
    """Attribute closures over a fixed list of single-RHS FDs, restricted to an active subset."""

    def __init__(self, fds):
        self.fds = fds
        self.uses = {}
        for i, (lhs, _) in enumerate(fds):
            for a in lhs:
                self.uses.setdefault(a, []).append(i)

    def __call__(self, X, active):
        missing = {}
        c, todo = set(X), list(X)
        for i in active:
            missing[i] = len(self.fds[i][0])
            if missing[i] == 0:
                (a,) = self.fds[i][1]
                if a not in c:
                    c.add(a)
                    todo.append(a)
        while todo:
            a = todo.pop()
            for i in self.uses.get(a, ()):
                if i in missing:
                    missing[i] -= 1
                    if missing[i] == 0:
                        (b,) = self.fds[i][1]
                        if b not in c:
                            c.add(b)
                            todo.append(b)
        return c


def run(ds):
    R, sigma, keys = B.load(os.path.join(config.FD_BASE, config.SEMS["nulluc"], "FD", ds + ".json"))
    t0 = time.perf_counter()
    prep = B.prepare(sigma)
    clos = Closure(sigma)
    profile = {}

    def prof(S):
        if S not in profile:
            proj = prep["proj"].get(S) or B.projection(sigma, S)
            profile[S] = Counter(next(iter(fd[1])) for fd in B.nonkey_atomic(S, proj))
        return profile[S]

    def implies_A(F):
        # F is a set of indices into sigma; does it imply every member of the closure?
        need = {}
        for i, (lhs, rhs) in enumerate(sigma):
            if i not in F:
                need.setdefault(lhs, set()).update(rhs)
        return all(rhs <= clos(lhs, F) for lhs, rhs in need.items())

    D = B.synthesize(R, sigma, keys, "so", prep=prep)
    crit = [S for S, _ in D if prof(S)]
    stored = sorted(set().union(*(prof(S) for S in crit))) if crit else []
    N = max((sum(prof(S).values()) for S in crit), default=0)
    member = [prof(fd[0] | fd[1]) for fd in sigma]

    cond1 = True
    for S in crit:
        p = prof(S)
        rest = {i for i, q in enumerate(member) if not all(q.get(b, 0) >= n for b, n in p.items())}
        if implies_A(rest):
            cond1 = False
            break
    avoidable = [b for b in stored if implies_A({i for i, q in enumerate(member) if q.get(b, 0) == 0})]

    hot = {}
    for b in stored:
        theta = B.attribute_heat(sigma, {b: HOT})
        so = B.decomp_max_hot(B.synthesize(R, sigma, keys, "so", hot=theta, prep=prep), theta)
        ha = B.decomp_max_hot(B.synthesize(R, sigma, keys, "ha", hot=theta, prep=prep), theta)
        hot[str(b)] = {"so": so, "ha": ha}
    rec = {"rules": len(sigma), "so_critical_subschemata": len(crit), "N": N,
           "stored": stored, "condition_1": cond1, "condition_2_attributes": avoidable,
           f"declared_{HOT}": hot, "seconds": round(time.perf_counter() - t0, 1)}
    return rec


def main():
    out = {}
    for ds in REDUCTS:
        out[ds] = run(ds)
        r = out[ds]
        print(f"{ds:40s} (1)={r['condition_1']!s:5s} (2)={r['condition_2_attributes']}  "
              f"N={r['N']}  {r['seconds']} s", flush=True)
    json.dump(out, open(OUT, "w"), indent=1)
    tied = [d for d in REDUCTS if out[d]["condition_1"]]
    unbounded = [d for d in REDUCTS if out[d]["condition_2_attributes"]]
    print(f"condition (1): {len(tied)} reducts {tied}")
    print(f"condition (2): {len(unbounded)} reducts {unbounded}")


if __name__ == "__main__":
    main()
