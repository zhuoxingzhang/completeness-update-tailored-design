# Completeness- and Update-Tailored Database Design: Artifact

> ## Full version of the paper: [`full-version.pdf`](full-version.pdf)
>
> **The paper together with its appendix, which gives all proofs.**

Code for the paper *Completeness- and Update-Tailored Database Design*, which
bounds the **update heat** a design stores redundantly over the completeness scope
of an application and synthesizes designs of least heat.

```
src/synthesis.py   FDs, minimal keys, non-key FDs, schema heat, and the three synthesizers
src/config.py      paths and database credentials, read from environment variables
experiments/       one script per study (table below)
data/fd/           constraint sets of the twelve benchmark relations
data/release/      the constraint set of the real release (RQ7)
```

The three synthesizers share one front end (the reduct, its atomic closure, the
minimal keys) and differ only in the objective: `3nf` is classical synthesis, `so`
is structure-optimal synthesis, and `ha` is Algorithm 1 of the paper. The scripts
write their results to `results/`, which is not part of the repository.

## Quick start (no database needed)

```bash
python -m pip install -r requirements.txt
python src/synthesis.py                          # self-check; Figure 1: maximal heat 8 (SO) vs 2 (HA)
python experiments/delivery_example.py           # Table 1 and the two designs of Figure 1
python experiments/delivery_schema.py --orders   # 200 shuffles of the closure: criterion or tie break?
python experiments/reduct_frontend.py            # Table 3 and the sweep over p below
```

`reduct_frontend.py` takes about an hour on 18 workers (`CUTD_WORKERS`); the
synthesis times in the paper were measured with `CUTD_WORKERS=1`.

## Scripts

All under `experiments/`; † needs MySQL and creates and drops databases of its
own, so use a scratch server.

| Script | Produces |
|---|---|
| `delivery_example.py` | Table 1, Figure 1 |
| `delivery_trace.py` | the eliminations of the worked synthesis examples |
| `delivery_schema.py` | schema, instance generator and offline cost model; its rates are Table 2 |
| `delivery_live.py --ops` † | RQ1: Figure 2 and the table below |
| `delivery_live.py --mixed` † | RQ3: Figure 4, first row of Table 4 |
| `delivery_live.py --reads` † | RQ3: Table 4 |
| `delivery_live.py` † | RQ6: Table 6, Figure 6 |
| `delivery_curves.py` | RQ4, RQ5: Figure 5, Table 5 |
| `delivery_tables.py` | the delivery tables and figures as LaTeX |
| `reduct_frontend.py` | RQ2: Table 3, Figure 3(a), the sweep below |
| `sweep_skew.py` | RQ2: Figure 3(b) |
| `total_heat_search.py` | RQ2: least total heat over the elimination orders, against HA |
| `separation_criterion.py` | RQ2: the separation criterion on SO's design, per reduct |
| `release_build.py` | RQ7: the mining window and the release window |
| `release_mine.py` | RQ7: `data/release/owid_fds.json` |
| `release_rules.py` | RQ7: the non-key rules and the heat of each design in Table 7 |
| `release_live.py` † | RQ7: the whole release window run live; window statistics of Table 7 |
| `release_maps.py` † | RQ7: the timed priced updates of Table 7 and Figure 8 |
| `release_tables.py` | RQ7: Table 7 and Figure 8 as LaTeX |
| `release_skew.py` | RQ7: Figure 7 |
| `dataset_stats.py` † | the benchmark table below |

`delivery_live.py --dry` gives the row counts without a server, and `--tiny` runs
one small scale. The release scripts share `release_cost.py` and `release_diff.py`.

## Setup

Python 3.12 and MySQL 8.0 produced the reported numbers. No credentials are
stored here; `src/config.py` reads them from the environment:

| variable | default | meaning |
|---|---|---|
| `CUTD_MYSQL_HOST` | `localhost` | server host |
| `CUTD_MYSQL_PORT` | `3306` | server port |
| `CUTD_MYSQL_USER` | `root` | user, allowed to set global variables |
| `CUTD_MYSQL_PASSWORD` | *(empty)* | password |
| `CUTD_MYSQL_DB` | `benchmarks` | database holding the benchmark relations |
| `CUTD_DELIVERY_DB` | `delivery_study` | database of the delivery designs |
| `CUTD_RELEASE_DB` | `release_study` | database of the real-release designs |
| `CUTD_MYSQL_CLIENT` | `mysql` | command-line client |
| `CUTD_FD_BASE` | `data/fd` | directory of the constraint sets |
| `CUTD_SCRATCH` | `.scratch` | bulk-load temporaries and the two windows of the real release |
| `CUTD_OWID_REPO` | `.scratch/owid` | clone of the publisher's repository |

### Benchmark relations

The relations are public profiling benchmarks and are not redistributed; their
mined constraint sets are in `data/fd/<reading>/FD/<file>.json`. The paper reports
the uncertainty reading of nulls (`null-uncertainty`).

| relation | file | attributes | rows | % null | mined FDs |
|---|---|---:|---:|---:|---:|
| biocase | `t_biocase_identification_r91800_c38` | 38 | 91,799 | 76.2 | 8 |
| breast | `breast` | 11 | 699 | 0.2 | 43 |
| bridges | `bridges` | 13 | 108 | 5.5 | 67 |
| claims | `claims` | 13 | 96,131 | 6.4 | 17 |
| dblp10k | `dblp10k` | 34 | 4,837 | 39.3 | 708 |
| echo | `echo` | 13 | 132 | 7.7 | 91 |
| hepatitis | `hepatitis` | 20 | 155 | 5.4 | 2,995 |
| hospital | `hospital` | 15 | 114,919 | 0.9 | 42 |
| ncvoter | `ncvoter` | 19 | 1,000 | 15.1 | 271 |
| pdbx | `pdbx` | 13 | 17,305,799 | 0.9 | 37 |
| routes | `routes` | 9 | 67,663 | 8.7 | 15 |
| weather | `china_weather` | 18 | 262,920 | 8.8 | 2,955 |

A constraint set is a JSON file `{"R": 11, "fds": [{"lhs": [0, 3], "rhs": [5, 7]}, ...]}`
over attributes `0 .. R-1`. For `dataset_stats.py`, load each relation into
`CUTD_MYSQL_DB` as two tables, `<relation>(nulleq)` and `<relation>(nulluc)`.

### The real release

```bash
git clone --filter=blob:none --no-checkout https://github.com/owid/covid-19-data .scratch/owid
python experiments/release_build.py
```

`release_build.py` fetches three editions of the OWID COVID table and writes the
mining window and the release window to the scratch directory.
`release_mine.py nulluc 4 .scratch/owid_mining_relation.pkl data/release/owid_fds.json 14`
mines the constraint set. The repository ships this file: mining again yields the
same FDs, but in no fixed order, and the synthesizers break ties by the order of
the input, so the designs of Table 7 are those over the shipped file.

Offline, run `release_rules.py` and then `release_skew.py`. With a server,
`release_live.py owid 3` runs the whole release window three times, and
`release_maps.py owid obs 3`, then `sq 1`, `exp2 1` and `cube 1` with
`POOL=8589934592`, are the timed runs of Table 7; both accept `--dry`.
`release_tables.py` reads their records.

## Measurement protocol

**Timing.** Times are medians of three repetitions that visit the designs
round-robin; each design is rebuilt, analyzed, timed and dropped. The buffer pool
is raised for a run and restored afterwards.

**Delivery (RQ1, RQ3 to RQ6).** The instances satisfy the declared rules by
construction, and the designs are synthesized from the declared rules. A design
stores deduplicated subschema projections with a unique index per minimal key;
non-key FDs are maintained by the workload's own statements. `--ops` issues 200
updates of a kind at every group and divides the time by 200; `--mixed`
interleaves refreshes with clean or conflicting completions; the default run
issues windows of 1,000 updates under the three profiles of Table 2, each drawn
once and issued against every design.

**Benchmark reducts (RQ2).** Heat is declared per attribute, and every rule
carries the heat of the attribute it determines. Under the graded declaration,
attributes not drawn hot keep heat 1. The worst single attribute tries every
attribute of a reduct and keeps the one on which SO and HA differ most.

**Real release (RQ7).** The mining window runs from the edition of 31 March 2024
to the base edition of 30 June 2024. The constraints are mined on its earlier
edition, and the heat of a rule `X -> A` is the number of its coalesced updates
that refresh `A` inside the scope, at least 1 (`release_cost.declare`). The
release window runs from the base edition, which the designs store, to the
edition of 19 August 2024, and every reported time is measured on its coalesced
updates. `E` adds columns by ascending null share while a third of the tuples of
the base edition stay complete on it (`release_cost.choose_E`).

Each subschema is kept equal to the projection of the edited relation and indexes
its minimal keys with plain indexes, since the release breaks some of the mined
rules. A non-key FD `X -> A` whose groups the release window rewrites whole is
maintained through a table over `XA` keyed by `X`, whose trigger rewrites the
group in the subschema.

A priced attribute with `n` updates in the scope gets grade
`l = 1 + min(9, floor(9 n / n_max))`; the designs run three times round-robin and
the reported time is the mean. Under a map `phi` (`l^2`, `2^l`, `l^3`), a priced
update at grade `l` is issued `1 + 2 floor(g / 2)` times, `g = phi(l) / (l phi(1))`,
alternating between the released and the earlier value; each design runs once
per map.

## Further results

**One update of each kind at a group of 3,000 (RQ1).** Rows each design rewrites
and time, medians of three repetitions; Figure 2 plots the times over `k`.

| update | rows SO | rows HA | SO / HA | time SO (ms) | time HA (ms) | SO / HA |
|---|---:|---:|---:|---:|---:|---:|
| reassignment | 6,006 | 8 | 751× | 159 | 3.14 | 51× |
| van swap | 7 | 2,005 | 0.0035× | 4.54 | 62.1 | 0.073× |
| completion, conflicting | 6,026.2 | 28.2 | 214× | 162 | 5.92 | 27× |
| completion, clean | 4 | 4 | 1.00× | 2.74 | 2.97 | 0.92× |
| insert | 3 | 3 | 1.00× | 2.71 | 2.61 | 1.04× |

**The sweep over the share `p` of hot attributes (RQ2).** On how many of the 12
reducts HA is strictly cooler than each baseline under the graded declaration
(means over 20 draws), and its largest excess in subschemata over SO; HA is never
hotter than either baseline.

| | | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HA cooler than SO | maximum | 4 | 5 | 5 | 6 | 5 | 5 | 6 | 4 | 5 | 5 |
| | total | 4 | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| HA cooler than 3NF | maximum | 5 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 7 |
| | total | 7 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| HA subschemata over SO (%) | | 5.0 | 5.8 | 4.5 | 4.5 | 4.7 | 3.9 | 4.6 | 3.7 | 3.4 | 6.4 |

On the eight smallest reducts, `total_heat_search.py --all` searches every
elimination order of the critical members and finds no lower total heat than HA's.

## License

MIT, see `LICENSE`.
