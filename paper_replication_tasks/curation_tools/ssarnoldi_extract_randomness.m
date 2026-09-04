## Curator-only helper for task scibench_replication_0022: extracts the
## realized v0/D/perm arrays that ssarnoldi_driver.m's RNG draws would
## produce for a given N/p/s, WITHOUT modifying the frozen/hash-pinned
## curation_tools/ssarnoldi_octave_compat/srht.m. Replicates the exact same
## rng('default') + randn/randi/randperm call sequence srht.m performs
## internally (v0=randn(N,1) in the driver, then inside srht: D=randi([0
## 1],n,1)*2-1, then perm=randperm(N2,s_embed)) -- since srht.m's own
## Rademacher-sign and permutation draws happen in a fixed, known order
## immediately after v0's draw with no other RNG consumption in between,
## re-issuing the identical draw sequence after the identical rng('default')
## reset reproduces identical values deterministically. Used only by
## build_ssarnoldi_task.py's independent-audit step, never by the adapter
## itself (which relies on srht.m directly and never needs D/perm exposed).
##
## Usage: octave-cli ssarnoldi_extract_randomness.m <input.json> <output.json>
## Writes v0 (Nx1), D (Nx1, +-1), perm (1-indexed as MATLAB emits it) to output.json.

input_path = argv(){1};
output_path = argv(){2};
case_data = jsondecode(fileread(input_path));

matrix = case_data.matrix;
p = case_data.p;
s = case_data.s;

this_dir = fileparts(mfilename("fullpathext"));
matrices_dir = fullfile(this_dir, "ssarnoldi_matrices");
if strcmp(matrix, "Norris/torso3")
  load(fullfile(matrices_dir, "torso3.mat"));
elseif strcmp(matrix, "Bai/cryg10000")
  load(fullfile(matrices_dir, "cryg10000.mat"));
elseif strcmp(matrix, "Norris/torso1")
  load(fullfile(matrices_dir, "torso1.mat"));
else
  error("ssarnoldi_extract_randomness: unknown matrix identifier");
end
N = size(Problem.A, 1);

rng('default');
v0 = randn(N, 1);

## Replicate srht.m's internal draws verbatim (same order, same arguments)
## without calling srht() itself, so D/perm are directly observable here.
s_embed = round(s * p);
D = randi([0 1], N, 1) * 2 - 1;
N2 = 2^ceil(log(N) / log(2));
perm = randperm(N2, s_embed);

result = struct();
result.v0 = v0;
result.D = D;
result.perm = perm;  % 1-indexed (MATLAB/Octave native); consumer must subtract 1 for 0-indexed use
fid = fopen(output_path, "w");
fputs(fid, jsonencode(result));
fclose(fid);
