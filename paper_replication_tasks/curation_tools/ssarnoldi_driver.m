## Curator-only driver for task scibench_replication_0022 (sketch-and-select
## Arnoldi condition-number growth). Faithful, verbatim-structure port of the
## 9 Krylov-basis-construction variants in the official
## paper_ssa_final_test1a.m / paper_ssa_final_test1b.m (identical files
## except the scalar `t`), scoped to exactly one matrix per call (the
## original scripts pin `ids = ids(46)`, a single-matrix 1-element loop; we
## drop the outer `for idj = 1:length(ids)` loop entirely since idj is
## always 1 here). fprintf progress dots and all plotting (`if withplots`)
## are removed; the inner algorithmic arithmetic/indexing/control flow of
## each variant is otherwise copied verbatim from the official source.
## Plain script (not a function file) -- see curation_tools/reim_driver.m's
## header comment for why: Octave silently no-ops function-wrapped driver
## scripts invoked by absolute path.

## Octave-compat paths MUST come first so maxk()/srht() resolve to the
## verified shims (curation_tools/ssarnoldi_octave_compat/), not to a
## missing maxk or the catastrophically slow original srht.m.
this_dir = fileparts(mfilename("fullpathext"));
addpath(fullfile(this_dir, "ssarnoldi_octave_compat"));


input_path = argv(){1};
case_data = jsondecode(fileread(input_path));

matrix = case_data.matrix;
p = case_data.p;
s = case_data.s;
t = case_data.t;
v0 = case_data.v0(:);
D = case_data.D(:);
perm = case_data.perm(:)';  % jsondecode gives a column; srht/myfwht expect perm as used by select(t,ind)=t(ind), shape-agnostic but keep row for readability

## jsondecode gives char arrays for JSON strings; condbound is either the
## string "inf" (JSON has no native Infinity) or a numeric scalar.
if ischar(case_data.condbound) && strcmp(case_data.condbound, "inf")
  condbound = inf;
else
  condbound = case_data.condbound;
end

## Load the pinned .mat file directly -- sidesteps ssget()'s websave-based
## download path (unavailable in Octave) and its 30-day index-staleness
## auto-refresh entirely. Problem.A is the same sparse matrix ssget(id).A
## would have produced.
matrices_dir = fullfile(this_dir, "ssarnoldi_matrices");
if strcmp(matrix, "Norris/torso3")
  load(fullfile(matrices_dir, "torso3.mat"));
elseif strcmp(matrix, "Bai/cryg10000")
  load(fullfile(matrices_dir, "cryg10000.mat"));
elseif strcmp(matrix, "Norris/torso1")
  load(fullfile(matrices_dir, "torso1.mat"));
else
  error("ssarnoldi_driver: unknown matrix identifier");
end
A = Problem.A;

N = size(A, 1);
## v0/D/perm are supplied directly in the input JSON (see
## ssarnoldi_common.py's module docstring for why: scientific.py's
## solve(task_id, value) dispatcher at evaluation time only ever sees the
## raw input JSON, with no access to a live Octave RNG state, so both sides
## must be given the same realized random draws rather than each
## regenerating their own via rng('default')). This driver therefore does
## NOT call rng('default') or draw its own v0/D/perm; it reconstructs the
## SRHT closure directly from the supplied D/perm using the exact same
## butterfly FWHT as the frozen ssarnoldi_octave_compat/srht.m (verified
## bit-identical -- see that file's CURATOR NOTE), rather than modifying
## that frozen/hash-pinned file to accept external D/perm.
s_embed = round(s * p);
select = @(x, ind) x(ind);
hS = @(x) (1 / sqrt(s_embed)) * select(myfwht_ext(D .* x), perm);

function z = myfwht_ext(a)
  n = length(a);
  N2 = 2^ceil(log(n) / log(2));
  z = zeros(N2, 1);
  z(1:n) = a;
  h = 1;
  while h < N2
    idx = (1:2*h:N2)';
    offs = (0:h-1);
    lo = reshape(idx + offs, [], 1);
    hi = lo + h;
    x = z(lo);
    y = z(hi);
    z(lo) = x + y;
    z(hi) = x - y;
    h = 2*h;
  end
end

basis_size = struct();
cnames = {"cond_truncated", "cond_sketch_truncate", "cond_select_pinv", ...
          "cond_select_pinv_recomp", "cond_select_corr", "cond_select_corr_pinv", ...
          "cond_select_omp", "cond_select_sp", "cond_select_greedy"};
snames = {"truncated", "sketch_truncate", "select_pinv", "select_pinv_recomp", ...
          "select_corr", "select_corr_pinv", "select_omp", "select_sp", "select_greedy"};

result = struct();
result.case_type = "arnoldi_cond_growth";

%% 1: Truncated Arnoldi (no sketching)
cnd = [];
jmax_ok = 0;
V = []; H = [];
V(:, 1) = v0/norm(v0);
c1 = [];
for j = 1:p
    c1(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    H(:,j) = 0;
    cols = max(1,j-t+1):j;
    h = V(:,cols)'*w;
    H(cols,j) = h;
    w = w - V(:,cols)*h;
    H(j+1,j) = norm(w);
    V(:,j+1) = w/H(j+1,j);
end
jmax = size(V, 2);
sz1 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz1 = j-1;
        break;
    elseif j == jmax
        sz1 = j;
    end
end
result.cond_truncated = c1(:)';
basis_size.truncated = sz1;

%% 2: Sketch + truncate
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c2 = [];
for j = 1:p
    c2(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    cols = max(1,j-t+1):j;
    h = SV(:,cols)'*sw;
    H(cols,j) = h;
    w = w - V(:,cols)*h;
    sw = sw - SV(:,cols)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz2 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz2 = j-1;
        break;
    elseif j == jmax
        sz2 = j;
    end
end
result.cond_sketch_truncate = c2(:)';
basis_size.sketch_truncate = sz2;

%% 3: Sketch and select Arnoldi (pinv)
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c3 = [];
for j = 1:p
    c3(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    coeffs = pinv(SV(:,1:j))*sw; % instead of \
    [~,ind] = maxk(abs(coeffs),t);
    h = coeffs(ind);
    H(ind,j) = h;
    w = w - V(:,ind)*h;
    sw = sw - SV(:,ind)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz3 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz3 = j-1;
        break;
    elseif j == jmax
        sz3 = j;
    end
end
result.cond_select_pinv = c3(:)';
basis_size.select_pinv = sz3;

%% 4: Sketch and select Arnoldi (pinv, recomputed)
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c4 = [];
for j = 1:p
    c4(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    coeffs = pinv(SV(:,1:j))*sw;
    [~,ind] = maxk(abs(coeffs),t);
    h = pinv(SV(:,ind))*sw; % recompute
    H(ind,j) = h;
    w = w - V(:,ind)*h;
    sw = sw - SV(:,ind)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz4 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz4 = j-1;
        break;
    elseif j == jmax
        sz4 = j;
    end
end
result.cond_select_pinv_recomp = c4(:)';
basis_size.select_pinv_recomp = sz4;

%% 5: Sketch and select Arnoldi (corr)
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c5 = [];
for j = 1:p
    c5(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    coeffs = SV(:,1:j)'*sw;
    [~,ind] = maxk(abs(coeffs),t);
    h = coeffs(ind);
    H(ind,j) = h;
    w = w - V(:,ind)*h;
    sw = sw - SV(:,ind)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz5 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz5 = j-1;
        break;
    elseif j == jmax
        sz5 = j;
    end
end
result.cond_select_corr = c5(:)';
basis_size.select_corr = sz5;

%% 6: Sketch and select Arnoldi (corr, pinv recompute)
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c6 = [];
for j = 1:p
    c6(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    coeffs = SV(:,1:j)'*sw;
    [~,ind] = maxk(abs(coeffs),t);
    h = pinv(SV(:,ind))*sw; % recompute
    H(ind,j) = h;
    w = w - V(:,ind)*h;
    sw = sw - SV(:,ind)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz6 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz6 = j-1;
        break;
    elseif j == jmax
        sz6 = j;
    end
end
result.cond_select_corr_pinv = c6(:)';
basis_size.select_corr_pinv = sz6;

%% 7: Orthogonal Matching Pursuit (OMP)
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c7 = [];
for j = 1:p
    c7(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    % OMP -- INITIALIZATION:
    r = sw;
    idx = zeros(0, 1);
    % Official source uses zeros(N, 0) (N = size(A,1)); MATLAB's horzcat
    % treats any Nx0 empty as concatenation-compatible with anything, but
    % Octave enforces strict row-count matching even for 0-column empties
    % (verified: [zeros(5,0), zeros(3,1)] errors in Octave, succeeds in
    % MATLAB). Use [] (true 0x0 empty, which Octave's horzcat DOES special-
    % case leniently) instead -- purely a dimension-placeholder difference,
    % SV_i is immediately overwritten column-by-column below and its
    % initial row count never enters any arithmetic.
    SV_i = [];
    x_i = zeros(0, 1);
    % OMP -- LOOP:
    for i = 1:min(j, t)
        corr = abs(SV(:,1:j)'*r);
        corr(idx) = 0;
        [~, idx_i] = max(corr);
        idx = [idx, idx_i];
        SV_i = [SV_i, SV(:, idx_i)];
        x_i = pinv(SV_i) * sw;
        r = sw - SV_i*x_i;
    end
    h = pinv(SV(:,idx)) * sw;
    H(idx,j) = h;
    w = w - V(:,idx)*h;
    sw = sw - SV(:,idx)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz7 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz7 = j-1;
        break;
    elseif j == jmax
        sz7 = j;
    end
end
result.cond_select_omp = c7(:)';
basis_size.select_omp = sz7;

%% 8: Subspace Pursuit (SP)
cnd = [];
jmax_ok = 0;
itsp = 1;  % number of iterations of SP
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c8 = [];
for j = 1:p
    c8(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;
    % SP -- INITIALIZATION:
    corr = abs(SV(:,1:j)'*sw);
    [~, idx_i] = maxk(corr, min(j, t));
    SV_i = SV(:, idx_i);
    x_i = pinv(SV_i) * sw;
    Sr = sw - SV_i * x_i;
    % SP -- LOOP:
    for isp = 1:itsp
        y = SV' * Sr;
        [~, idx2_i] = maxk(abs(y), t);
        idxU_i = union(idx_i, idx2_i);
        xU = pinv(SV(:, idxU_i)) * sw;
        [~, idx_rel] = maxk(abs(xU), t);
        idx_i = idxU_i(idx_rel);
        SV_i = SV(:, idx_i);
        x_i = pinv(SV_i) * sw;
        Sr = sw - SV_i * x_i;
    end
    h = pinv(SV(:,idx_i)) * sw;
    H(idx_i,j) = h;
    w = w - V(:,idx_i)*h;
    sw = sw - SV(:,idx_i)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz8 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz8 = j-1;
        break;
    elseif j == jmax
        sz8 = j;
    end
end
result.cond_select_sp = c8(:)';
basis_size.select_sp = sz8;

%% 9: Sketch and select Arnoldi (greedy) -- from NATARAJAN paper
cnd = [];
jmax_ok = 0;
sw = hS(v0); nsw = norm(sw);
V = []; SV = []; SAV = []; H = [];
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
c9 = [];
for j = 1:p
    c9(j) = cond(V(:,1:j));
    if mod(j, 10) == 0
        cnd(j) = cond(V(:, 1:j));
        if cnd(j) > condbound
            break;
        else
            jmax_ok = j;
        end
    end
    w = A*V(:,j);
    sw = hS(w);
    SAV(:,j) = sw;
    H(:,j) = 0;

    % get indices via greedy; see NATARAJAN paper
    ind = [];
    SV1 = SV; sw1 = sw;
    for it = 1:min(j, t)
        corr = SV1'*sw1;
        [~,i] = max(abs(corr));
        ind = [ ind; i];
        sw1 = sw1 - SV1(:,i)*(SV1(:,i)'*sw1);
        SV1 = SV1 - SV1(:,i)*(SV1(:,i)'*SV1);
        SV1 = SV1./vecnorm(SV1);
        SV1(:,ind) = 0;
    end

    h = pinv(SV(:,ind))*sw; % recompute
    H(ind,j) = h;
    w = w - V(:,ind)*h;
    sw = sw - SV(:,ind)*h;
    H(j+1,j) = norm(sw);
    V(:,j+1) = w/H(j+1,j);
    SV(:,j+1) = sw/H(j+1,j);
end
jmax = size(V, 2);
sz9 = jmax;
for j = jmax_ok+1:jmax
    cnd(j) = cond(V(:, 1:j));
    if cnd(j) > condbound
        sz9 = j-1;
        break;
    elseif j == jmax
        sz9 = j;
    end
end
result.cond_select_greedy = c9(:)';
basis_size.select_greedy = sz9;

result.basis_size = basis_size;

## Octave's jsonencode silently maps Inf/-Inf/NaN to JSON null instead of
## erroring (verified: jsonencode(struct('a',Inf)) -> {"a":null}), which
## would silently discard information cond() can legitimately produce for a
## singular/near-singular basis. Convert every non-finite numeric field to
## the literal string "Inf"/"-Inf"/"NaN" before encoding so no information
## is lost; ssarnoldi_common.py / verify_ssarnoldi_task.py must reverse this
## mapping when comparing. Plain loop (not a helper function) since local
## functions at the end of a script are invisible to the script's own
## top-level body in Octave -- see the addpath comment above.
for k = 1:numel(cnames)
  name = cnames{k};
  v = result.(name);
  cellv = cell(1, numel(v));
  for m = 1:numel(v)
    x = v(m);
    if isfinite(x)
      cellv{m} = x;
    elseif isnan(x)
      cellv{m} = "NaN";
    elseif x > 0
      cellv{m} = "Inf";
    else
      cellv{m} = "-Inf";
    end
  end
  result.(name) = cellv;
end
fn = fieldnames(basis_size);
for k = 1:numel(fn)
  v = basis_size.(fn{k});
  if ~isfinite(v)
    if isnan(v)
      basis_size.(fn{k}) = "NaN";
    elseif v > 0
      basis_size.(fn{k}) = "Inf";
    else
      basis_size.(fn{k}) = "-Inf";
    end
  end
end
result.basis_size = basis_size;

printf("%s", jsonencode(result));
