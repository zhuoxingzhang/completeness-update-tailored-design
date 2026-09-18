# The real release

The constraint set of the real-release study (RQ7): the COVID table of Our World
in Data, https://github.com/owid/covid-19-data, as its editions of 30 June 2024
(commit `257e9651175ff5b90b05845509e2d5ed0a9e46ac`) and 19 August 2024 (commit
`f0d53320b19703cf565940d8269181a8423d7032`) stand in the publisher's repository.

`owid_fds.json` holds the minimal functional dependencies with at most four
determinant attributes that hold on the earlier edition under the uncertainty
reading of nulls, mined by `experiments/release_mine.py`. The format is that of
`data/fd/` with the attribute names added:

```json
{"R": 23, "attrs": ["location", "continent", ...], "fds": [{"lhs": [0], "rhs": [1]}, ...]}
```

The relation itself is not redistributed: `experiments/release_build.py` reads the
two editions from a clone of the publisher's repository and writes it to the
scratch directory, together with the workload, which is the difference between
the two editions. The relation keeps the country-days that carry the four core
surveillance indicators (the reproduction rate, the stringency index, and the
smoothed new cases and new deaths per million) in the earlier edition, and the
twenty-three columns the constraint set names, in that order.
