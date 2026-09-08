## Minimal numeric-input adaptation of the "Sketch and select Arnoldi (pinv)"
## block in paper_ssa_final_test1a.m at commit 6e145837e4696bd9e26b3d6160b37f97e4188e10.
## Selection, projection, sketch normalization, and SAV recording retain the
## official block's arithmetic. JSON I/O and explicit A/v0/S/p/t replace its
## matrix download, random SRHT, plotting, and condition-growth wrapper.

input_path = argv(){1};
addpath(fullfile(fileparts(mfilename("fullpathext")), "ssarnoldi_octave_compat"));
case_data = jsondecode(fileread(input_path));
A = case_data.matrix;
v0 = case_data.start_vector(:);
S = case_data.sketch_matrix;
p = case_data.iterations;
t = case_data.selection_budget;
hS = @(x) S*x;

sw = hS(v0); nsw = norm(sw);
V = zeros(rows(A), p+1); SV = zeros(rows(S), p+1);
SAV = zeros(rows(S), p); H = zeros(p+1, p);
SV(:,1) = sw/nsw; V(:,1) = v0/nsw;
for j = 1:p
  w = A*V(:,j);
  sw = hS(w);
  SAV(:,j) = sw;
  coeffs = pinv(SV(:,1:j))*sw;
  [~,ind] = maxk(abs(coeffs),min(j,t));
  h = coeffs(ind);
  H(ind,j) = h;
  w = w - V(:,ind)*h;
  sw = sw - SV(:,ind)*h;
  H(j+1,j) = norm(sw);
  if !isfinite(H(j+1,j)) || H(j+1,j) <= 64*eps*max(1,norm(SAV(:,j)))
    error("numerical breakdown");
  end
  V(:,j+1) = w/H(j+1,j);
  SV(:,j+1) = sw/H(j+1,j);
end
result = struct("basis", V, "hessenberg", H, "sketched_basis", SV, "sketched_products", SAV);
printf("%s", jsonencode(result));
