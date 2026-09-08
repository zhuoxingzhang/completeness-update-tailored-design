# -*- coding: utf-8 -*-
"""Why each criterion keeps the subschemata it keeps, step by step.

Synthesis walks the atomic closure in an order its criterion chooses, drops every FD the rest
still implies, and keeps one subschema per survivor.  The whole difference between two
designs is therefore the order, and the order comes from one number per FD: the count of
non-key FDs in its subschema for the structural baseline, the heat of that subschema for
ours.  Printing both numbers beside the trace says whether a separation rests on those
numbers or only on the tie break, and it is what the walkthrough in the paper reports.

Usage: python delivery_trace.py [hot attribute, default c]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
import synthesis as B
import config as CFG
import delivery_schema as S

B.HEAT = "all"


def order_of(mode, heat, prep):
    """The order the criterion eliminates in, critical FDs first."""
    proj, mkeys, nonkey = prep["proj"], prep["mkeys"], prep["nonkey"]
    crit, noncrit = prep["crit"], prep["noncrit"]

    def hotness(fd):
        XA = fd[0] | fd[1]
        return sum(B.fd_hot(g, heat)
                   for g in B.schema_nonkey(XA, proj[XA], mkeys[XA], heat))

    if mode == "3nf":
        return list(S.ATOM), (lambda fd: "")
    key_count = lambda fd: len(mkeys[fd[0] | fd[1]])
    if mode == "so":
        return (sorted(crit, key=lambda fd: len(nonkey[fd[0] | fd[1]]), reverse=True)
                + sorted(noncrit, key=key_count, reverse=True),
                lambda fd: f"f={len(nonkey[fd[0] | fd[1]])}")
    return (sorted(crit, key=hotness, reverse=True)
            + sorted(noncrit, key=key_count, reverse=True),
            lambda fd: f"heat={hotness(fd)}")


def heat_of(XA, heat, prep):
    """The heat of one schema: its non-key atomic FDs, summed."""
    proj = prep["proj"].get(XA) or S.ATOM
    keys = prep["mkeys"].get(XA) or B.minimal_keys(XA, S.ATOM)
    return sum(B.fd_hot(g, heat) for g in B.schema_nonkey(XA, proj, keys, heat))


def trace(mode, heat, prep):
    """One elimination pass, reporting what it drops and what it keeps."""
    order, label = order_of(mode, heat, prep)
    work, D, dropped = list(S.ATOM), [], []
    for fd in order:
        if B.is_redundant(fd, work):
            work.remove(fd)
            dropped.append(fd)
        else:
            B._add(D, fd[0] | fd[1], prep["proj"][fd[0] | fd[1]])
    kept = [XA for XA, _ in D if not any(XA < X2 for X2, _ in D)]
    return order, label, dropped, [XA for XA, _ in D], kept


def main():
    x = (sys.argv[1] if len(sys.argv) > 1 else "c")
    heat = S.op_heat({a: (8 if a == x else 1) for a in S.REFRESH.values()})
    prep = B.prepare(S.ATOM)
    crit = {S.nm(fd[0] | fd[1]) for fd in prep["crit"]}
    print(f"  R = {S.ATTRS}, {len(S.ATOM)} atomic FDs, hot operation: change {x}")
    print(f"  critical subschemata (they store non-key FDs): {' '.join(sorted(crit))}\n")
    designs = {}
    for mode, lab in (("so", "SO, by non-key FD count"),
                      ("ha", "HA, by subschema heat"),
                      ("3nf", "3NF, in the order the closure arrives")):
        order, label, dropped, built, kept = trace(mode, heat, prep)
        designs[mode] = kept
        print(f"  {lab}")
        for fd in order[:8]:
            mark = "dropped" if fd in dropped else "kept   "
            print(f"    {S.fdnm(fd):<12} {label(fd):<10} {mark}"
                  f"  -> {S.nm(fd[0] | fd[1])}")
        if len(order) > 8:
            print(f"    ... {len(order) - 8} more, of which "
                  f"{len([f for f in order[8:] if f in dropped])} dropped")
        print(f"    result {' '.join(sorted(S.nm(XA) for XA in kept))}"
              f"  ({len(kept)} subschemata, {sum(len(XA) for XA in kept)} columns)\n")

    R = frozenset(range(len(S.ATTRS)))
    every = sorted({XA for kept in designs.values() for XA in kept}, key=S.nm)
    print(f"  heat of R: {heat_of(R, heat, prep)}")
    print("  heat of each subschema a design keeps: "
          + "  ".join(f"{S.nm(XA)} {heat_of(XA, heat, prep)}" for XA in every))


if __name__ == "__main__":
    main()
