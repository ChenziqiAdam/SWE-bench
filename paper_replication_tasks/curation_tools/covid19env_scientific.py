"""Independent 3-stage least squares (3SLS) spatial-SUR-SLM implementation for
task 0020, written from spsur 1.0.1.3's own documented method (Angulo, Lopez,
Minguez & Mur, "spsur: Spatial Seemingly Unrelated Regression Models") and the
paper's stated design (Paez, Lopez, Menezes, Cavalcanti & Galdino da Rocha Pitta
2021, Geographical Analysis 53(3):397-421, Sections "SUR Models"):

  Stage 1: OLS of the stacked regressor matrix Z (each equation's Wy_g slot plus
           its X_g columns) on an instrument matrix H = [W^1 X_noIntercept,
           W^2 X_noIntercept, X] (maxlagW=2 for an "slm" model), giving Z_hat.
  Stage 2: 2SLS residuals from Y on Z_hat estimate the GxG cross-equation
           covariance matrix Sigma (sample covariance across time/space of each
           equation's residual series).
  Stage 3: Feasible GLS using Omega^-1 = I_T kron Sigma^-1 kron I_N:
           beta_3sls = (Z_hat' Omega^-1 Z_hat)^-1 Z_hat' Omega^-1 Y

Equality restrictions (GDPpc and Older coefficients held constant across the 30
time-period equations) are imposed the way README.Rmd builds them: rather than
reimplementing spsur's general R/b restriction-projection matrix, the two
restricted regressor columns are pooled into a single shared column (equivalent
for this specific restriction), which is what the R2/b2 restriction matrices in
covid19env_driver.R encode.

Used only to audit the pinned official spsurtime() gold in promote_official.py;
never a gold generator.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PANEL_PATH = FIXTURES_DIR / "covid19env_panel.csv"
WMAT_PATH = FIXTURES_DIR / "covid19env_wmat.csv"
PANEL_SHA256 = "a581a9fdc4aeb521186b2deaae0b5b5b582bec9b8133703d84e3986bb3eb3efd"
WMAT_SHA256 = "e34d2eca6e76852d075d94c2df110fbde1e5ca4f1cad4257dc7db6e2c48b10e5"

LAG_COLUMNS = {
    "lag8": ("Humidity_lag8", "Mean_Temp_lag8", "Sunshine_Hours_lag8"),
    "lag11": ("Humidity_lag11", "Mean_Temp_lag11", "Sunshine_Hours_lag11"),
    "lag11w": ("Humidity_lag11w", "Mean_Temp_lag11w", "Sunshine_Hours_lag11w"),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fixtures() -> tuple[pd.DataFrame, np.ndarray, list[int]]:
    for path, expected in ((PANEL_PATH, PANEL_SHA256), (WMAT_PATH, WMAT_SHA256)):
        if not path.is_file():
            raise RuntimeError(f"archived covid19env fixture is missing: {path.name}")
        if _digest(path) != expected:
            raise RuntimeError(f"archived covid19env fixture hash mismatch: {path.name}")
    panel = pd.read_csv(PANEL_PATH)
    wmat_df = pd.read_csv(WMAT_PATH, index_col=0)

    # spsurtime() filters the pdata.frame (province-major sorted) by one date at
    # a time, so each equation's X/Y rows come out in province-name-alphabetical
    # order. W, however, is built separately from provinces_spain's native sf row
    # order (ID_INE-ascending, which is exactly the row order already stored in
    # this fixture) and applied purely positionally (no name-matching) via
    # (IT %x% IG %x% W) %*% Y. The official pipeline therefore multiplies W's
    # k-th row against whichever province is alphabetically k-th, not the same
    # province -- a latent row-order mismatch in the official code that must be
    # reproduced exactly (not "fixed") to match its actual gold output.
    first_date = panel["Date"].min()
    province_order = panel.loc[panel["Date"] == first_date, "ID_INE"].tolist()
    W = wmat_df.to_numpy(dtype=float)
    return panel, W, province_order


def _build_design(panel: pd.DataFrame, province_order: list[int], lag_spec: str) -> tuple[np.ndarray, list[str], int, int]:
    """Return X (N*Tm x G*7) equation-block-diagonal regressor matrix (no Wy
    columns yet), regressor names per equation, N, and G=Tm (one equation per
    day, per README.Rmd's SUR-over-time design)."""
    humidity, temp, sunshine = LAG_COLUMNS[lag_spec]
    dates = sorted(panel["Date"].unique())
    G = len(dates)
    N = len(province_order)

    regressor_names = [
        "(Intercept)", "log(GDPpc)", "log(Older)", "log(Density)", "Transit",
        f"log({humidity})", f"log({temp})", f"log({sunshine} + 0.1)",
    ]
    p_g = len(regressor_names)

    panel_indexed = panel.set_index(["ID_INE", "Date"])
    blocks = []
    for date in dates:
        rows = panel_indexed.xs(date, level="Date").reindex(province_order)
        x_g = np.column_stack([
            np.ones(N),
            np.log(rows["GDPpc"].to_numpy()),
            np.log(rows["Older"].to_numpy()),
            np.log(rows["Density"].to_numpy()),
            rows["Transit"].to_numpy(dtype=float),
            np.log(rows[humidity].to_numpy()),
            np.log(rows[temp].to_numpy()),
            np.log(rows[sunshine].to_numpy() + 0.1),
        ])
        blocks.append(x_g)

    # Stack equations: block-diagonal X of shape (N*G, G*p_g), y-major then g-major
    # to match R's array(Y, c(N, G, Tm=1)) fill order used by spsur's get_Sigma.
    X_full = np.zeros((N * G, G * p_g))
    for g, x_g in enumerate(blocks):
        X_full[g * N:(g + 1) * N, g * p_g:(g + 1) * p_g] = x_g

    y_blocks = []
    for date in dates:
        rows = panel_indexed.xs(date, level="Date").reindex(province_order)
        y_blocks.append(np.log(rows["Incidence"].to_numpy()))
    y_full = np.concatenate(y_blocks)

    return X_full, regressor_names, N, G, y_full, p_g


def _apply_restriction(X_full: np.ndarray, regressor_names: list[str], N: int, G: int, p_g: int) -> tuple[np.ndarray, list[str]]:
    """Pool the log(GDPpc) and log(Older) columns (indices 1, 2 within each
    equation's p_g block) across all G equations into one shared column each,
    equivalent to spsur3sls's R2/b2 equality restriction for this design."""
    keep_local = [0, 3, 4, 5, 6, 7]  # drop indices 1 (GDPpc), 2 (Older) per-equation
    pooled_gdppc = X_full[:, [g * p_g + 1 for g in range(G)]].sum(axis=1, keepdims=True)
    pooled_older = X_full[:, [g * p_g + 2 for g in range(G)]].sum(axis=1, keepdims=True)

    cols = [pooled_gdppc, pooled_older]
    names = ["log(GDPpc)_1", "log(Older)_1"]
    for g in range(G):
        for local in keep_local:
            cols.append(X_full[:, [g * p_g + local]])
            names.append(f"{regressor_names[local]}_{g + 1}")
    X_restricted = np.hstack(cols)
    return X_restricted, names


def _spatial_lag_operator(W: np.ndarray, G: int) -> np.ndarray:
    """I_G kron W, applied to a (N*G,) vector stacked equation-major (matches
    spsur's (IT %x% IG %x% W) with Tm=1)."""
    N = W.shape[0]
    return np.kron(np.eye(G), W)


def solve(case: dict[str, Any]) -> dict[str, Any]:
    lag_spec = case["lag_spec"]
    restricted = bool(case["restricted"])
    if lag_spec not in LAG_COLUMNS:
        raise ValueError("lag_spec must be lag8, lag11, or lag11w")

    panel, W, province_order = _load_fixtures()
    X_full, regressor_names, N, G, y, p_g = _build_design(panel, province_order, lag_spec)
    W_full = _spatial_lag_operator(W, G)

    if restricted:
        X_reg, names = _apply_restriction(X_full, regressor_names, N, G, p_g)
    else:
        X_reg = X_full
        names = [f"{regressor_names[local]}_{g + 1}" for g in range(G) for local in range(p_g)]

    n_regressor_cols = X_reg.shape[1]
    n_rho = G

    # Z: [Wy_1 .. Wy_G | X_reg columns], Wy_g nonzero only in that equation's rows
    Z = np.zeros((N * G, n_rho + n_regressor_cols))
    Wy = W_full @ y
    for g in range(G):
        Z[g * N:(g + 1) * N, g] = Wy[g * N:(g + 1) * N]
    Z[:, n_rho:] = X_reg

    # Instruments: original X_full (with intercept) plus W^1, W^2 of X_full's
    # non-intercept columns, restricted the same way as the regressors.
    if restricted:
        X_noint_full, noint_names = _apply_restriction(X_full, regressor_names, N, G, p_g)
        # X_restr already excludes nothing by intercept; drop pooled+per-eq intercepts
        intercept_local_positions = [i for i, nm in enumerate(names) if nm.startswith("(Intercept)")]
    else:
        intercept_local_positions = [i for i, nm in enumerate(names) if nm.startswith("(Intercept)")]
    X_noint = np.delete(X_reg, intercept_local_positions, axis=1)

    H_blocks = [X_reg]
    lag = X_noint
    for _ in range(2):
        lag = W_full @ lag
        H_blocks.insert(0, lag)
    H = np.hstack(H_blocks)

    # Stage 1: OLS of Z on H
    coef1, *_ = np.linalg.lstsq(H, Z, rcond=None)
    Z_hat = H @ coef1

    # Stage 2: 2SLS residuals -> Sigma (GxG), using R's array(resid, c(N,G,Tm=1))
    # fill order: equation blocks stacked equation-major, matching our y/Z layout.
    coef_2sls, *_ = np.linalg.lstsq(Z_hat, y, rcond=None)
    resid_2sls = y - Z_hat @ coef_2sls
    R_mat = resid_2sls.reshape(G, N).T  # (N, G)
    Sigma = np.cov(R_mat, rowvar=False, ddof=1)
    Sigma_inv = np.linalg.inv(Sigma)

    # Stage 3: FGLS with Omega^-1 = Sigma^-1 kron I_N (Tm=1)
    Omega_inv = np.kron(Sigma_inv, np.eye(N))
    ZtOZ = Z_hat.T @ Omega_inv @ Z_hat
    ZtOy = Z_hat.T @ Omega_inv @ y
    beta_3sls = np.linalg.solve(ZtOZ, ZtOy)
    cov_3sls = np.linalg.inv(ZtOZ)
    se_3sls = np.sqrt(np.diag(cov_3sls))

    rho = beta_3sls[:n_rho]
    coefficients = beta_3sls[n_rho:]
    std_errors = se_3sls[n_rho:]

    y_hat = Z @ beta_3sls
    resid = y - y_hat
    pooled_r2 = float(np.corrcoef(y, y_hat)[0, 1] ** 2)
    r2_by_equation = []
    for g in range(G):
        sl = slice(g * N, (g + 1) * N)
        r2_by_equation.append(float(np.corrcoef(y[sl], y_hat[sl])[0, 1] ** 2))

    return {
        "coefficients": {name: float(v) for name, v in zip(names, coefficients)},
        "std_errors": {name: float(v) for name, v in zip(names, std_errors)},
        "rho": [float(v) for v in rho],
        "r2_by_equation": r2_by_equation,
        "pooled_r2": pooled_r2,
    }
