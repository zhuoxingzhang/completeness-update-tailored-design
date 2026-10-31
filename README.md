# Completeness- and Update-Tailored Database Design: Artifact

> ## Full version of the paper: [`full-version.pdf`](full-version.pdf)
>
> **The paper together with its appendix, which gives all proofs.**

Code, constraint sets and result files for the paper *Completeness- and
Update-Tailored Database Design*, which bounds the **update heat** a design stores
redundantly over the completeness scope of an application and synthesizes designs
of least heat. Every experiment can be re-run from here.

## Contents

```
src/synthesis.py   the synthesis engine: FDs, minimal keys, non-key FDs, schema heat,
                   and the three objectives; run it directly for a self-check
src/config.py      paths and database credentials, read from environment variables
experiments/       one script per study (table below)
data/fd/           constraint sets mined from the twelve benchmark relations
data/release/      constraint set of the real release (OWID COVID table, 30 June 2024)
results/           the JSON behind every table and figure of the paper
```

The three synthesizers share one front end (the reduct `Sigma[E]`, its atomic
closure, the minimal keys), so the objective is the only variable:

| key   | objective |
|-------|-----------|
| `3nf` | classical lossless, dependency-preserving 3NF synthesis |
| `so`  | structure-optimal: fewest procedurally maintained FDs per subschema |
| `ha`  | heat-aware: Algorithm 1 of the paper |

`so` and `ha` differ in one line: which redundant critical schemata are eliminated
first.

## Quick start (no database needed)

```bash
python -m pip install -r requirements.txt
python src/synthesis.py                          # self-check; Figure 1: maximal heat 8 (SO) vs 2 (HA)
python experiments/delivery_example.py           # Table 1 and the two designs of Figure 1
python experiments/delivery_schema.py --orders   # 200 shuffles of the closure: criterion or tie break?
python experiments/reduct_frontend.py            # Table 3 and the sweep over p below
```

`reduct_frontend.py` sweeps `p` from 0.1 to 1 with 20 draws each, about an hour
on 18 workers (`CUTD_WORKERS`); the synthesis times in the paper were measured with
`CUTD_WORKERS=1`. The paper reports the uncertainty reading of nulls (`nulluc`);
constraint sets and results also carry the equality reading (`nulleq`).

## Scripts

All under `experiments/`; result files under `results/`. † needs MySQL.

| Script | Produces |
|---|---|
| `delivery_example.py` | Table 1, Figure 1 |
| `delivery_trace.py` | the eliminations of the worked synthesis examples on the delivery schema |
| `delivery_schema.py` | schema, instance generator and offline cost model; `--orders`, `--costs`, `--window` (`rq6_window_model.json`); its rates are Table 2 |
| `delivery_live.py --ops` † | RQ1: Figure 2 and the table below (`rq1_operations.json`) |
| `delivery_live.py --mixed` † | RQ3: Figure 4, first row of Table 5 (`rq3_mixed.json`) |
| `delivery_live.py --reads` † | RQ3: Table 5 (`rq3_reads.json`) |
| `delivery_live.py` † | RQ6: Table 7, Figure 6 (`rq6_window.json`) |
| `delivery_curves.py` | RQ4, RQ5: Figure 5, Table 6 (`rq4_rq5_curves.json`) |
| `delivery_tables.py` | the delivery tables and figures as LaTeX |
| `reduct_frontend.py` | RQ2: Table 3, Figure 3(a), the sweep below (`rq2_reducts.json`) |
| `sweep_skew.py` | RQ2: Figure 3(b) (`rq2_worst_single_attribute.json`) |
| `redundancy_study.py` † | RQ2: Table 4 (`rq2_redundant_occurrences.json`) |
| `release_build.py` | RQ7: relation and workload of the real release |
| `release_mine.py` | RQ7: `data/release/owid_fds.json` |
| `release_classes.py` | RQ7: the designs each criterion returns over elimination orders, priced offline (`rq7_real_classes.json`), and the three timed orders (`rq7_real_picks.json`) |
| `release_rules.py` | RQ7: non-key rules and total heat of Table 8 (`rq7_real_rules.json`) |
| `release_live.py` † | RQ7: the whole window run live; window statistics of Table 8 (`rq7_real_live.json`) |
| `release_maps.py` † | RQ7: timed priced updates of Table 8 and Figure 8 (`rq7_real_maps.json`, visiting orders in `rq7_real_visit.json`) |
| `release_tables.py` | RQ7: Table 8, Figure 8 as LaTeX (`rq7_real_summary.json`) |
| `release_skew.py` | RQ7: Figure 7 |
| `dataset_stats.py` † | the benchmark table below (`datasets.json`) |

The delivery scripts share `delivery_schema.py`. The release scripts share
`release_cost.py` (relation, `E`, coalescing of the workload, offline price),
`release_pool.py` (elimination orders) and `release_diff.py` (a window as the
projection diff of every subschema). `redundancy_study.py` and `sweep_skew.py`
keep a running record next to the script, so an interrupted sweep resumes.

The † scripts create and drop databases of their own; use a scratch server.
`delivery_live.py --dry` gives the row counts without a server, `--verify`
compares both designs after a window by count and checksum, and `--tiny` runs one
small scale.

## Measurement protocol

**Timing.** Times are medians of three repetitions that visit the designs
round-robin; inside a repetition each design is rebuilt, analyzed, timed and
dropped. The buffer pool is raised for a run and restored afterwards. The
repetitions of a controlled window differ by at most 5% of the median
(`rq6_window.json`).

**Delivery instances.** Zones rotate through the branches and vans through the
zones; Armstrong witnesses for the independencies sit in a disjoint value range
(Beeri, Dowd, Fagin and Statman, *JACM* 31(1), 1984; Langeveldt and Link,
*Inf. Syst.* 35(3), 2010). Before every run `delivery_schema.py` recomputes the
instance's dependencies and compares them with the declared closure, so the
instance satisfies the declared rules and no others. A design stores
deduplicated subschema projections with a unique index per minimal key; non-key
FDs are maintained by the workload's own statements, so the designs differ only
in what they store. Server row counts agree with the offline model within 1%.

**Delivery workloads.** `--ops` issues 200 updates of a kind in one client call
at every group and divides the time by 200; `--mixed` interleaves refreshes with
completions from an all-clean or an all-conflicting pool at share `gamma`; the
default run issues windows of 1,000 updates under the three profiles of Table 2.
Each window is drawn once and issued against every design.

**Benchmark reducts.** Heat is declared per attribute, and every rule carries the
heat of the attribute it determines (`synthesis.attribute_heat`). Under the graded
declaration, attributes not drawn hot keep heat 1. The adversarial declaration
tries every attribute of a reduct and keeps the one on which the two optimizing
designs differ most. The data-derived declaration maps the redundant value
occurrences of each attribute onto the scale. Table 4 counts redundant value
occurrences on deduplicated subschema projections.

**Real release (RQ7).** The relation and its constraints come from the edition of
30 June 2024 of the OWID COVID table; the workload is its difference to the
edition of 19 August 2024, coalesced into updates. `E` adds columns by ascending
null share while a third of the tuples stay complete on it, which gives 21 of the
23 columns (`release_cost.choose_E`). The heat of a rule `X -> A` is the number of
coalesced updates that refresh `A` inside the scope, and at least 1
(`release_cost.declare`, `HEAT_FLOOR`).

Each subschema is kept equal to the projection of the edited relation, since the
release splits and merges stored rows. Subschemata index their minimal keys with
plain indexes, since the release breaks some rules mined on the earlier edition
(20 of those 3NF stores, one each of SO's and HA's; `release_broke` in
`rq7_real_live.json`). A non-key FD `X -> A` whose groups the window rewrites
whole is maintained through a table over `XA` keyed by `X`, whose trigger
rewrites the group in the subschema.

Under the observed levels, an attribute with `n` priced updates in the scope gets
level `l = 1 + min(9, floor(9 n / n_max))`; the designs run three times
round-robin and the reported time is the mean. The maps `l^2`, `2^l` and `l^3`
re-number the levels: under a map `phi`, a priced update at level `l` is issued
`1 + 2 floor(g / 2)` times, `g = phi(l) / (l phi(1))`, alternating between the
released and the earlier value, so the window still ends in the released edition;
each design runs once per map.

The timed designs come from the elimination orders `keep7_3` (3NF), `h+c+` (SO)
and `haswap164` (HA) in `rq7_real_picks.json`. A criterion fixes a design only up
to the elimination order; `release_classes.py` (`POOL=250 SWAPS=300 HA_SWAPS=300
TARGET=priced`) searches those orders and prices what they return. The offline
model ranks the timed designs as the server does: it predicts 4.70 and 2.00 times
HA's price for 3NF and SO, against the measured 4.75 and 1.83.

The timed runs predate the heat floor of 1 and the declaration by updates (they
declared the cells the updates rewrite); under the current declaration the
designs and levels of Table 8 are the same and only the heats change
(`rq7_real_rules.json`), now from 4 to 509 rather than 0 to 319,969. The shipped
search returns the same designs for 3NF and SO; for HA, the order `haswap239`
prices 0.15% below the timed design, and `haswap164` swaps two cold subschemata
under the floor that no priced update touches, so the priced statements and rows
of Table 8 hold for both, while the whole-window statements differ by 1.2%.
`HEAT_FLOOR=0` rebuilds the timed designs exactly.

## Setup

Python 3.12 and MySQL 8.0 produced the reported numbers. No credentials are
stored here; `src/config.py` reads them from the environment:

| variable | default | meaning |
|---|---|---|
| `CUTD_MYSQL_HOST` | `localhost` | server host |
| `CUTD_MYSQL_PORT` | `3306` | server port |
| `CUTD_MYSQL_USER` | `root` | user |
| `CUTD_MYSQL_PASSWORD` | *(empty)* | password |
| `CUTD_MYSQL_DB` | `benchmarks` | database holding the benchmark relations |
| `CUTD_DELIVERY_DB` | `delivery_study` | database of the delivery designs |
| `CUTD_RELEASE_DB` | `release_study` | database of the real-release designs |
| `CUTD_MYSQL_CLIENT` | `mysql` | command-line client |
| `CUTD_FD_BASE` | `data/fd` | directory of the constraint sets |
| `CUTD_SCRATCH` | `.scratch` | bulk-load temporaries and the built real-release relation |
| `CUTD_OWID_REPO` | `.scratch/owid` | clone of the publisher's repository |

The delivery study sets the buffer pool, so its user must be allowed to set global
variables.

### Benchmark relations

The relations are public profiling benchmarks and are not redistributed; their
mined constraint sets are in `data/fd/`. Dimensions, share of null cells and
FDs mined under the no-information reading (`dataset_stats.py`):

| relation | attributes | rows | % null | mined FDs |
|---|---:|---:|---:|---:|
| biocase | 38 | 91,799 | 76.2 | 8 |
| breast | 12 | 699 | 0.2 | 43 |
| bridges | 14 | 108 | 5.1 | 67 |
| claims | 14 | 96,131 | 5.9 | 17 |
| dblp10k | 35 | 4,837 | 38.2 | 708 |
| echo | 14 | 132 | 7.1 | 91 |
| hepatitis | 21 | 155 | 5.1 | 2,995 |
| hospital | 16 | 114,919 | 0.8 | 42 |
| ncvoter | 20 | 1,000 | 14.3 | 271 |
| pdbx | 14 | 17,305,799 | 0.8 | 37 |
| routes | 10 | 67,663 | 7.8 | 15 |
| weather | 19 | 262,920 | 8.4 | 2,955 |

For the † scripts, load each relation into `CUTD_MYSQL_DB` as two tables,
`<relation>(nulleq)` and `<relation>(nulluc)`; `redundancy_study.py` documents
the calibration that aligns a table with its constraint set. The delivery studies
need no benchmark data.

### The real release

```bash
git clone --filter=blob:none --no-checkout https://github.com/owid/covid-19-data .scratch/owid
python experiments/release_build.py
```

The clone is 41 MB; `release_build.py` fetches the two editions on demand and
writes the relation and the workload (about 90 MB) to the scratch directory.
`release_mine.py nulluc 4 .scratch/owid_relation.pkl data/release/owid_fds.json 14`
mines the constraint set again. Offline, run `release_classes.py` (about a quarter
of an hour), `release_rules.py`, `release_skew.py` and `release_tables.py`; the
last two need only the shipped records. With a server, `release_live.py owid 3`
runs the whole window three times, and `release_maps.py owid obs 3`, then `sq 1`,
`exp2 1` and `cube 1` with `POOL=8589934592`, are the timed runs of Table 8; both
accept `--dry`.

## Data format

A constraint set is a JSON file `{"R": 11, "fds": [{"lhs": [0, 3], "rhs": [5, 7]}, ...]}`
over attributes `0 .. R-1`. `synthesis.load()` splits it into atomic FDs and
computes the minimal keys. Rules are identified by attribute index, in the paper
as well.

## One update of each kind at a group of 3,000 (RQ1)

Rows each design rewrites (a mean where fractional) and time, medians of three
round-robin repetitions (`rq1_operations.json`); Figure 2 plots the times over `k`.

| update | rows SO | rows HA | SO / HA | time SO (ms) | time HA (ms) | SO / HA |
|---|---:|---:|---:|---:|---:|---:|
| reassignment | 6,006 | 8 | 751× | 159 | 3.14 | 51× |
| van swap | 7 | 2,005 | 0.0035× | 4.54 | 62.1 | 0.073× |
| completion, conflicting | 6,026.2 | 28.2 | 214× | 162 | 5.92 | 27× |
| completion, clean | 4 | 4 | 1.00× | 2.74 | 2.97 | 0.92× |
| insert | 3 | 3 | 1.00× | 2.71 | 2.61 | 1.04× |

## The sweep over the share `p` of hot attributes (RQ2)

On how many of the 12 reducts HA is strictly cooler than each baseline under the
graded declaration (means over 20 draws), and its largest excess in subschemata
over SO; HA is never hotter than either baseline (`rq2_reducts.json`):

| | | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HA cooler than SO | maximum | 4 | 5 | 5 | 6 | 5 | 5 | 6 | 4 | 5 | 5 |
| | total | 4 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| HA cooler than 3NF | maximum | 5 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 7 |
| | total | 7 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| HA subschemata over SO (%) | | 0.4 | 0.8 | 0.7 | 0.5 | 0.6 | 0.6 | 0.9 | 1.4 | 1.4 | 1.0 |

## License

MIT, see `LICENSE`.
