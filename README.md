# Completeness- and Update-Tailored Database Design — Artifact

Implementation, declared constraint sets, workload generators, and result files
for the paper *Completeness- and Update-Tailored Database Design*.

The paper introduces normal forms that bound, over the completeness scope of an
application, the **update heat** a design materializes redundantly, together with
a synthesis algorithm that minimizes the maximal subschema heat among the designs
synthesis reaches. This repository lets you re-run every experiment.

## What is here

```
src/
  synthesis.py     the synthesis engine: FD primitives, minimal keys, the
                   non-key FDs and heat of a schema, and one skeleton carrying
                   every objective. Run it directly for a self-check.
  config.py        paths and database credentials, all overridable by environment
                   variables. The only file you may need to touch.
experiments/       one script per research question (table below)
data/fd/           the declared constraint sets: atomic closures mined from the
                   benchmark relations under both NULL readings
data/release/      the constraint set of the real release, mined on the edition
                   of 30 June 2024 of the COVID table of Our World in Data
results/           the result files behind the paper's tables and figures
```

### The three objectives

All experiments compare three synthesizers that share one front end — the reduct
`Sigma[E]`, its atomic closure, and the key computations — so that the objective
is the only variable:

| key   | objective |
|-------|-----------|
| `3nf` | classical lossless, dependency-preserving 3NF synthesis |
| `so`  | structure-optimal: fewest procedurally maintained FDs per subschema |
| `ha`  | heat-aware: Algorithm 1 of the paper |

`so` and `ha` differ in one line — which redundant critical schemata are
eliminated first. That line is what the experiments measure.

## Quick start (no database needed)

```bash
python src/synthesis.py
```

This runs the engine's self-check on the delivery running example of the paper.
It verifies that every objective returns a lossless, dependency-preserving
design, and reproduces the separation of Figure 1: the structure-optimal design
has maximal subschema heat 8, the heat-aware design has 2.

```bash
python experiments/delivery_example.py
```

prints the six-tuple snapshot of Table 1 and both designs of Figure 1 subschema
by subschema, with their minimal keys and the rows each one stores, and checks
the snapshot against the rules it illustrates.

```bash
python experiments/delivery_schema.py --orders
```

shuffles the atomic closure 200 times and reports the design each objective
returns on each listing. Both objectives break ties by input order, so this is
what says whether a separation rests on the criterion or on the tie break.

```bash
python experiments/reduct_frontend.py
```

reproduces Table 3 (maximal and total design heat on the reducts of
real incomplete relations) and the sweep over `p` below from the shipped
constraint sets, sweeping the graded declaration over ten values of `p`, from 0.1 to 1 in
steps of 0.1, with twenty draws each. About two hours on 18 workers, dominated
by hepatitis under equality; set `CUTD_WORKERS` to match your machine. The per-synthesis times it records are
inflated by parallel contention; the synthesis times quoted in the paper were measured with
`CUTD_WORKERS=1`. Writes `results/rq2_reducts.json`. The paper reports the
uncertainty reading (`nulluc`) of the fourteen relations only; the shipped
constraint sets, the scripts, and the result files carry both readings, so the
equality rows can be restored without a rerun.

## Reproducing the experiments

| Script | Produces |
|---|---|
| `experiments/delivery_example.py` | Table 1 and Figure 1 |
| `experiments/delivery_trace.py` | Examples "Heat of the delivery subschemata" and "Synthesis on the delivery reduct": the eliminations each objective performs, the number it ranks by, and the heat of the reduct and of every subschema a design keeps |
| `experiments/delivery_schema.py` | the schema, the instance generator and the offline cost model the other delivery scripts import; `--orders` for the order study above, `--costs` for the rows one update of each kind rewrites, `--window` for `results/rq7_window_model.json`; its rates are Table 2 |
| `experiments/delivery_live.py --ops` | Figure 2 and the table of one update of each kind below (RQ1, over group depths; `results/rq1_operations.json`) † |
| `experiments/delivery_live.py --mixed` | Figure 4 and the first row of Table 5 (RQ3, refreshes with a growing completion share; `results/rq3_mixed.json`) † |
| `experiments/delivery_live.py --reads` | Table 5 (RQ3, reconstruction, key lookups, history, storage; `results/rq3_reads.json`) † |
| `experiments/delivery_live.py` | Table 7 and Figure 6 (RQ6, one maintenance window under three rate profiles; `results/rq7_window.json`) † |
| `experiments/delivery_curves.py` | Figure 5 and Table 6 (RQ4 and RQ5, skew, completeness drift, and the four declarations; `results/rq4_rq5_curves.json`) |
| `experiments/delivery_tables.py` | every figure and table of the delivery study as LaTeX, from the result files above |
| `experiments/reduct_frontend.py` | Table 3 (RQ2, maximal and total design heat at `p = 0.5`), the sweep over `p` below, and Figure 3(a); `results/rq2_reducts.json` |
| `experiments/sweep_skew.py` | Figure 3(b) (RQ2, worst single hot rule) |
| `experiments/redundancy_study.py` | Table 4 (RQ2, redundant value occurrences) † |
| `experiments/release_build.py` | the relation and the workload of the real release, read from a clone of the publisher's repository (RQ7; see below) |
| `experiments/release_mine.py` | the constraint set of the real release, `data/release/owid_fds.json`, mined on that relation |
| `experiments/release_classes.py` | the class of designs each objective may return on the real release, priced offline, and the extremes the paper runs (`results/rq7_real_classes.json`, `results/rq7_real_orders.json`) |
| `experiments/release_rules.py` | the rules each timed design stores away from a key, and the total heat row of Table 8 (`results/rq7_real_rules.json`) |
| `experiments/release_live.py` | the whole window run live on the three designs, every subschema indexed on its minimal keys and on the determinants of its non-key FDs; the window statistics of Table 8 (`results/rq7_real_live.json`) † |
| `experiments/release_maps.py` | the timed runs of Table 8 and Figure 8: the priced updates under the observed and the re-numbered levels, keys indexed alone and non-key FDs refreshed through trigger tables (`results/rq7_real_maps.json`) † |
| `experiments/release_tables.py` | Table 8 and Figure 8 as LaTeX, from the three records above |
| `experiments/release_skew.py` | Figure 7 (RQ7, the refreshes every rule of the reduct receives) |
| `experiments/real_workload.py` | null control on routes and the heat-channel runs on ncvoter, from the weather study that the submitted paper no longer reports (`results/rq6_end_to_end.json`) † |
| `experiments/weather_census.py` | counting census over the fat rules of weather, weather study (`results/rq6_weather_census.json`) † |
| `experiments/weather_rules.py` | live runs of the five separating weather rules on their storing subschemata, weather study (`results/rq6_weather_rules_*.json`) † |
| `experiments/weather_rows.py` | rows one refresh of the 20 deepest groups rewrites, counted offline on the storing subschemata, weather study (`results/rq6_weather_rows.json`) |
| `experiments/weather_full.py` | full materialization, then the update and query sequences on the widest-gap rule, weather study (`results/rq6_weather_full.json`) † |
| `experiments/weather_recon.py` | reconstruction re-measured on the designs `weather_full.py` leaves in place, weather study (`results/rq6_weather_reconstruction.json`) † |
| `experiments/dataset_stats.py` | the benchmark table below (dataset dimensions) † |

`weather_rules.py`, `weather_full.py` and `weather_recon.py` share the front end
`weather_common.py`; the four `delivery_live.py` studies share `delivery_schema.py`
and `delivery_curves.py`. The `release_*.py` scripts share `release_cost.py`, which
holds the relation, the coalescing of the workload into updates and the offline
price of a design, and `release_pool.py`, the pool of elimination orders the class
search starts from; `release_diff.py` prices a window as the exact projection diff
every subschema undergoes, rows updated, inserted and deleted.

† needs a MySQL server; see below.

Scripts marked † build and populate MySQL databases of their own and drop them
again. They assume a server they may create and drop schemas on; point them at a
scratch instance rather than a production one.

`delivery_live.py` accepts `--dry` for the row counts alone, which needs no
server and is the fastest way to see the mechanism, `--verify` to run one window
on both designs and compare the reconstructed relations by count and checksum,
and `--tiny` for a single small scale.

## Measurement protocol

The paper's setup names the datasets, the baselines and the three heat
declarations; the protocol behind the reported numbers is here. Timings in the
paper are medians of three repetitions that visit the designs round-robin, and
the three repetitions of a controlled window differ by at most 5% of the median
(`results/rq7_window.json` keeps all three).

**Instances.** The delivery studies generate an instance of the schema of the
running example: the zones rotate through the branches and the vans through the
zones, and Armstrong witnesses for the independencies are appended in a disjoint
value range (Beeri, Dowd, Fagin and Statman, *JACM* 31(1), 1984; Langeveldt and
Link, *Inf. Syst.* 35(3), 2010). `delivery_schema.py` recomputes the instance's
own dependencies over all seven attributes before every run and compares them
against the declared closure, so the instance satisfies the declared rules and no
others. Each design is materialized as deduplicated subschema projections, with
every minimal key a unique index; non-key FDs are maintained by the workload's
own statements rather than by triggers, so that the two designs differ only in
what they store. Heat values are verified against brute force.

**Workloads.** `delivery_live.py --ops` issues one update of each kind at a time;
`--mixed` interleaves refreshes with completions drawn from an all-clean or an
all-conflicting pool at a share `gamma`; the default run issues whole maintenance
windows of 1,000 updates under the three rate profiles of Table 2. Every window
is drawn once and then priced offline and issued against each design, so the two
designs run the same window.

**Timing.** The buffer pool is raised for a run and restored afterwards. Inside
each repetition the designs are rebuilt, analyzed, timed and dropped round-robin,
and every reported time is the median of three repetitions; running one design to
completion before the next lets checkpoint activity dominate. Rows reported by
the server agree with the offline cost model within 1%, and after a window both
designs reconstruct to the same tuple count and checksum (`--verify`).

**Heat declarations.** Under the graded declaration, modes that are not drawn hot
stay at the baseline heat of 1. The adversarial declaration searches up to 300
candidate rules per reduct and keeps the one on which the two optimizing designs
differ most.

**The real release (RQ7).** The window is the pair of editions of 30 June and
19 August 2024 of the COVID table of Our World in Data: the relation is the
earlier edition, the constraints are mined on it, and the workload is the
difference between the two editions, coalesced into the updates that produce
it. The heat of a rule `X -> A` is the number of cells of `A` the window
refreshes inside the scope, and a rule the window does not refresh keeps the
default heat 1, since heats are positive (`HEAT_FLOOR` in the scripts; 0
reproduces the runs recorded before 18 September 2026). Each subschema is
kept equal to the projection of the edited relation,
since the release splits and merges stored rows as well as rewriting them.
Every subschema indexes its minimal keys and no other attributes. A non-key FD
`X -> A` whose groups the window rewrites whole, without splitting or merging
stored rows, is maintained through a table over `XA` keyed by `X`: a priced
update refreshes that table, and a trigger on the table rewrites the group in
the subschema, which has no index on `X`. Every design executes the window,
and its priced updates are timed; the reported times are means over the three
repetitions, since the round-robin puts each design once in every position.
Under the observed levels, a priced attribute refreshed `n` times in the scope
receives the level `l = 1 + min(9, floor(9 n / n_max))`, where `n_max` is the
largest such count. To multiply the priced updates, one of the maps `l^2`,
`2^l` and `l^3` re-numbers these levels: under a map `phi`, a priced update of
an attribute at level `l` is issued `1 + 2 floor(g / 2)` times, where
`g = phi(l) / (l phi(1))`, alternating between the released value and the
earlier one, so that its frequency follows the new level and the window still
ends in the released edition. The designs stay those of Table 8 of the paper,
and under each map every design runs the window once. The designs are the
extremes of the classes `release_classes.py` prices, with `POOL=250 SWAPS=300
HA_SWAPS=300 TARGET=priced`: 3NF at its priced worst (order `keep7_3`), SO at its
hottest (`h+c+`), HA at its priced best (`haswap164`); `results/rq7_real_picks.json`
holds the three orders. The search that returned them ran before the heats were
made positive, and so did the timed runs. Under the floor of 1 the search returns
the same designs for 3NF and SO, and for HA the order `haswap239`, whose static
price of the priced updates is 0.15 per cent below the timed design's
(`results/rq7_real_classes.json`); the order `haswap164` itself exchanges two cold
subschemata that no priced update touches, so its priced statements and rows are
those of Table 8 either way, while its whole-window statements differ from
`results/rq7_real_live.json` by 1.2 per cent. `HEAT_FLOOR=0` rebuilds the timed
designs exactly.

**The weather study**, an end-to-end study on the weather relation that the
submitted paper no longer reports, is kept here with its scripts and results.
`E` takes the attributes in ascending order of their null
counts, for as long as at least a third of the tuples stay `E`-complete. Every
rule of the reduct carries unit heat and the one rule under study carries 10, so
no declaration is fitted to the data. Each sequence starts from a quiesced buffer
pool and is undone by its exact inverse, with row counts and checksums asserted
equal across designs. Refresh passes are timed in 15 rounds that visit the designs
round-robin, and every refresh comparison is a two-sided rank test over those
rounds. Reported size is the engine's table and index size summed over a design's
subschemata. Rules with more than four determinant attributes were sampled, 300 of them, and none averaged above 1.3 tuples per group, so the enumeration stops at four. A null control on routes, whose three designs coincide, returns every pairwise rank test above p = 0.48, while timing the designs in build order separates the identical designs by 3% at p < 0.01, which is why every comparison is round-robin and gaps of a few percent are read as noise. Reconstruction joins are anchored at the widest subschema; anchoring them at the narrow key subschema breaches the bound on intermediate growth.

## Setup

```bash
python -m pip install -r requirements.txt
```

Python 3.12 and MySQL 8.0 were used for the reported numbers. Nothing depends on
the versions beyond that.

### Database configuration

No credentials are stored in this repository. `src/config.py` reads them from the
environment, with portable defaults:

| variable | default | meaning |
|---|---|---|
| `CUTD_MYSQL_HOST` | `localhost` | server host |
| `CUTD_MYSQL_PORT` | `3306` | server port |
| `CUTD_MYSQL_USER` | `root` | user |
| `CUTD_MYSQL_PASSWORD` | *(empty)* | password |
| `CUTD_MYSQL_DB` | `benchmarks` | database holding the benchmark relations |
| `CUTD_DELIVERY_DB` | `delivery_study` | database the delivery study builds its designs in |
| `CUTD_RELEASE_DB` | `release_study` | database the real-release study builds its designs in |
| `CUTD_MYSQL_CLIENT` | `mysql` | path to the command-line client |
| `CUTD_FD_BASE` | `data/fd` | directory of the constraint sets |
| `CUTD_SCRATCH` | `.scratch` | directory for bulk-load temporaries and the built relation of the real release |
| `CUTD_OWID_REPO` | `.scratch/owid` | clone of the publisher's repository the real release is read from |

For example:

```bash
export CUTD_MYSQL_PASSWORD=secret
export CUTD_MYSQL_DB=benchmarks
```

The delivery study raises the buffer pool for a run and restores it afterwards,
which needs a server the configured user may set global variables on.

### Benchmark relations

The mined **constraint sets** are shipped here in full, under `data/fd/`. The
underlying **relations** are the public profiling benchmarks used throughout the
data-profiling literature and are not redistributed. Their dimensions, the
share of null cells, and the size of the FD set mined on each under the
no-information reading (`dataset_stats.py`):

| relation | attributes | rows | % null | mined FDs |
|---|---:|---:|---:|---:|
| biocase | 38 | 91,799 | 76.2 | 8 |
| breast | 12 | 699 | 0.2 | 43 |
| bridges | 14 | 108 | 5.1 | 67 |
| claims | 14 | 96,131 | 5.9 | 17 |
| dblp10k | 35 | 4,837 | 38.2 | 708 |
| diabetic | 31 | 101,766 | 6.1 | 97,341 |
| echo | 14 | 132 | 7.1 | 91 |
| hepatitis | 21 | 155 | 5.1 | 2,995 |
| hospital | 16 | 114,919 | 0.8 | 42 |
| ncvoter | 20 | 1,000 | 14.3 | 271 |
| pdbx | 14 | 17,305,799 | 0.8 | 37 |
| routes | 10 | 67,663 | 7.8 | 15 |
| uniprot | 31 | 96,996 | 23.7 | 5,794 |
| weather | 19 | 262,920 | 8.4 | 2,955 |

diabetic and uniprot, whose atomic closures exceed 10,000 FDs, are left out of
the paper's tables; the other twelve are its reducts. To run the scripts marked †,
load them into the database named by `CUTD_MYSQL_DB`, one table per relation.

The operational studies expect the two NULL readings as separate tables, named
`<relation>(nulleq)` and `<relation>(nulluc)`, matching the two constraint-set
directories. `experiments/redundancy_study.py` documents the calibration step
that aligns a loaded table with its mined constraint set.

The delivery studies (`delivery_live.py`, `delivery_curves.py`) need no benchmark
data at all: they generate an instance of the delivery schema that satisfies the
declared rules and, by the Armstrong witnesses appended in a disjoint value
range, nothing more. `delivery_schema.py` recomputes the instance's own
dependencies over all seven attributes and compares them against the closure
before every run.

### The real release

The relation of the real release is not redistributed either. `release_build.py`
reads its two editions from a clone of the publisher's repository, which keeps
every edition of the table in its history, and writes the relation and the
workload to the scratch directory (about 90 MB):

```bash
git clone --filter=blob:none --no-checkout https://github.com/owid/covid-19-data .scratch/owid
python experiments/release_build.py
```

The clone is 41 MB, and the two editions are fetched on demand. The constraint
set is shipped in `data/release/`; `release_mine.py nulluc 4 .scratch/owid_relation.pkl
data/release/owid_fds.json 14` mines it again. The offline scripts then run in
the order `release_classes.py` (`POOL=250 SWAPS=300 HA_SWAPS=300 TARGET=priced`,
about a quarter of an hour), `release_rules.py`, `release_skew.py` and
`release_tables.py`; the last two read the shipped records and need no relation.
With a server, `release_live.py owid 3` runs the whole window three times and
`release_maps.py owid obs 3`, then `sq 1`, `exp2 1` and `cube 1` with
`POOL=8589934592`, are the timed runs of Table 8; both accept `--dry` to build
and price the statements without a server.

## Data format

A constraint set is a JSON file

```json
{"R": 11, "fds": [{"lhs": [0, 3], "rhs": [5, 7]}, ...]}
```

where `R` is the number of attributes, attributes are `0 .. R-1`, and each entry
is an FD. `synthesis.load()` splits these into single-right-hand-side atomic FDs
and computes the minimal keys. Attribute names are not part of the benchmark
files: rules are identified by attribute index throughout, in the paper as well.

## Results

`results/` holds the JSON output behind each table and figure, so the numbers in
the paper can be checked without re-running anything. File names match the table
above. The real release has five: `rq7_real_live.json` (the whole window run
live, with the window statistics), `rq7_real_maps.json` (the timed runs under
the four numberings of the levels), `rq7_real_rules.json` (the designs' non-key
rules and heats), `rq7_real_classes.json` (the class search under the heat floor)
and `rq7_real_picks.json` (the three elimination orders the timed designs are
synthesized from); `rq7_real_visit.json` names the visiting orders of the
single passes under the re-numbered levels, and `rq7_real_summary.json` holds the
numbers of Table 8 and Figure 8 as `release_tables.py` assembles them.

### One update of each kind at a group of 3,000 (RQ1)

The rows each delivery design rewrites for one update of each kind at a group of
`k = 3,000`, a mean over the operations issued where fractional, and the time it
takes, medians of three round-robin repetitions (`delivery_live.py --ops`,
`results/rq1_operations.json`); Figure 2 of the paper plots the times over `k`.
SO is the structure-optimal design and HA the heat-aware one:

| update | rows SO | rows HA | SO / HA | time SO (ms) | time HA (ms) | SO / HA |
|---|---:|---:|---:|---:|---:|---:|
| reassignment | 6,006 | 8 | 751× | 164 | 5.76 | 29× |
| van swap | 7 | 2,005 | 0.0035× | 7.86 | 36.6 | 0.21× |
| completion, conflicting | 6,011.6 | 13.6 | 444× | 167 | 8.92 | 19× |
| completion, clean | 4 | 4 | 1.00× | 5.46 | 5.53 | 0.99× |
| insert | 3 | 3 | 1.00× | 5.32 | 5.50 | 0.97× |

### The sweep over the share `p` of hot rules (RQ2)

On how many of the 12 reducts heat-aware synthesis is strictly cooler than each
baseline under the graded declaration, means over 20 draws at each `p`, and its
largest excess in subschemata over the structure-optimal design; it is never
hotter than either baseline (`reduct_frontend.py`, `results/rq2_reducts.json`):

| | | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HA cooler than SO | maximum | 6 | 7 | 6 | 6 | 6 | 6 | 5 | 6 | 6 | 5 |
| | total | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 |
| HA cooler than 3NF | maximum | 7 | 8 | 7 | 7 | 7 | 8 | 7 | 7 | 8 | 7 |
| | total | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| HA subschemata over SO (%) | | 1.1 | 1.1 | 1.2 | 1.2 | 1.3 | 1.5 | 1.3 | 1.3 | 1.3 | 1.3 |

## License

MIT, see `LICENSE`.
