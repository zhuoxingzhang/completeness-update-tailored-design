# -*- coding: utf-8 -*-
"""An exact, parameterised instance of the schema the running example is to be built on.

The relation records deliveries: on a day, a courier works out of a branch, drives a van on
a round, and covers a zone.  A van reports through one GPS network, which is recorded only
once its unit has first reported in, so a tuple can stay pending until then.

    z -> c      a zone is covered by one courier on duty
    bcd -> z    a courier covers one zone per branch and day
    bc -> v     at a branch a courier drives one van
    bv -> c     at a branch a van is driven by one courier
    cv -> r     a courier and a van work one round
    rz -> b     a round covering a zone belongs to one branch
    v -> g      a van reports through one GPS network

What none of them says matters as much.  Branches share their route numbering and neighbouring
zones are served from either branch, so neither the zone nor the van alone fixes the branch or
the courier, and round numbers are reused, so a round identifies nobody by itself.  The
closure admits four designs in two families, and the families part in opposite directions:
one keeps the zone's courier under a key, the other keeps the branch's van under one, and
which is cheaper is decided by which of the two reassignments the window carries.  Two designs
in one family differ by 0.4% over a window, so it is the family a criterion has to reach.

Exactness is not assumed.  The bulk satisfies the seven rules by construction; Armstrong
witnesses are appended in a disjoint value range, refuting every dependency the rules do not
imply; and `verify_exact` recomputes the instance's own dependencies over all seven
attributes and compares them against the closure.

Usage: python delivery_schema.py             the schema, the designs and an exact instance
       python delivery_schema.py --orders    the design each criterion returns, 200 orders
       python delivery_schema.py --costs     what one update of each kind costs
       python delivery_schema.py --window    the window, over group, mix and declaration
"""
import itertools
import json
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
import synthesis as B
import config as CFG

B.HEAT = "all"

HERE = os.path.dirname(os.path.abspath(__file__))
def result(name):
    """Where a result file goes, which the artifact keeps in one directory."""
    return os.path.join(CFG.RESULTS, name)


ATTRS = "bcdgrvz"          # branch, courier, day, gps, round, van, zone
AID = {a: i for i, a in enumerate(ATTRS)}
INV = {i: a for a, i in AID.items()}
RULES = ["z>c", "bcd>z", "bc>v", "bv>c", "cv>r", "rz>b", "v>g"]
ORDER = ["3NF", "SO", "HA"]
MODE = {"3NF": "3nf", "SO": "so", "HA": "ha"}


def _S(s):
    return frozenset(AID[c] for c in s)


def nm(S):
    return "".join(sorted((INV[i] for i in S), key=ATTRS.index))


def fdnm(fd):
    return nm(fd[0]) + "->" + nm(fd[1])


SIGMA = [(_S(r.split(">")[0]), _S(r.split(">")[1])) for r in RULES]
R = frozenset(AID.values())


def atomic_closure():
    out = []
    for k in range(1, len(ATTRS) + 1):
        for X in itertools.combinations(sorted(AID.values()), k):
            Xs = frozenset(X)
            for a in sorted(B.closure(Xs, SIGMA) - Xs):
                if k == 1 or all(a not in B.closure(frozenset(Y), SIGMA)
                                 for Y in itertools.combinations(X, k - 1)):
                    out.append((Xs, frozenset({a})))
    return out


ATOM = atomic_closure()
KEYS = B.minimal_keys(R, ATOM)


def heat_map(weights):
    w = {(_S(k.split(">")[0]), _S(k.split(">")[1])): v for k, v in weights.items()}
    return {fd: w.get(fd, 0) for fd in ATOM}


def designs(heat, atom=None):
    atom = ATOM if atom is None else atom
    out = {}
    for lab in ORDER:
        D = B.synthesize(R, atom, B.minimal_keys(R, atom), MODE[lab], heat, B.prepare(atom))
        out[lab] = [(XA, B.minimal_keys(XA, proj),
                     B.schema_nonkey(XA, proj, B.minimal_keys(XA, proj), heat))
                    for XA, proj in D]
    return out


class Instance:
    """The delivery relation, with the depth of the zone's group given.

    A courier covers `zones` of them and works one at each branch and day, chosen
    by the branch and the day together, so a courier does not determine a zone and a
    zone is worked at more than one branch.  Vans are numbered across the whole company
    and rotate between branches, so a van names its courier only together with a branch;
    round numbers are reused the same way.  Every group a rule ranges over then scales with
    the branches and the days, and the zone's group holds `branches * days / zones`
    tuples.
    """

    def __init__(self, couriers=6, branches=3, zones=2, days=8):
        assert zones >= 2, "a courier covers more than one zone, or a courier is one"
        assert branches >= 2 and days >= 2 and couriers >= branches
        assert (branches * days) % zones == 0, "every zone needs as many tuples"
        self.A, self.Bn, self.m, self.E = couriers, branches, zones, days
        self.n = couriers * branches * days
        self.depth = branches * days // zones

    def tup(self, c, b, d):
        z = c * self.m + (b + d) % self.m
        v = (c + b) % self.A
        r = (2 * c + b) % self.Bn
        return (200 + b, 100 + c, 500 + d, 700 + v % 3, 300 + r, 600 + v, 400 + z)

    def rows(self):
        for c in range(self.A):
            for b in range(self.Bn):
                for d in range(self.E):
                    yield self.tup(c, b, d)

    def fresh_tuple(self, c, b, k):
        """A delivery a courier makes on a new day, covering a zone opened for it.

        The day and the zone are new and the rest is the courier's own, so the tuple
        satisfies every rule on arrival; `k` numbers the arrivals, so a window that adds two
        deliveries adds two rows rather than writing the same row twice.
        """
        t = list(self.tup(c, b, 0))
        t[AID["z"]], t[AID["d"]] = 900_000 + k, 800_000 + k
        return tuple(t)


BASE = 9 * 10 ** 8


def maximal_sets():
    gen = set()
    for a in AID.values():
        rest = [x for x in AID.values() if x != a]
        cands = [frozenset(c) for k in range(len(rest) + 1)
                 for c in itertools.combinations(rest, k)
                 if a not in B.closure(frozenset(c), SIGMA)]
        gen.update(X for X in cands if not any(X < Y for Y in cands))
    return sorted(gen, key=lambda x: (-len(x), sorted(x)))


def core_rows():
    """Armstrong witnesses, in a value range disjoint from the bulk."""
    fresh = itertools.count(BASE + 1)
    out = [tuple(BASE for _ in ATTRS)]
    for X in maximal_sets():
        out.append(tuple((BASE if AID[a] in X else next(fresh)) for a in ATTRS))
    return out


def holds(rows, X, a):
    seen = {}
    for t in rows:
        k = tuple(t[i] for i in sorted(X))
        if seen.setdefault(k, t[a]) != t[a]:
            return False
    return True


def verify_exact(rows):
    """The instance's own dependencies, against the closure of the declared rules."""
    extra, missing = [], []
    for k in range(1, len(ATTRS)):
        for X in itertools.combinations(sorted(AID.values()), k):
            Xs = frozenset(X)
            cl = B.closure(Xs, SIGMA)
            for a in sorted(set(AID.values()) - Xs):
                h, implied = holds(rows, Xs, a), a in cl
                if h and not implied and all(not holds(rows, frozenset(Y), a)
                                             for Y in itertools.combinations(X, k - 1)):
                    extra.append(nm(Xs) + "->" + INV[a])
                if implied and not h:
                    missing.append(nm(Xs) + "->" + INV[a])
    return extra, missing


# ---- what one update costs a design -----------------------------------------
ZERO = {"charged": 0, "keyed": 0, "propagated": 0, "free": 0, "rows": 0, "stmts": 0}
KIND = tuple(ZERO)


def support(rows, D):
    """How many in-scope tuples stand behind each row of each subschema."""
    return {XA: Counter(tuple(t[i] for i in sorted(XA)) for t in rows) for XA, _, _ in D}


def dets_of(a):
    return [X for X, A in ATOM if next(iter(A)) == a]


def components(rows, a):
    """The sets of tuples the attribute can be rewritten on, one update to a set.

    Every rule that determines the attribute has to keep holding, so a set that takes a new
    value has to be closed under each of their groups.  The components of those groupings
    taken together are the smallest such sets, and they partition the instance, so one
    update of the attribute is one component and the window can draw from them.

    Components come back as positions rather than tuples, because a window names the tuples
    it is about to rewrite before it rewrites them: an update that renames a courier leaves
    every later update that mentions those tuples looking for values that are no longer
    there, and a window that quietly skips them is no longer the same window on both designs.
    """
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for X in dets_of(a):
        idx, first = sorted(X), {}
        for n, t in enumerate(rows):
            k = tuple(t[i] for i in idx)
            if k in first:
                ri, rj = find(n), find(first[k])
                if ri != rj:
                    parent[ri] = rj
            else:
                first[k] = n
    out = {}
    for n in range(len(rows)):
        out.setdefault(find(n), []).append(n)
    return sorted(out.values(), key=lambda c: (len(c), c[0]))


def unit_of(rows, a):
    """The component one update of the attribute in the middle of the instance writes."""
    mid = len(rows) // 2
    return [rows[n] for n in next(c for c in components(rows, a) if mid in c)]


def change_cost(D, dets, unit, delta, sup):
    """Rows written when the tuples of `unit` take the values in `delta`.

    A subschema that holds one of the attribute's determinants owns the rows of the unit it
    projects onto, so it rewrites all of them; it is charged for them when that determinant
    is not a key there, and keyed otherwise.  A subschema holding only affected attributes
    may share its rows with tuples the update does not touch, so it writes the rows nothing
    else supports plus whatever new row it needs.
    """
    moved = set(delta)
    out = dict(ZERO)
    out["per"] = []
    for XA, keys, _ in D:
        if not (moved & XA):
            continue
        idx = sorted(XA)
        before = Counter(tuple(t[i] for i in idx) for t in unit)
        after = {tuple(delta.get(i, t[i]) for i in idx) for t in unit}
        inside = [X for X in dets if X <= XA]
        if inside:
            kind = ("charged" if any(not any(k <= X for k in keys) for X in inside)
                    else "keyed")
            rows = len(before)
        else:
            kind = "propagated"
            excl = {row for row, c in before.items() if sup[XA].get(row, 0) == c}
            made = {tuple(delta.get(i, v) for i, v in zip(idx, row)) for row in excl}
            rows = len(excl) + len([x for x in after
                                    if x not in sup[XA] and x not in made])
        if not rows:
            continue
        out[kind] += rows
        out["rows"] += rows
        out["stmts"] += 1
        out["per"].append((nm(XA), kind, rows))
    return out


def entry_cost(D, tup, sup, sign, remainder=0):
    """Rows an E-total tuple writes when it enters (+1) or leaves (-1) the scope.

    A subschema gains a row only when nothing else already carries those values and loses one
    only when nothing else still does, so the count is what the decomposition holds, not one
    row per subschema.  `remainder` counts the row the tuple moves out of or into the table
    of tuples that are not yet E-total; every design pays it alike.
    """
    out = dict(ZERO)
    for XA, _, _ in D:
        row = tuple(tup[i] for i in sorted(XA))
        have = sup[XA].get(row, 0)
        if (sign > 0 and have == 0) or (sign < 0 and have == 1):
            out["free"] += 1
            out["rows"] += 1
            out["stmts"] += 1
    out["free"] += remainder
    out["rows"] += remainder
    out["stmts"] += remainder
    out["per"] = []
    return out


# ---- the window -------------------------------------------------------------
# One refresh per attribute the schema lets an update touch, so the window leaves out no
# operation the rules admit, plus the operations that move a tuple across the scope.
REFRESH = {"reassign": "c", "transfer": "b", "reroute": "r", "rezone": "z",
           "swap": "v", "retag": "g"}
OPS = list(REFRESH) + ["completion_clean", "completion_conflict", "retraction",
                       "insert_total", "insert_partial", "delete"]

# Rates per window of 1,000 updates.  The first is a delivery desk, where the courier on duty
# for a zone is reassigned all day and the fleet stands still; the second is the same company
# read from the workshop, where vans go in and out of service and the rounds keep their
# couriers.  The third splits the difference.  Everything outside the two hot operations is
# held fixed across the three, so what moves between them is the mix, not the volume.
MIXES = {
    "desk": {"reassign": 0.30, "swap": 0.02, "reroute": 0.03, "rezone": 0.05,
             "transfer": 0.01, "retag": 0.01, "completion_clean": 0.12,
             "completion_conflict": 0.02, "retraction": 0.05, "insert_total": 0.20,
             "insert_partial": 0.10, "delete": 0.09},
    "fleet": {"reassign": 0.02, "swap": 0.30, "reroute": 0.03, "rezone": 0.05,
              "transfer": 0.01, "retag": 0.01, "completion_clean": 0.12,
              "completion_conflict": 0.02, "retraction": 0.05, "insert_total": 0.20,
              "insert_partial": 0.10, "delete": 0.09},
    "mixed": {"reassign": 0.16, "swap": 0.16, "reroute": 0.03, "rezone": 0.05,
              "transfer": 0.01, "retag": 0.01, "completion_clean": 0.12,
              "completion_conflict": 0.02, "retraction": 0.05, "insert_total": 0.20,
              "insert_partial": 0.10, "delete": 0.09},
}
CHANNELS = ["rate", "uniform", "size", "swapped"]


def hottest(mix):
    """The attribute the window rewrites most often.

    A tuple that arrives with a value its group disagrees on carries a latent conflict, and
    the completion that brings it into the scope is what surfaces it.  Which rule the
    conflict sits on follows the traffic, not the design: the more often the application
    rewrites an attribute, the more often it enters one that is already out of step.
    """
    return REFRESH[max(REFRESH, key=lambda o: mix.get(o, 0))]


def op_heat(counts):
    """A heat map from a count per operation.

    One change of an attribute has to keep every rule that determines it satisfied, so all of
    them carry the rate of that operation; a profiler measures operations, not rules.
    """
    return {fd: counts.get(nm(fd[1]), 0) for fd in ATOM}


def declare(mix, reps, comp, channel="rate"):
    """The heat map handed to synthesis, under four ways of arriving at one.

    `rate` is what a profiler measures: how often each attribute is rewritten in the window.
    `uniform` declares every rule alike, which is all the structure of the schema can say.
    `size` declares each operation by the group it ranges over, the quantity a designer reads
    off the data without watching it change.  `swapped` exchanges the rates of the two hot
    operations, which is the profile of a window this one is not.
    """
    if channel == "uniform":
        return op_heat({a: 1 for a in REFRESH.values()})
    if channel == "size":
        return op_heat({a: max(len(c) for c in comp[a]) for a in REFRESH.values()})
    rate = {a: int(round(mix[op] * reps)) for op, a in REFRESH.items()}
    rate[hottest(mix)] += int(round(mix["completion_conflict"] * reps))
    if channel == "swapped":
        rate["c"], rate["v"] = rate["v"], rate["c"]
    return op_heat(rate)


def metrics(D, heat):
    hs = [sum(heat[fd] for fd in ATOM if fd[0] <= XA and fd[1] <= XA
              and not any(k <= fd[0] for k in keys)) for XA, keys, _ in D]
    return {"designs": " ".join(sorted(nm(XA) for XA, _, _ in D)), "|D|": len(D),
            "cols": sum(len(XA) for XA, _, _ in D), "hmax": max(hs), "htot": sum(hs)}


def events(inst, mix, reps, seed=0):
    """The window as one list of logical updates, before any design sees it.

    A window is a property of the application, not of the design that has to carry it, so it
    is drawn once and then priced, or issued, against each design in turn.  A `set` rewrites
    one attribute over one component; an `enter` moves a tuple into (+1) or out of (-1) the
    scope, carrying `rest` when the tuple also leaves or joins the table of tuples that are
    not yet E-total; a `rest` update touches that table alone.  Tuples the instance already
    holds are named by position, and a rewrite names one of them rather than the set it will
    range over, because that set is a property of the relation at the time the rewrite is
    issued and earlier updates move it.
    """
    rng = random.Random(seed)
    fresh, serial = itertools.count(500_000), itertools.count()
    hot, out = hottest(mix), []
    for op in OPS:
        for _ in range(int(round(mix.get(op, 0) * reps))):
            a, b = rng.randrange(inst.A), rng.randrange(inst.Bn)
            n = (a * inst.Bn + b) * inst.E + rng.randrange(inst.E)
            if op in REFRESH:
                out.append((op, "set", REFRESH[op], n, next(fresh)))
            elif op == "completion_conflict":
                out.append((op, "set", hot, n, next(fresh)))
                out.append((op, "enter", ("new", n, next(serial)), +1, 1))
            elif op == "completion_clean":
                out.append((op, "enter", ("new", n, next(serial)), +1, 1))
            elif op == "insert_total":
                out.append((op, "enter", ("new", n, next(serial)), +1, 0))
            elif op == "retraction":
                out.append((op, "enter", n, -1, 1))
            elif op == "delete":
                out.append((op, "enter", n, -1, 0))
            elif op == "insert_partial":
                out.append((op, "rest", n, 0, 1))
    return out


def resolve(rel, ref):
    """The tuple an event names.

    A position names a tuple the instance already held.  A `new` reference names a delivery
    that has still to arrive: the courier of that tuple, out of the same branch and in the
    same van, covering a zone opened for it on a date it has not worked.  Deriving it from
    the tuple as the window has left it rather than as the instance built it is what keeps it
    consistent, since a courier the window has already replaced no longer drives that van.
    """
    if isinstance(ref, int):
        return rel[ref] if ref < len(rel) else None
    if ref[0] == "new":
        if ref[1] >= len(rel):
            return None
        base = rel[ref[1]]
        if base is None:
            return None
        t = list(base)
        t[AID["z"]], t[AID["d"]] = 900_000 + ref[2], 800_000 + ref[2]
        return tuple(t)
    return ref


class Run:
    """The relation as a window moves it, and what each design pays to keep up.

    Every design is carried through the same events, so the relation is one object and the
    designs differ only in the projections they hold.  Two things have to be read off the
    state the window has reached rather than the state it started in.  The set a rewrite is
    issued on is one: an update of an attribute has to leave every rule that determines it
    satisfied, so it ranges over the component the attribute's determinants induce, and
    earlier updates move those components.  What a subschema already holds is the other,
    since a row nothing else supports is a row the update owns.
    """

    def __init__(self, inst, named, rel=None):
        self.inst, self.named = inst, named
        self.rel = [t if t is None else tuple(t)
                    for t in (inst.rows() if rel is None else rel)]
        self.have = Counter(t for t in self.rel if t is not None)
        self.sup = {k: support([t for t in self.rel if t is not None], D)
                    for k, D in named.items()}
        self.dix = {tuple(sorted(Y)): {} for x in REFRESH.values()
                    for Y in dets_of(AID[x])}
        for n, t in enumerate(self.rel):
            if t is not None:
                self._reindex(n, None, t)
        self.rest = 0

    def _reindex(self, n, old, new):
        """Keep the group each determinant induces up to date as one tuple moves."""
        for Y, by in self.dix.items():
            if old is not None:
                k = tuple(old[j] for j in Y)
                by[k].discard(n)
                if not by[k]:
                    del by[k]
            if new is not None:
                by.setdefault(tuple(new[j] for j in Y), set()).add(n)

    def unit(self, x, seed):
        """The component of the seed tuple, in the relation as it now stands.

        Walking the determinants outwards from one tuple costs what the component holds
        rather than what the relation holds, because the groups are kept as the window moves
        them; a window that rebuilt them per update would cost the relation once per update.
        """
        if seed >= len(self.rel) or self.rel[seed] is None:
            return []
        ys = [tuple(sorted(Y)) for Y in dets_of(AID[x])]
        cur, frontier = {seed}, [seed]
        while frontier:
            nxt = []
            for n in frontier:
                t = self.rel[n]
                for Y in ys:
                    for m in self.dix[Y][tuple(t[j] for j in Y)]:
                        if m not in cur:
                            cur.add(m)
                            nxt.append(m)
            frontier = nxt
        return sorted(cur)

    def _bump(self, k, tup, d):
        for XA, _, _ in self.named[k]:
            row = tuple(tup[i] for i in sorted(XA))
            c = self.sup[k][XA]
            c[row] += d
            if c[row] <= 0:
                del c[row]

    def replace(self, n, new):
        old = self.rel[n]
        for k in self.named:
            self._bump(k, old, -1)
            self._bump(k, new, +1)
        self.have[old] -= 1
        self.have[new] += 1
        self._reindex(n, old, new)
        self.rel[n] = new

    def add(self, t):
        if self.have[t]:
            return
        for k in self.named:
            self._bump(k, t, +1)
        self.have[t] += 1
        self.rel.append(t)
        self._reindex(len(self.rel) - 1, None, t)

    def drop(self, n):
        for k in self.named:
            self._bump(k, self.rel[n], -1)
        self.have[self.rel[n]] -= 1
        self._reindex(n, self.rel[n], None)
        self.rel[n] = None

    def plan(self, ev):
        """What one event comes to on the current relation, and what it costs each design.

        Planning is kept apart from committing so that a caller which has to write the event
        out, rather than only price it, sees the relation the statements will run against.
        """
        out = {k: dict(ZERO) for k in self.named}
        if ev[1] == "set":
            _, _, x, seed, v = ev
            slots = self.unit(x, seed)
            if not slots:
                return None, out
            u = [self.rel[n] for n in slots]
            for k, D in self.named.items():
                out[k] = change_cost(D, dets_of(AID[x]), u, {AID[x]: v}, self.sup[k])
            return slots, out
        t = resolve(self.rel, ev[2])
        if t is None:
            return None, out
        if ev[1] == "enter":
            for k, D in self.named.items():
                out[k] = entry_cost(D, t, self.sup[k], ev[3], remainder=ev[4])
        else:
            for k in self.named:
                out[k]["free"] = out[k]["rows"] = out[k]["stmts"] = 1
        return t, out

    def commit(self, ev, payload):
        """Let a planned event move the relation."""
        if payload is None:
            return
        if ev[1] == "set":
            i, v = AID[ev[2]], ev[4]
            for n in payload:
                t = list(self.rel[n])
                t[i] = v
                self.replace(n, tuple(t))
        elif ev[1] == "enter":
            if ev[3] > 0:
                self.add(payload)
            elif isinstance(ev[2], int):
                self.drop(ev[2])
            self.rest += -ev[4] if ev[3] > 0 else ev[4]
        else:
            self.rest += 1

    def step(self, ev):
        """Price one event on every design, then let it move the relation."""
        payload, out = self.plan(ev)
        self.commit(ev, payload)
        return out


def window(inst, named, mix, reps, seed=0, rel=None):
    """One window: every kind of update fired at its own rate, on every design at once."""
    run = Run(inst, named, rel)
    tot = {k: dict(ZERO) for k in named}
    by = {k: {op: dict(ZERO) for op in OPS} for k in named}
    for ev in events(inst, mix, reps, seed):
        for k, c in run.step(ev).items():
            for x in KIND:
                tot[k][x] += c[x]
                by[k][ev[0]][x] += c[x]
    return {k: {"total": tot[k], "by_op": by[k]} for k in named}, run


def reached(heat, reps=200, seed=0):
    """The designs a criterion returns over `reps` listings of the closure.

    Synthesis eliminates subschemata one at a time and both criteria break ties by the order
    their input arrives in, so what a criterion returns on one listing is not what it
    returns, and a window cost read off one listing is not the cost of using that criterion.
    """
    rng, out = random.Random(seed), {lab: {} for lab in ORDER}
    for k in range(reps):
        atom = list(ATOM)
        if k:
            rng.shuffle(atom)
        D = designs(heat, atom)
        for lab in ORDER:
            out[lab].setdefault(" ".join(sorted(nm(XA) for XA, _, _ in D[lab])), D[lab])
    return out


def run_window(inst, comp, mix, reps, channel, cache=None, name=""):
    """One window under one declaration, on every design each criterion can reach.

    A window costs what its own rates make it cost, so the prices are cached per mix as well
    as per design; only the declaration is free to change without repricing.
    """
    heat = declare(mix, reps, comp, channel)
    got = reached(heat)
    todo = {key: D for lab in got for key, D in got[lab].items()
            if cache is None or (name, key) not in cache}
    if todo:
        w, _ = window(inst, todo, mix, reps)
        for key, D in todo.items():
            p = {**metrics(D, heat), **w[key]["total"],
                 "by_op": {k: v["rows"] for k, v in w[key]["by_op"].items()}}
            if cache is None:
                todo[key] = p
            else:
                cache[(name, key)] = p
    out = {}
    for lab, reach in got.items():
        prices = {key: {**(cache[(name, key)] if cache is not None else todo[key]),
                        **metrics(D, heat)} for key, D in reach.items()}
        lo = min(prices.values(), key=lambda p: p["rows"])
        hi = max(prices.values(), key=lambda p: p["rows"])
        out[lab] = {**lo, "reach": len(reach), "rows_max": hi["rows"],
                    "designs_max": hi["designs"], "hmax_max": hi["hmax"]}
    return out


def main_window(out=result("rq7_window_model.json")):
    """The window on each criterion, over the zone's group, the mix and the declaration."""
    res, days = [], (16, 32, 64, 128)
    depths = []
    for d in days:
        inst = Instance(couriers=6, branches=3, zones=2, days=d)
        rows = list(inst.rows())
        comp = {a: components(rows, AID[a]) for a in REFRESH.values()}
        cache = {}
        depths.append(inst.depth)
        for name, mix in MIXES.items():
            for ch in CHANNELS:
                r = run_window(inst, comp, mix, 1000, ch, cache, name)
                for lab in ORDER:
                    res.append({"depth": inst.depth, "n": inst.n, "mix": name,
                                "channel": ch, "design": lab, **r[lab]})
        print(f"  group {inst.depth}: {inst.n:,} tuples, "
              f"{len(cache)} designs reached", flush=True)
    json.dump(res, open(out, "w"), indent=1)
    print(f"\nwritten {out}: {len(res)} rows\n")
    print("  rows one window of 1,000 updates writes, best to worst over 200 listings.")
    print("  the ratios are what a criterion guarantees: the baseline at its best against")
    print("  HA at its worst, so a factor above one holds on every listing.\n")
    print(f"  {'group':>6}  {'mix':<8}{'declared':<10}"
          + "".join(f"{lab:>19}" for lab in ORDER) + "     SO/HA  3NFmax/HA")
    for depth in depths:
        for name in MIXES:
            for ch in CHANNELS:
                r = {x["design"]: x for x in res if x["depth"] == depth
                     and x["mix"] == name and x["channel"] == ch}
                ha = r["HA"]["rows_max"]
                print(f"  {depth:>6}  {name:<8}{ch:<10}"
                      + "".join(f"{f'{r[lab]['rows']:,}-{r[lab]['rows_max']:,}':>19}"
                               for lab in ORDER)
                      + f"   {r['SO']['rows'] / ha:6.2f}x "
                      f"{r['3NF']['rows_max'] / ha:8.2f}x")


def main_orders(reps=200):
    """Which design each criterion returns, over orders of the closure.

    Synthesis eliminates subschemata one at a time and both criteria break ties by the order
    their input arrives in, so a design that a criterion reaches on one listing of the closure
    is only evidence if it reaches it on every listing.
    """
    inst = Instance(couriers=6, branches=3, zones=2, days=16)
    rows = list(inst.rows())
    comp = {a: components(rows, AID[a]) for a in REFRESH.values()}
    rng = random.Random(0)
    seen = {(name, lab): Counter() for name in MIXES for lab in ORDER}
    for k in range(reps):
        atom = list(ATOM)
        if k:
            rng.shuffle(atom)
        for name, mix in MIXES.items():
            D = designs(declare(mix, 1000, comp, "rate"), atom)
            for lab in ORDER:
                seen[(name, lab)][" ".join(sorted(nm(XA) for XA, _, _ in D[lab]))] += 1
    print(f"design returned over {reps} orders of the closure, group of {inst.depth}:")
    for name in MIXES:
        print(f"  {name}")
        for lab in ORDER:
            for sub, cnt in sorted(seen[(name, lab)].items(), key=lambda x: -x[1]):
                print(f"    {lab:<4} {cnt:>4}/{reps}  {sub}")


def main_costs():
    """What each reassignment costs on each design, as the zone's group grows."""
    ops = {}
    for X, A in ATOM:
        ops.setdefault(nm(A), []).append((X, A))
    named = {}
    for a in sorted(ops):
        heat = {fd: (10 if fd in ops[a] else 1) for fd in ATOM}
        D = designs(heat)["HA"]
        named.setdefault(" ".join(sorted(nm(XA) for XA, _, _ in D)), D)
    labels = {k: chr(ord("A") + i) for i, k in enumerate(named)}
    for k, lab in labels.items():
        print(f"  design {lab}: {k}  ({sum(len(s) for s in k.split())} columns)")

    head = "instance"
    print()
    print(f"  {head:<26}" + "".join(f"{'change ' + a:>26}" for a in ("c", "v", "b")))
    for days in (4, 8, 16, 32):
        inst = Instance(couriers=6, branches=3, zones=2, days=days)
        rows = list(inst.rows())
        sup = {k: support(rows, D) for k, D in named.items()}
        line = f"  {inst.n:>6,} tuples, group {inst.depth:<3} "
        for a in ("c", "v", "b"):
            unit = unit_of(rows, AID[a])
            cells = []
            for k, D in named.items():
                c = change_cost(D, dets_of(AID[a]), unit, {AID[a]: -1}, sup[k])
                cells.append(f"{labels[k]} {c['rows']}")
            line += f"{'  '.join(cells):>26}"
        print(line)


def main_check():
    print(f"R = {ATTRS}, {len(RULES)} declared rules -> {len(ATOM)} atomic FDs, "
          f"{len(KEYS)} minimal keys ({', '.join(nm(k) for k in KEYS)})")
    ops = {}
    for X, A in ATOM:
        ops.setdefault(nm(A), []).append((X, A))
    for a, fds in sorted(ops.items()):
        print(f"  change {a}: " + ", ".join(fdnm(fd) for fd in fds))

    for a in sorted(ops):
        heat = {fd: (10 if fd in ops[a] else 1) for fd in ATOM}
        D = designs(heat)
        print(f"\n  declaring `change {a}' hot:")
        for lab in ORDER:
            cols = sum(len(XA) for XA, _, _ in D[lab])
            print(f"    {lab:<4} {' '.join(nm(XA) for XA, _, _ in D[lab])}  "
                  f"({len(D[lab])} subschemata, {cols} columns)")

    small = Instance(couriers=4, branches=2, zones=2, days=4)
    rows = list(small.rows())
    extra, missing = verify_exact(rows + core_rows())
    print(f"\n  instance {small.n:,} tuples ({len(set(rows))} distinct) + "
          f"{len(core_rows())} witnesses, zone group {small.depth}: "
          f"extra {extra or 'none'}, missing {missing or 'none'}")


if __name__ == "__main__":
    if "--costs" in sys.argv:
        main_costs()
    elif "--window" in sys.argv:
        main_window()
    elif "--orders" in sys.argv:
        main_orders()
    else:
        main_check()
