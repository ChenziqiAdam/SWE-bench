## Curator-only driver: calls the pinned (case_type=="fractional_fem"/
## "bdf2_fractional_heat" use FEM/*.m verbatim; all rEIM family case types
## use REIM.m patched only for Octave char==string dispatch compatibility,
## see curation_tools/patches/0021-reim-strcmp.patch) source verbatim.
## Reads one JSON case from the path given as the sole argument, writes one
## JSON result to stdout. Never modifies FEM/*.m.
## Plain script (not a function file) so Octave executes it unconditionally
## regardless of whether it is invoked by a relative or absolute path.

addpath(fullfile(fileparts(mfilename("fullpathext")), "FEM"));

## Anonymous function handles (not trailing `function ... end` blocks): Octave
## does not make local functions defined at the end of a script file visible
## to code in the script's own top-level body (only to other local
## functions), unlike MATLAB. Handles assigned to script-scope variables are
## visible everywhere in the script and avoid that restriction.
u_bdf2 = @(t, p) exp(-t/20) * cos(2*pi*t) * sin(pi*p(:,1)) .* sin(pi*p(:,2));
f_bdf2 = @(t, p, s) (-1/20 + (2*pi^2)^s) * u_bdf2(t, p) - 2*pi*exp(-t/20)*sin(2*pi*t) * sin(pi*p(:,1)) .* sin(pi*p(:,2));

input_path = argv(){1};
case_data = jsondecode(fileread(input_path));
case_type = case_data.case_type;

if strcmp(case_type, "rational_approx") || strcmp(case_type, "time_family_approx") || ...
   strcmp(case_type, "exp_family_approx") || strcmp(case_type, "precon_family_approx")

  a = case_data.a; b = case_data.b; M = case_data.M;
  if strcmp(case_type, "rational_approx")
    family = "power";
  elseif strcmp(case_type, "time_family_approx")
    family = "time";
  elseif strcmp(case_type, "exp_family_approx")
    family = "exp";
  else
    family = "precon";
  end
  [Xm, Bm, Gm] = REIM(M, a, b, family);

  Xtest = linspace(a, b, 5e5)';
  gtest = 1 ./ (Xtest + Bm');
  if strcmp(case_type, "rational_approx")
    s = case_data.s;
    ftest = Xtest .^ (-s);
    fXm = Xm .^ (-s);
  elseif strcmp(case_type, "time_family_approx")
    s = case_data.s; d = case_data.d; Lambda = case_data.Lambda;
    ftest = 1 ./ (Xtest .^ s + d / Lambda ^ s);
    fXm = 1 ./ (Xm .^ s + d / Lambda ^ s);
  elseif strcmp(case_type, "exp_family_approx")
    tau = case_data.tau;
    ftest = exp(-tau * Xtest);
    fXm = exp(-tau * Xm);
  else
    K = case_data.K;
    ftest = 1 ./ (Xtest .^ (-0.5) + K * Xtest .^ 0.5);
    fXm = 1 ./ (Xm .^ (-0.5) + K * Xm .^ 0.5);
  end
  coef = Gm \ fXm;
  Linf_error = norm(ftest - gtest * coef, "inf");

  result = struct("case_type", case_type, "xm", Xm, "bm", Bm, "G", Gm, ...
                   "Linf_error", Linf_error);

elseif strcmp(case_type, "fractional_fem")
  s = case_data.s; res = case_data.res(:); pol = case_data.pol(:);
  mesh_type = case_data.mesh_type; mesh_param = case_data.mesh_param;

  if strcmp(mesh_type, "uniform")
    [node, elem] = squaremesh([-1, 1, -1, 1], 0.25);
    for iter = 1:2
      [node, elem] = uniformrefine(node, elem);
    end
    for iter = 1:mesh_param
      [node, elem] = uniformrefine(node, elem);
    end
    Lambda = 1e6;
  else
    [node, elem] = squaremesh([-1, 1, -1, 1], 0.25);
    for iter = 1:2
      [node, elem] = uniformrefine(node, elem);
    end
    Nmax = mesh_param;
    theta = 6; maxit = 30;
    for iter = 1:maxit
      NV = size(node, 1);
      if NV < Nmax
        [~, area] = gradbasis(node, elem);
        mid = (node(elem(:,1),:) + node(elem(:,2),:) + node(elem(:,3),:)) / 3;
        dist = min(min(min(abs(mid(:,1)-1), abs(mid(:,1)+1)), abs(mid(:,2)-1)), abs(mid(:,2)+1));
        marker = (area > (theta / NV * log10(NV) * dist));
        [node, elem] = bisect(node, elem, marker);
      end
    end
    Lambda = 1e8;
  end

  T = myauxstructure(elem);
  [D, area] = gradbasis(node, elem);
  [A, Mm] = P1mat2d(D, area, elem);
  b_rhs = P1rhs2d(node, elem, area, @(p) ones(size(p,1),1));
  bv = unique(T.bdEdge);
  NV = size(node, 1);
  fv = setdiff(1:NV, bv)';
  AA = A(fv, fv); MM = Mm(fv, fv);
  rhs = b_rhs(fv) / Lambda ^ s;

  uh = zeros(NV, 1);
  x = zeros(length(fv), 1);
  np = length(pol);
  for j = 1:np
    x = x + res(j) * ((AA / Lambda + pol(j) * MM) \ rhs);
  end
  uh(fv) = x;

  m_terms = 2000;
  uexact = reim_u_exact(node, s, m_terms);
  e = uh - uexact;
  L2_error = sqrt(e' * Mm * e);

  result = struct("case_type", "fractional_fem", "s", s, "mesh_type", mesh_type, ...
                   "N", NV, "L2_error", L2_error);

elseif strcmp(case_type, "bdf2_fractional_heat")
  s = case_data.s; M = case_data.M; Lambda = case_data.Lambda;
  tol = case_data.tol; tau0_init = case_data.tau0; tend = case_data.tend;
  h_exp = case_data.mesh_h_exponent;

  [Xm, Bm, ~] = REIM(M, 1e-6, 1, "time");
  gx = 1 ./ (repmat(Xm, 1, length(Bm)) + Bm');

  tau = tau0_init; T = 0; tau0 = tau;
  np = length(Bm);
  ## Starting mesh is always h=0.125 (BDF2_FEM.m's own fixed choice); each
  ## uniformrefine halves h, so refine_iters = h_exp - 3 reaches final
  ## h = 0.125 / 2^refine_iters = 2^-h_exp (h_exp=8 reproduces the paper's
  ## own h=2^-8, matching BDF2_FEM.m's default 5 refinements from h=0.125).
  [node, elem] = squaremesh([0, 1, 0, 1], 0.125);
  refine_iters = h_exp - 3;
  for iter = 1:refine_iters
    [node, elem] = uniformrefine(node, elem);
  end
  NV = size(node, 1);
  aux = myauxstructure(elem);
  [D, area] = gradbasis(node, elem);
  [Stiff, Mass] = P1mat2d(D, area, elem);
  bv = unique(aux.bdEdge);
  fv = setdiff(1:NV, bv)';
  S = Stiff(fv, fv); Mm = Mass(fv, fv);

  LL = cell(np,1); UU = LL; PP = LL; QQ = LL;
  for i = 1:np
    [LL{i}, UU{i}, PP{i}, QQ{i}] = lu(S / Lambda + Bm(i) * Mm);
  end

  err = zeros(0,1); errest = zeros(0,1); Tdel = []; taudel = [];
  Uarray = cell(1,1); uexact_t = Uarray; fn = Uarray;
  uexact_t{1} = u_bdf2(0, node(fv,:));
  Uarray{1} = uexact_t{1};

  while T(end) <= tend
    j = length(T) + 1;
    uexact_t{j} = u_bdf2(T(end) + tau0, node(fv,:));
    rhs = P1rhs2d(node, elem, area, @(x0) f_bdf2(T(end) + tau0, x0, s));
    fn{j} = rhs(fv);

    fx = 1 ./ (Xm .^ s + 1 / (tau0 * Lambda ^ s));
    res_c = gx \ fx;
    Uj = Uarray{j-1};
    F = ((Mm * Uj) / tau0 + fn{j}) / Lambda ^ s;

    a_step = tau(end);
    k0 = (a_step + 2*tau0) / (tau0 * (a_step + tau0));
    k1 = -(a_step + tau0) / (a_step * tau0);
    k2 = tau0 / (a_step * (a_step + tau0));
    if j > 2
      Ui = Uarray{j-2};
      G_rhs = (-k1 * (Mm * Uj) - k2 * (Mm * Ui) + fn{j}) / Lambda ^ s;
    else
      G_rhs = F;
    end
    hx = 1 ./ (Xm .^ s + k0 / Lambda ^ s);
    res2_c = gx \ hx;

    U1 = zeros(length(fv), 1); U2 = U1;
    for i = 1:np
      solve = QQ{i} * (UU{i} \ (LL{i} \ (PP{i} * [F G_rhs])));
      U1 = U1 + res_c(i) * solve(:,1);
      U2 = U2 + res2_c(i) * solve(:,2);
    end
    if j == 2, U2 = U1; end
    errest(j-1) = sqrt((U1-U2)' * Mm * (U1-U2));
    if errest(j-1) <= tol
      tau(j-1) = tau0;
      T(j) = T(j-1) + tau0;
      Uarray{j} = U1;
      err(j) = sqrt((U1-uexact_t{j})' * Mm * (U1-uexact_t{j}));
      tau0 = 0.8 * tau0 * (tol / max(errest(j-1), 1e-6)) ^ 0.5;
      if T(j) + tau0 > tend
        if T(j-1) >= tend
          break
        end
        tau0 = tend - T(j);
      end
    else
      Tdel = [Tdel; T(j-1)+tau0];
      taudel = [taudel; tau0];
      tau0 = 0.8 * tau0 * (tol / errest(j-1)) ^ 0.5;
    end
    if tau0 <= 1e-4
      break
    end
  end

  result = struct("case_type", "bdf2_fractional_heat", "s", s, "T", T(:), ...
                   "err", err(:), "tau", tau(:), "Tdel", Tdel(:), "taudel", taudel(:));
else
  error("unsupported case_type");
end

printf("%s", jsonencode(result));
