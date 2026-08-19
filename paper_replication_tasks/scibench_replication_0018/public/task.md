# scibench_replication_0018

Implement the paper's a posteriori time series aggregation framework for the six-region
capacity expansion planning model with storage, and reproduce its six aggregation schemes
(A-F). The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write
finite `output.json`.

## Planning model

Implement the six-region system exactly as specified in the paper's Appendix B (nomenclature
Table B.3, objective and constraints B.1-B.14, technology/cost parameters Table B.4): baseload,
peaking and wind generation technologies; transmission between six regions; and storage, solved
as a linear/mixed-integer program that minimizes annualized install cost plus generation cost
subject to demand balance, transmission and storage dynamics constraints. Demand and wind
generation-potential time series are hourly for 1980-2017; a run resamples `ts_reduction_num_years`
years (with replacement) to build a 3-year base time series, then rolls the last 184 days to the
front (reduces the impact of an empty initial storage level). To avoid degenerate/non-unique
solutions, perturb each region's install/generation costs by a small amount (under 0.1%) that is
distinct per region and technology; the exact perturbation is not prescribed by the paper and does
not need to match the reference implementation bit-for-bit -- only the resulting capacities and
unserved energy need to fall within the stated tolerances.

Solve two kinds of runs for each aggregation method: a `get_design_estimate` run (plan mode,
aggregated 3-year time series, free capacities) and a `get_operate_variables` run (operate mode,
full non-aggregated time series, capacities fixed at the design estimate's values, unmet demand
allowed).

## Aggregation schemes A-F

All schemes aggregate the 3-year (1096-day) base time series into 30 representative days using
Ward's-linkage hierarchical clustering on z-normalized daily vectors (each day is one vector of
24 hourly values per clustering column).

- **A**: cluster on demand/wind columns only (no stratification); representative day = cluster
  mean.
- **B**: same clustering as A; representative day = medoid (real day closest to the cluster mean
  in normalized space).
- **C**: like B, but first mark the 3 regional-max-demand days and 3 regional-min-wind days (6
  days total) as "extreme" and cluster them separately from the remaining "regular" days into 6
  and 24 representative days respectively.
- **D**: like B, but stratify using each day's total unmet demand (`gen_unmet_total`, summed over
  regions) from a prior method-B `get_operate_variables` run on the full time series: rank days by
  daily total unmet demand, mark the top 5% (capped at the number of days with any unmet demand)
  as "extreme", and split representative days 15/15 between extreme and regular.
- **E**: like D, but stratify using each day's total generation cost (`generation_cost`, daily sum)
  instead of unmet demand.
- **F**: like E, but also add each region's storage (dis)charge decisions (`gen_storage_region2`,
  `gen_storage_region5`, `gen_storage_region6`) as clustering columns (in addition to the demand/wind
  columns).

## Output

For each of the six methods (keys `"A"`-`"F"`), report:

- `capacity_totals`: `[cap_baseload_total, cap_peaking_total, cap_wind_total,
  cap_storage_energy_total, cap_transmission_total]` (GW/GW/GW/GWh/GW) from the
  `get_design_estimate` run.
- `unserved_energy`: total unmet demand (MWh) summed across the full time series from the
  `get_operate_variables` run.

```json
{"methods": {"A": {"capacity_totals": [..5 floats..], "unserved_energy": <float>}, "...": "...through F"}}
```
