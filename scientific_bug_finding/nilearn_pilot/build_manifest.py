"""Build sanitizers.json from LAW_CANDIDATES.md (single source of truth for the laws)."""
import json, re, sys
doc = open("LAW_CANDIDATES.md").read()
SRC = {  # id -> (source, symbol, quantity)
 "SIG-001": ("nilearn/signal.py", "_detrend", "linear-detrended time series"),
 "SIG-003": ("nilearn/signal.py", "standardize_signal", "percent signal change"),
 "SIG-004": ("nilearn/signal.py", "butterworth", "Butterworth cut-off gain"),
 "SIG-006": ("nilearn/signal.py", "create_cosine_drift", "DCT-II drift basis"),
 "SIG-007": ("nilearn/signal.py", "create_cosine_drift", "high-pass cut-off frequency"),
 "SIG-008": ("nilearn/signal.py", "high_variance_confounds", "CompCor components"),
 "GLM-001": ("nilearn/glm/regression.py", "OLSModel.fit", "least-squares residuals"),
 "GLM-002": ("nilearn/glm/regression.py", "RegressionResults.r_square", "coefficient of determination"),
 "GLM-003": ("nilearn/glm/_utils.py", "z_score", "z-score of a tail probability"),
 "GLM-004": ("nilearn/glm/contrasts.py", "Contrast.p_value", "t/F contrast p-value"),
 "GLM-005": ("nilearn/glm/contrasts.py", "compute_contrast", "t-contrast statistic"),
 "GLM-006": ("nilearn/glm/contrasts.py", "compute_contrast", "F-contrast statistic"),
 "GLM-007": ("nilearn/glm/contrasts.py", "_compute_fixed_effects_params", "fixed-effects pooled estimate"),
 "GLM-008": ("nilearn/glm/contrasts.py", "Contrast.z_score", "contrast z-score"),
 "HRF-001": ("nilearn/glm/first_level/hemodynamic_models.py", "orthogonalize", "orthogonalised regressors"),
 "HRF-002": ("nilearn/glm/first_level/hemodynamic_models.py", "compute_regressor", "BOLD regressor"),
 "HRF-003": ("nilearn/glm/first_level/hemodynamic_models.py", "compute_regressor", "BOLD regressor"),
 "HRF-004": ("nilearn/glm/first_level/hemodynamic_models.py", "_generic_time_derivative", "HRF time-derivative kernel"),
 "THR-001": ("nilearn/glm/thresholding.py", "threshold_stats_img", "false discovery rate"),
 "THR-002": ("nilearn/glm/thresholding.py", "threshold_stats_img", "multiple-comparison threshold"),
 "THR-003": ("nilearn/image/image.py", "threshold_img", "cluster-extent threshold"),
 "CON-001": ("nilearn/connectome/connectivity_matrices.py", "cov_to_corr", "correlation matrix"),
 "CON-002": ("nilearn/connectome/connectivity_matrices.py", "ConnectivityMeasure._fit_transform", "connectivity matrices"),
 "CON-003": ("nilearn/connectome/connectivity_matrices.py", "ConnectivityMeasure._fit_transform", "partial correlation"),
 "CON-004": ("nilearn/connectome/connectivity_matrices.py", "sym_matrix_to_vec", "vectorised symmetric matrix"),
 "CON-005": ("nilearn/connectome/connectivity_matrices.py", "vec_to_sym_matrix", "symmetric matrix from vector"),
 "CON-006": ("nilearn/connectome/connectivity_matrices.py", "_geometric_mean", "Frechet mean of SPD matrices"),
 "CON-007": ("nilearn/connectome/connectivity_matrices.py", "ConnectivityMeasure._fit_transform", "tangent-space embedding"),
 "CON-008": ("nilearn/connectome/group_sparse_cov.py", "_group_sparse_covariance", "group-sparse precision graph"),
 "CON-009": ("nilearn/connectome/group_sparse_cov.py", "_group_sparse_covariance", "estimated precision matrices"),
 "MU-002": ("nilearn/mass_univariate/_utils.py", "calculate_tfce", "TFCE statistic"),
 "MU-003": ("nilearn/mass_univariate/_utils.py", "calculate_tfce", "TFCE statistic"),
 "MU-004": ("nilearn/mass_univariate/_utils.py", "null_to_p", "permutation p-value"),
 "MU-005": ("nilearn/mass_univariate/_utils.py", "calculate_cluster_measures", "cluster size and mass"),
 "IMG-001": ("nilearn/image/image.py", "smooth_array", "smoothed image intensity"),
 "IMG-002": ("nilearn/image/image.py", "smooth_array", "smoothing kernel width"),
 "IMG-003": ("nilearn/image/resampling.py", "resample_img", "resampled image geometry"),
 "IMG-004": ("nilearn/regions/signal_extraction.py", "signals_to_img_labels", "region signals"),
 "IMG-005": ("nilearn/regions/signal_extraction.py", "signals_to_img_maps", "map-based region signals"),
}
def clean(t): return re.sub(r"\s+", " ", t).strip()
out = []
blocks = re.findall(r"\*\*((?:[A-Z]+-\d{3})(?: / [A-Z]+-\d{3})?) ([^*]+?)\.\*\*(.*?)(?=\n\n\*\*|\n\n---|\Z)", doc, re.S)
for ids, title, body in blocks:
    idl = [i.strip() for i in ids.split("/")]
    if len(idl) == 2:
        idl = [idl[0], idl[1]]
    m = re.search(r"Pre: (.*?)\. ?Law: (.*?)\. ?Obs: (.*?)\. ?Alarm: (.*?)\. ?Fam `(\w+)`(?:\.| )(?:\s*Why: (.*))?", clean(body))
    if not m: sys.exit(f"parse failure: {ids}")
    pre, law, obs, alarm, fam, why = m.groups()
    for k, i in enumerate(idl):
        if len(idl) == 2: obs_k = "return of sym_matrix_to_vec" if k == 0 else "return of vec_to_sym_matrix (diagonal=None)"
        else: obs_k = obs
        src, sym, qty = SRC[i]
        out.append({"id": "NL-" + i, "category": "scientific", "family": fam, "source": src,
                    "symbol": sym, "scientific_quantity": qty, "precondition": pre,
                    "invariant": law, "observation_point": obs_k, "alarm": alarm,
                    "rationale": (why or title).rstrip(".") + "."})
ids = [s["id"] for s in out]
assert len(ids) == len(set(ids)) == 42, (len(ids), len(set(ids)))
json.dump(out, open("/tmp/claude-501/nl_sanitizers_list.json", "w"), indent=1)
print(len(out), "sanitizers;", len({s["family"] for s in out}), "families")
