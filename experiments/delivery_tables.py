# -*- coding: utf-8 -*-
"""The LaTeX blocks of the experiment section, generated from the result files.

Every figure and table of the delivery study is emitted here rather than typed into the
paper, so that a rerun of a study changes the paper by regenerating this output and never by
hand.  Blocks are written one file each under `blocks/`, and the paper splices them in.

    fig_kappa    one update of each kind, over group depths          rq1_operations.json
    fig_curves   the window as the traffic and the scope move        rq4_rq5_curves.json
    tab_decl     what each way of declaring heat costs                rq4_rq5_curves.json
    tab_side     the read side and what it costs to store            rq3_reads.json
    tab_window   one window under three rate profiles                rq7_window.json
    fig_window   the window as the group grows                       rq7_window.json

Usage: python delivery_tables.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config as CFG

OUT = os.path.join(CFG.RESULTS, "blocks")
A, B = "cheap on c", "cheap on v"          # \Dupd and \Dstr


def load(name):
    return json.load(open(os.path.join(CFG.RESULTS, name)))


def med(xs):
    return sorted(xs)[len(xs) // 2]


def fac(r):
    """A factor as the paper prints it: one decimal below ten, whole numbers above."""
    return f"{r:.1f}" if r < 10 else f"{r:,.0f}".replace(",", "{,}")


def coords(pairs, fmt="{:.6g}"):
    return " ".join("(" + fmt.format(x) + "," + fmt.format(y) + ")" for x, y in pairs)


def decades(vals):
    """Tick positions from a decimal ladder that the given values span."""
    lo, hi = min(vals), max(vals)
    rung = [x * 10 ** e for e in range(-3, 6) for x in (1, 2, 5)]
    keep = [t for t in rung if lo / 1.6 <= t <= hi * 1.6]
    return ",".join(f"{t:g}" for t in keep)


# ---- RQ1 --------------------------------------------------------------------
def fig_kappa():
    d = load("rq1_operations.json")
    depths = sorted({x["depth"] for x in d})
    get = lambda op, k: [(x["depth"], x["secs"][k] * 1000) for x in d if x["op"] == op]

    def labelled(op):
        """The costly design's curve, each point carrying its factor over the other."""
        r = {x["depth"]: x["secs"][B] / x["secs"][A] for x in d if x["op"] == op}
        return " ".join(
            f"({p},{v:.2f}) [" + ("{}" if i == 0 else "$" + fac(r[p]) + chr(92) + "times$")
            + "]" for i, (p, v) in enumerate(get(op, B)))
    ticks = ",".join(str(p) for p in depths)
    names = {3: "3", 30: "30", 300: "300", 3000: "3k", 30000: "30k"}
    return rf"""\begin{{figure}}
\centering
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 1, horizontal sep=11mm}},
  height=2.8cm, width=0.545\columnwidth,
  xmode=log, ymode=log, log basis x=10,
  enlarge y limits={{upper=0.35, lower=0.12}},
  label style={{font=\scriptsize}}, tick label style={{font=\scriptsize}},
  title style={{font=\scriptsize, yshift=-3pt}},
  legend style={{font=\tiny, fill=none, draw=none}},
  every axis plot/.append style={{line width=0.7pt, mark size=1.1pt}},
  xlabel={{group of one district $k$}},
  xtick={{{ticks}}}, xticklabels={{{','.join(names[p] for p in depths)}}},
]
\nextgroupplot[
  title={{(a) refresh}},
  ylabel={{time (ms)}},
  legend to name=leg:kappa, legend columns=2,
]
\addplot[serD, mark=*, nodes near coords, point meta=explicit symbolic,
         nodes near coords style={{font=\tiny, serD!60!black, anchor=south east,
         xshift=-1pt, yshift=-1pt}}] coordinates {{{labelled('reassign')}}};
\addplot[serA, mark=square*] coordinates {{{coords(get('reassign', A), '{:.4g}')}}};
\addplot[serD, densely dashed, mark=*] coordinates {{{coords(get('swap', B), '{:.4g}')}}};
\addplot[serA, densely dashed, mark=square*] coordinates {{{coords(get('swap', A), '{:.4g}')}}};
\legend{{\Dstr{{}}, \Dupd{{}}}}
\nextgroupplot[
  title={{(b) completion}},
  ylabel={{ms per tuple}},
]
\addplot[serD, mark=*, nodes near coords, point meta=explicit symbolic,
         nodes near coords style={{font=\tiny, serD!60!black, anchor=south east,
         xshift=-1pt, yshift=-1pt}}] coordinates {{{labelled('completion_conflict')}}};
\addplot[serA, mark=square*] coordinates {{{coords(get('completion_conflict', A), '{:.4g}')}}};
\addplot[serD, densely dashed, mark=*] coordinates {{{coords(get('completion_clean', B), '{:.4g}')}}};
\addplot[serA, densely dashed, mark=square*] coordinates {{{coords(get('completion_clean', A), '{:.4g}')}}};
\end{{groupplot}}
\end{{tikzpicture}}\\[2pt]
\ref{{leg:kappa}}
\caption{{Scaling the group $k$ of one district on the delivery designs (\ref{{rq:op}}): (a) one reassignment (solid) and one van swap (dashed), (b) one entering tuple, conflicting (solid) and clean (dashed); labels give the time on \Dstr{{}} as a multiple of the time on \Dupd{{}}.}}
\label{{fig:kappa}}
\end{{figure}}"""


def tab_ops():
    """The rows one update writes, which Fig. kappa cannot show because it plots time."""
    d = load("rq1_operations.json")
    k = max(x["depth"] for x in d)
    at = {(x["op"], x["depth"]): x for x in d}
    names = [("reassignment", "reassign"), ("van swap", "swap"),
             ("completion, conflicting", "completion_conflict"),
             ("completion, clean", "completion_clean"), ("insert", "insert_total")]

    def cnt(v):
        """A row count, averaged over the operations of a run where they differ."""
        s = f"{v:,.0f}" if abs(v - round(v)) < 0.05 else f"{v:,.1f}"
        return s.replace(",", "{,}")

    def rat(r):
        if r >= 10:
            return f"{r:,.0f}".replace(",", "{,}")
        return f"{r:.2f}" if r >= 1 else f"{r:.2g}"

    def ms(v):
        """A time in milliseconds, at three significant digits with the zero kept."""
        return f"{v:.0f}" if v >= 100 else (f"{v:.1f}" if v >= 10 else f"{v:.2f}")

    body = "\n".join(
        f"{lab} & {cnt(x['rows'][B])} & {cnt(x['rows'][A])} & "
        f"${rat(x['rows'][B] / x['rows'][A])}\\times$ & "
        f"{ms(x['secs'][B] * 1000)} & {ms(x['secs'][A] * 1000)} & "
        f"${rat(x['secs'][B] / x['secs'][A])}\\times$\\\\"
        for lab, op in names for x in [at[(op, k)]])
    kk = f"{k:,}".replace(",", "{,}")
    return rf"""\begin{{table}}
\caption{{One update of each kind at a group of $k={kk}$ (\ref{{rq:op}}): the rows each design rewrites and the time it takes.
Fig.~\ref{{fig:kappa}} plots the same times as $k$ grows.}}
\label{{tab:ops}}
\scriptsize
\setlength{{\tabcolsep}}{{4pt}}
\begin{{tabular}}{{@{{}}l rrr rrr@{{}}}}
\toprule
 & \multicolumn{{3}}{{c}}{{rows written}} & \multicolumn{{3}}{{c}}{{time (ms)}}\\
\cmidrule(lr){{2-4}}\cmidrule(l){{5-7}}
update & \Dstr{{}} & \Dupd{{}} & \Dstr{{}}/\Dupd{{}} & \Dstr{{}} & \Dupd{{}} & \Dstr{{}}/\Dupd{{}}\\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{table}}"""


# ---- RQ4 and RQ5a -----------------------------------------------------------
def fig_curves():
    d = load("rq4_rq5_curves.json")
    sk, dr = d["skew"], d["drift"]
    return rf"""\begin{{figure}}
\centering
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 1, horizontal sep=11mm}},
  height=2.8cm, width=0.545\columnwidth,
  ymode=log,
  label style={{font=\scriptsize}}, tick label style={{font=\scriptsize}},
  title style={{font=\scriptsize, yshift=-3pt}},
  legend style={{font=\tiny, fill=none, draw=none}},
  every axis plot/.append style={{line width=0.7pt, mark size=1.1pt}},
  log ticks with fixed point,
]
\nextgroupplot[
  title={{(a) skew (\ref{{rq:skew}})}},
  xmode=log, log basis x=2,
  xlabel={{reassignments per van swap}}, ylabel={{rows written}},
  xtick={{0.0625,0.25,1,4,16}},
  xticklabels={{$\frac{{1}}{{16}}$,$\frac{{1}}{{4}}$,1,4,16}},
  ytick={{10000,30000,100000}}, yticklabels={{10k,30k,100k}},
  legend to name=leg:curves, legend columns=2,
]
\addplot[serD, mark=*] coordinates {{{coords([(x['w'], x[B]) for x in sk])}}};
\addplot[serA, mark=square*] coordinates {{{coords([(x['w'], x[A]) for x in sk])}}};
\legend{{\Dstr{{}}, \Dupd{{}}}}
\nextgroupplot[
  title={{(b) drift (\ref{{rq:robust}})}},
  xlabel={{scope filled}}, ylabel={{rows written}},
  xtick={{25,50,75,100}}, xticklabels={{25\%,50\%,75\%,100\%}},
  ytick={{1000,10000,100000}}, yticklabels={{1k,10k,100k}},
]
\addplot[serD, mark=*] coordinates {{{coords([(x['frac'] * 100, x[B]) for x in dr])}}};
\addplot[serA, mark=square*] coordinates {{{coords([(x['frac'] * 100, x[A]) for x in dr])}}};
\end{{groupplot}}
\end{{tikzpicture}}\\[2pt]
\ref{{leg:curves}}
\caption{{Robustness (\ref{{rq:skew}}, \ref{{rq:robust}}), rows one window of $1{{,}}000$ updates writes: (a) as its traffic moves from van swaps to reassignments, at a group of $192$; (b) as the scope fills, at a full group of $192$.}}
\label{{fig:curves}}
\end{{figure}}"""


def tab_decl():
    """What heat-aware synthesis pays under each declaration, per profile."""
    d = load("rq4_rq5_curves.json")["misestimate"]
    mixes = ("desk", "mixed", "fleet")
    names = {"desk": "delivery desk", "mixed": "split", "fleet": "fleet office"}
    chans = [("rate", "by the measured rates"),
             ("uniform", "uniformly"),
             ("size", "by the group each rule ranges over"),
             ("swapped", "with the two rates exchanged")]
    best = {m: min(x["rows"] for x in d if x["mix"] == m) for m in mixes}
    cell = lambda c, m: [x for x in d if x["mix"] == m and x["channel"] == c
                         and x["design"] == "HA"][0]["rows"] / best[m]
    body = "\n".join(
        lab + "".join(f" & ${cell(c, m):.2f}" + r"\times$" for m in mixes) + r"\\"
        for c, lab in chans)
    depth = d[0]["depth"]
    return rf"""\begin{{table}}
\caption{{What a declaration costs (\ref{{rq:robust}}): rows one window of $1{{,}}000$ updates writes on the design heat-aware synthesis returns, as a multiple of the cheaper of the two designs, at a group of ${depth}$. A profile is served right where the factor is $1.00$.}}
\label{{tab:decl}}
\scriptsize
\setlength{{\tabcolsep}}{{4pt}}
\begin{{tabular}}{{@{{}}l rrr@{{}}}}
\toprule
heat declared & {" & ".join(names[m] for m in mixes)}\\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{table}}"""


# ---- RQ3 --------------------------------------------------------------------
def tab_side():
    r = load("rq3_reads.json")
    mx = load("rq3_mixed.json")
    g0 = [x for x in mx if x["gamma"] == 0][0]
    ms = lambda k, q: r[k][q]["secs"] * 1000
    mb = lambda k: r[k]["bytes"] / 1024 ** 2
    rows = [("refresh workload, $\\gamma=0$", "s", g0["secs"][B], g0["secs"][A], "{:.2f}"),
            ("scope reconstruction", "ms", ms(B, "rebuild"), ms(A, "rebuild"), "{:.0f}"),
            ("delivery by key", "ms", ms(B, "lookup"), ms(A, "lookup"), "{:.2f}"),
            ("history of one courier", "ms", ms(B, "history"), ms(A, "history"), "{:.0f}"),
            ("stored size", "MB", mb(B), mb(A), "{:.0f}")]
    body = "\n".join(
        f"{n} & {u} & {f.format(b)} & {f.format(a)} & ${b / a:.2f}" + r"\times$\\"
        for n, u, b, a, f in rows)
    return rf"""\begin{{table}}
\caption{{The delivery designs at $10^{{6}}$ tuples, except for the refresh workload, which runs at $36{{,}}000$: what a window of pure refreshes takes, and what the designs cost to read from and to store (\ref{{rq:mixed}}).}}
\label{{tab:side}}
\scriptsize
\setlength{{\tabcolsep}}{{4pt}}
\begin{{tabular}}{{@{{}}ll rr r@{{}}}}
\toprule
 & & \Dstr{{}} & \Dupd{{}} & \Dstr{{}}/\Dupd{{}}\\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{table}}"""


# ---- RQ3, the completion share ----------------------------------------------
def fig_mixed():
    d = load("rq3_mixed.json")
    ch = lambda c, k: [(x["gamma"] * 100, x["secs"][k]) for x in d if x["channel"] == c]
    return rf"""\begin{{figure}}
\centering
\begin{{tikzpicture}}
\begin{{axis}}[
  height=2.8cm, width=0.74\columnwidth,
  ymode=log, log ticks with fixed point,
  xlabel={{completion share $\gamma$}}, ylabel={{time (s)}},
  xtick={{0,10,25,50}}, xticklabels={{0\%,10\%,25\%,50\%}},
  label style={{font=\scriptsize}}, tick label style={{font=\scriptsize}},
  legend style={{font=\tiny, fill=none, draw=none, at={{(1.02,0.5)}}, anchor=west}},
  every axis plot/.append style={{line width=0.7pt, mark size=1.1pt}},
]
\addplot[serD, mark=*] coordinates {{{coords(ch('completion_clean', B), '{:.4g}')}}};
\addplot[serD, densely dashed, mark=*] coordinates {{{coords(ch('completion_conflict', B), '{:.4g}')}}};
\addplot[serA, mark=square*] coordinates {{{coords(ch('completion_clean', A), '{:.4g}')}}};
\addplot[serA, densely dashed, mark=square*] coordinates {{{coords(ch('completion_conflict', A), '{:.4g}')}}};
\legend{{\Dstr{{}} clean, \Dstr{{}} confl., \Dupd{{}} clean, \Dupd{{}} confl.}}
\end{{axis}}
\end{{tikzpicture}}
\caption{{Mixed workloads at a group of $3{{,}}000$ (\ref{{rq:mixed}}): time for $200$ updates as the completion share $\gamma$ grows, with clean (solid) and conflicting (dashed) completions.}}
\label{{fig:mixed}}
\end{{figure}}"""


# ---- RQ7 --------------------------------------------------------------------
def _win(depth):
    d = load("rq7_window.json")
    out = {}
    for mix in ("desk", "mixed", "fleet"):
        r = {x["design"]: x for x in d if x["depth"] == depth and x["mix"] == mix}
        if len(r) == 2:
            out[mix] = (r[B]["rows"], r[A]["rows"], med(r[B]["secs"]), med(r[A]["secs"]))
    return out


def tab_window():
    d = load("rq7_window.json")
    depth = max(x["depth"] for x in d)
    n = max(x["n"] for x in d if x["depth"] == depth)
    w = _win(depth)
    names = {"desk": "delivery desk", "mixed": "split", "fleet": "fleet office"}
    body = "\n".join(
        f"{names[m]} & {rb:,} & {ra:,} & ${rb / ra:.2f}".replace(",", "{,}")
        + rf"\times$ & {sb:.2f} & {sa:.2f} & ${sb / sa:.2f}\times$\\"
        for m, (rb, ra, sb, sa) in w.items())
    return rf"""\begin{{table}}
\caption{{One maintenance window of $1{{,}}000$ updates over ${n:,}$ tuples in groups of ${depth:,}$ (\ref{{rq:window}}): what it writes and what it takes on each design, under three rate profiles.}}
\label{{tab:window}}
\scriptsize
\setlength{{\tabcolsep}}{{4pt}}
\begin{{tabular}}{{@{{}}l rrr rrr@{{}}}}
\toprule
 & \multicolumn{{3}}{{c}}{{rows written}} & \multicolumn{{3}}{{c}}{{seconds}}\\
\cmidrule(lr){{2-4}}\cmidrule(lr){{5-7}}
window & \Dstr{{}} & \Dupd{{}} & ratio & \Dstr{{}} & \Dupd{{}} & ratio\\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{table}}""".replace("$" + f"{n:,}" + "$", "$" + f"{n:,}".replace(",", "{,}") + "$") \
                .replace("$" + f"{depth:,}" + "$", "$" + f"{depth:,}".replace(",", "{,}") + "$")


def fig_window():
    d = load("rq7_window.json")
    depths = sorted({x["depth"] for x in d})
    pts = lambda mix, k: [(p, med([x["secs"] for x in d
                                   if x["depth"] == p and x["mix"] == mix
                                   and x["design"] == k][0]))
                          for p in depths]
    secs = [y for mix in ("desk", "fleet") for k in (A, B) for _, y in pts(mix, k)]
    return rf"""\begin{{figure}}
\centering
\begin{{tikzpicture}}
\begin{{axis}}[
  height=3.3cm, width=0.93\columnwidth,
  xmode=log, log basis x=2, ymode=log,
  xlabel={{deliveries a district carries}}, ylabel={{window (s)}},
  label style={{font=\scriptsize}}, tick label style={{font=\scriptsize}},
  legend style={{font=\scriptsize, draw=none, fill=none, at={{(0.02,0.97)}},
                anchor=north west, row sep=-1pt,
                /tikz/every even column/.append style={{column sep=5pt}}}},
  legend columns=2,
  xtick={{{','.join(str(p) for p in depths)}}},
  xticklabels={{{','.join(f'{p:,}'.replace(',', '{,}') for p in depths)}}},
  ytick={{{decades(secs)}}},
  log ticks with fixed point, grid=major, grid style={{gray!20}}]
\addplot[serD, mark=*, mark size=1.3pt, thick]
  coordinates {{{coords(pts('desk', B), '{:.4g}')}}};
\addlegendentry{{\Dstr{{}}, desk}}
\addplot[serA, mark=square*, mark size=1.3pt, thick]
  coordinates {{{coords(pts('desk', A), '{:.4g}')}}};
\addlegendentry{{\Dupd{{}}, desk}}
\addplot[serD, mark=*, mark size=1.3pt, thick, densely dashed]
  coordinates {{{coords(pts('fleet', B), '{:.4g}')}}};
\addlegendentry{{\Dstr{{}}, fleet}}
\addplot[serA, mark=square*, mark size=1.3pt, thick, densely dashed]
  coordinates {{{coords(pts('fleet', A), '{:.4g}')}}};
\addlegendentry{{\Dupd{{}}, fleet}}
\end{{axis}}
\end{{tikzpicture}}
\caption{{The same window as the group each rule ranges over grows (\ref{{rq:window}}): the desk profile (solid), whose traffic is reassignments, and the fleet profile (dashed), whose traffic is van swaps.}}
\label{{fig:window}}
\end{{figure}}"""


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("fig_kappa", fig_kappa), ("tab_ops", tab_ops),
                     ("fig_mixed", fig_mixed),
                     ("tab_side", tab_side), ("fig_curves", fig_curves),
                     ("tab_decl", tab_decl),
                     ("tab_window", tab_window), ("fig_window", fig_window)):
        try:
            text = fn()
        except (FileNotFoundError, IndexError, ValueError) as e:
            print(f"  {name:<12} skipped ({type(e).__name__}: {e})")
            continue
        with open(os.path.join(OUT, name + ".tex"), "w", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"  {name:<12} {len(text.splitlines()):>3} lines")


if __name__ == "__main__":
    main()
