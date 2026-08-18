# scibench_replication_0017

Implement the paper's balanced floating catchment area (BFCA) accessibility method and its conventional two-step floating catchment area (2SFCA) counterpart for a public bike-share network. The runner invokes `<entrypoint> --input <input.json> --output <new-output-dir>`; write `output.json`.

`data/travel_time_matrix.csv`, shipped alongside `cases/`, links population units to docking-station hubs. Columns: `UID` (population-unit id), `hub` (hub id), `travel_time` (walking minutes), `hub_type` (`Conventional` or `ERI`), `hub_status` (`Active` or `Deactivated`), `population` (population at the origin), `racks` (bicycle racks at the hub). Each `input.json` case supplies a `method` (`"b2sfca"` or `"c2sfca"`), a walking-time `threshold` in minutes, and a `hub_filter` selecting which hubs are open: `conventional_active` keeps only rows with `hub_type == "Conventional"` and `hub_status == "Active"`; `all_active` keeps every row with `hub_status == "Active"` regardless of `hub_type`. Restrict the table to rows matching `hub_filter` and to rows with `travel_time <= threshold` before computing accessibility.

Binary impedance: `w_ij = 1` if travel time from population unit `i` to hub `j` is at most `threshold`, else `0`.

## `b2sfca` (balanced)

Compute two balancing sums: `sum_b1_i = sum_j w_ij` (number of hubs unit `i` can reach) and `sum_b2_j = sum_i w_ij` (number of population units hub `j` can reach). Drop any row where `sum_b1_i = 0` or `sum_b2_j = 0` (no feasible pairing). Balanced weights are `w1_ij = w_ij / sum_b1_i` and `w2_ij = w_ij / sum_b2_j`.

Level of service at hub `j`: `los_j = racks_j / sum_i (population_i * w1_ij)`.

Accessibility at population unit `i`: `accessibility_i = sum_j (los_j * w2_ij)`.

## `c2sfca` (conventional)

Keep only rows with `w_ij = 1` (no balancing). Level of service at hub `j`: `los_j = racks_j / sum_i (population_i * w_ij)`. Accessibility at population unit `i`: `accessibility_i = sum_j (los_j * w_ij)`.

## Output

Write JSON with these exact keys:

- `hub`: array of hub ids with nonzero level of service, sorted ascending.
- `level_of_service`: `los_j` for each id in `hub`, same order.
- `population_unit`: array of population-unit ids with nonzero accessibility, sorted ascending.
- `accessibility`: `accessibility_i` for each id in `population_unit`, same order.

Use float64 arithmetic throughout. A population unit or hub that is filtered out (dropped for `b2sfca`, or has no reachable rows) must not appear in the output arrays.
