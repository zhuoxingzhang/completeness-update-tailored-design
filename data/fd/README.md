# Declared constraint sets

Atomic closures of functional dependencies mined from the twelve benchmark
relations of the paper, under two NULL readings:

- `null-equality/FD/`: null markers compare equal
- `null-uncertainty/FD/`: null markers are pairwise uncertain, the reading the paper reports

Each file is one relation. In the framework of the paper, a mined set is read as
the reduct `Sigma[E]` on which design operates, so the two directories bracket
how a completeness reading turns the same incomplete table into constraints.

Format:

```json
{"R": 11, "fds": [{"lhs": [0, 3], "rhs": [5, 7]}, ...]}
```

`R` is the number of attributes, attributes are `0 .. R-1`. Attribute names are
not part of these files; rules are identified by attribute index, in the paper as
well. `src/synthesis.py::load` splits every entry into single-right-hand-side
atomic FDs and computes the minimal keys.

Not every relation is profiled under both readings; `results/datasets.json`
records which readings exist per relation.
