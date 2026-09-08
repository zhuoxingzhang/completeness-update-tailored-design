# -*- coding: utf-8 -*-
"""The snapshot the paper prints, checked against the rules it is supposed to illustrate.

Six deliveries, five of them complete and one still pending because its van has not reported
in.  District D1 is covered by Maggie on three of the complete tuples, which is the redundancy
the hot rule carries, and the pending tuple claims Ravi for D1, which is a conflict no
constraint can see while the tuple sits outside the scope.  The script checks that the five
complete tuples satisfy every rule, that the pending one violates the hot rule and nothing
else, and prints what each design stores.

Usage: python delivery_example.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import delivery_schema as S
import delivery_curves as C

NUL = "-"
ROWS = [
    ("t1", "North", "Maggie", "D1", "Telco-A", "R1", "V7", "Mon"),
    ("t2", "South", "Maggie", "D1", "Telco-B", "R2", "V9", "Mon"),
    ("t3", "North", "Maggie", "D1", "Telco-A", "R1", "V7", "Wed"),
    ("t4", "North", "Maggie", "D2", "Telco-A", "R1", "V7", "Tue"),
    ("t5", "North", "Ravi", "D3", "Telco-B", "R2", "V4", "Mon"),
    ("t6", "South", "Ravi", "D1", NUL, "R2", "V4", "Tue"),
]
SCOPE = [r[1:] for r in ROWS if NUL not in r]
PENDING = [r[1:] for r in ROWS if NUL in r]


def broken(rows):
    """The declared rules the given tuples do not satisfy."""
    out = []
    for X, A in S.SIGMA:
        a, seen = next(iter(A)), {}
        for t in rows:
            k = tuple(t[i] for i in sorted(X))
            if seen.setdefault(k, t[a]) != t[a]:
                out.append(S.nm(X) + "->" + S.INV[a])
                break
    return out


def main():
    print(f"  R = {S.ATTRS}, rules " + ", ".join(S.fdnm(fd) for fd in S.SIGMA))
    print(f"  {'':<4}" + "".join(f"{S.INV[i]:>10}" for i in range(len(S.ATTRS))))
    for r in ROWS:
        print(f"  {r[0]:<4}" + "".join(f"{v:>10}" for v in r[1:])
              + ("    pending" if NUL in r else ""))
    net = {t[S.AID["v"]]: t[S.AID["g"]] for t in SCOPE}
    filled = [tuple(net[t[S.AID["v"]]] if i == S.AID["g"] else v
                    for i, v in enumerate(t)) for t in PENDING]
    shared = sorted(set.intersection(*({S.nm(XA) for XA, _, _ in D}
                                       for D in C.two_designs().values())))
    print(f"\n  the scope satisfies every rule: {broken(SCOPE) == []}")
    print(f"  registering the van's network breaks: {broken(SCOPE + filled)}")
    print(f"  the designs share {len(shared)} subschemata: " + " ".join(shared))
    for k, D in C.two_designs().items():
        print(f"\n  {k}: " + " ".join(sorted(S.nm(XA) for XA, _, _ in D)))
        for XA, keys, _ in sorted(D, key=lambda x: S.nm(x[0])):
            idx = sorted(XA)
            seen = []
            for t in SCOPE:
                v = tuple(t[i] for i in idx)
                if v not in seen:
                    seen.append(v)
            print(f"    {S.nm(XA):<6} keys {'/'.join(sorted(S.nm(k) for k in keys)):<12}"
                  f"{len(seen)} rows: " + "  ".join("(" + ",".join(v) + ")" for v in seen))


if __name__ == "__main__":
    main()
