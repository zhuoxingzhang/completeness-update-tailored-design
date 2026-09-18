r"""The window priced as the exact diff every projection a design stores has to undergo.

release_cost.price charges one statement per subschema holding an updated attribute and counts
the rows that statement reaches.  That is the model of the amplification proposition, and it is
the right model of the rows a group rewrite costs, but it is not the whole maintenance of a
decomposition.  A stored row is a distinct projection of the scope, carried by however many base
rows agree on it.  A release that moves only some of those rows splits the projection: the old
row keeps the support that stayed behind and the image has to be added.  Where the release makes
two projections coincide, one of them goes away instead.  So one attribute update costs a
subschema

  * an UPDATE of the projections whose whole support moves,
  * an INSERT of the images of the projections that split,
  * a DELETE of the projections whose image the table already holds,

and only the first is what release_cost charges.  A subschema that stores the attribute away from
a key never splits on it: the amplification proposition makes it move the whole group of its
determinant, so the support of every row of that group moves at once.  The splits therefore live
entirely in the copy layer.  release_live.py keeps its own account of the same diff, built while
it renders the statements, and the two agree to the row.
"""
import collections
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import synthesis as B

B.HEAT = "all"
import release_cost as W


class Window:
    """One real release: the relation it ran against, its declaration, and its coalesced work."""

    def __init__(self, tag, decl=None):
        d = pickle.load(open(W.relpath(tag), "rb"))
        self.attrs, data = d["attrs"], d["data"]
        E = W.choose_E(data, len(self.attrs))
        self.scope = [r for r in data if all(r[a] is not None for a in E)]
        self.R = R = W.Rel(tag)
        assert R.n == len(self.scope), f"scope disagrees: {R.n} vs {len(self.scope)}"
        self.M = len(self.attrs)
        self.plan = W.coalesce(R)
        nev = {}
        for a, j, _ in R.ev:
            nev.setdefault(a, np.zeros(R.n, dtype=np.int64))[j] += 1
        self.events = {a: int(v.sum()) for a, v in nev.items()}
        self.theta = W.floor({fd: (decl.get(next(iter(fd[1])), 0) if decl is not None
                                   else self.events.get(next(iter(fd[1])), 0)) for fd in R.reduct})
        self.prep = B.prepare(R.reduct)
        self.col0 = [list(c) for c in zip(*self.scope)]
        self._groups = {}
        self.WL = self._workload()

    def rows_of(self, a, g):
        """The base rows of one whole group of the coalescing determinant, as the plan fixed it."""
        if a not in self._groups:
            gid = self.R.gid(self.plan[a]["X"])
            o = np.argsort(gid, kind="stable")
            self._groups[a] = (o, np.searchsorted(gid[o], np.arange(gid.max() + 2)))
        o, b = self._groups[a]
        return o[b[g]:b[g + 1]]

    def _workload(self):
        """The updates the diff coalesces into: one per whole group, one per leftover event."""
        R, plan = self.R, self.plan
        seen, out = set(), []
        gids = {a: (R.gid(plan[a]["X"]) if plan[a]["X"] else None) for a in plan}
        for a, j, v in R.ev:
            p = plan.get(a)
            if p is None:
                continue
            g = gids[a]
            if p["whole"] is not None and g is not None and p["whole"][g[j]]:
                key = (a, int(g[j]))
                if key in seen:
                    continue
                seen.add(key)
                out.append((a, int(g[j]), None, v))
            else:
                out.append((a, None, int(j), v))
        want = sum(p["updates"] for p in plan.values())
        assert len(out) == want, f"{len(out)} updates derived, {want} expected from the plan"
        return out

    def synthesize(self, order, mode):
        p = dict(self.prep)
        crit, noncrit = set(self.prep["crit"]), set(self.prep["noncrit"])
        p["crit"] = [f for f in order if f in crit]
        p["noncrit"] = [f for f in order if f in noncrit]
        return B.synthesize(self.R.E, order, self.R.keys, mode, hot=self.theta, prep=p)

    def hosts(self, D):
        """Per attribute, the subschemata storing it, and whether it sits there away from a key."""
        R, plan = self.R, self.plan
        out = collections.defaultdict(list)
        for i, (S, proj) in enumerate(D):
            touched = S & set(plan)
            if not touched:
                continue
            nk = collections.defaultdict(list)
            for fd in B.nonkey_atomic(S, proj):
                nk[next(iter(fd[1]))].append(fd)
            for a in touched:
                if a in nk:
                    fd = max(nk[a], key=lambda f: R.rows_per_group(S, f[0]).sum())
                    out[a].append({"i": i, "cols": tuple(sorted(S)),
                                   "where": tuple(sorted(fd[0])), "charged": True})
                else:
                    out[a].append({"i": i, "cols": tuple(sorted(S)), "where": None,
                                   "charged": False})
        return out

    def price(self, D):
        """Statements and rows the whole window costs on D, as the projection diff requires."""
        R, n = self.R, self.R.n
        hs = self.hosts(D)
        col = [list(c) for c in self.col0]
        live = sorted({h["i"] for a in hs for h in hs[a]})
        proj = {}
        for i in live:
            cs = tuple(sorted(D[i][0]))
            c = collections.Counter()
            for t in range(n):
                c[tuple(col[x][t] for x in cs)] += 1
            proj[i] = c
        before = sum(len(proj[i]) for i in live)
        ver, idx = [0] * self.M, {}

        def group(cs):
            v = tuple(ver[x] for x in cs)
            held = idx.get(cs)
            if held is None or held[0] != v:
                g = collections.defaultdict(list)
                for t in range(n):
                    g[tuple(col[x][t] for x in cs)].append(t)
                held = idx[cs] = (v, g)
            return held[1]

        acct = collections.Counter()
        for a, g, j, v in self.WL:
            rws = [j] if g is None else [int(t) for t in self.rows_of(a, g)]
            reach = set(rws)
            for h in hs[a]:
                if h["charged"]:
                    gr = group(h["where"])
                    for val in {tuple(col[x][t] for x in h["where"]) for t in rws}:
                        reach.update(gr[val])
            reach = sorted(reach)
            for h in hs[a]:
                i, cs = h["i"], h["cols"]
                pos = cs.index(a)
                aff = collections.Counter()
                for t in reach:
                    aff[tuple(col[x][t] for x in cs)] += 1
                pj = proj[i]
                nu = nd = ni = 0
                for ot, c in aff.items():
                    if ot[pos] == v:
                        continue
                    assert pj[ot] >= c, f"s{i}: a projection is stored {pj[ot]} times, {c} move"
                    nt = ot[:pos] + (v,) + ot[pos + 1:]
                    if c == pj[ot]:
                        del pj[ot]
                        if nt in pj:
                            nd += 1
                        else:
                            nu += 1
                    else:
                        pj[ot] -= c
                        if nt not in pj:
                            ni += 1
                    pj[nt] += c
                acct["updated"] += nu
                acct["deleted"] += nd
                acct["inserted"] += ni
                acct["statements"] += (nu > 0) + (nd > 0) + (ni > 0)
                if h["charged"]:
                    acct["charged_rows"] += nu + nd + ni
            for t in reach:
                col[a][t] = v
            ver[a] += 1
        acct["rows"] = acct["updated"] + acct["inserted"] + acct["deleted"]
        acct["stored_before"] = before
        acct["stored_after"] = sum(len(proj[i]) for i in live)
        acct["pred_s"] = W.ALPHA * acct["statements"] + W.BETA * acct["rows"]
        return dict(acct)
