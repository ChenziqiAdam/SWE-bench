## Curator-only driver: calls the pinned seccurv_* functions verbatim.
## Reads one JSON case from the path given as the sole argument, writes one
## JSON result to stdout. Never modifies the official source files.
## Plain script (not a function file) so Octave executes it unconditionally
## regardless of whether it is invoked by a relative or absolute path.

input_path = argv(){1};
case_data = jsondecode(fileread(input_path));
metric = case_data.metric;

if strcmp(metric, "stiefel_canonical") || strcmp(metric, "stiefel_euclidean")
  A1 = case_data.A1; B1 = case_data.B1; A2 = case_data.A2; B2 = case_data.B2;
  if strcmp(metric, "stiefel_canonical")
    seccurv = seccurv_Stiefel_canon(A1, B1, A2, B2);
  else
    seccurv = seccurv_Stiefel_euclid(A1, B1, A2, B2);
  end
elseif strcmp(metric, "grassmann")
  seccurv = seccurv_Grassmann(case_data.B1, case_data.B2);
elseif strcmp(metric, "so_n")
  seccurv = seccurv_SOn(case_data.X, case_data.Y);
else
  error("unsupported metric");
end

result = struct("metric", metric, "seccurv", seccurv);
printf("%s", jsonencode(result));
