#!/usr/bin/env python3
"""Curator reference for the explicit-panel SUR-SLM 3SLS contract."""

import argparse
import json
from pathlib import Path

import numpy as np

p = argparse.ArgumentParser(); p.add_argument("--input", required=True); p.add_argument("--output", required=True); a = p.parse_args()
v = json.loads(Path(a.input).read_text()); Y = np.asarray(v["y"], float); X = np.asarray(v["x"], float); W = np.asarray(v["w"], float)
G, N, P = X.shape; shared = set(v["shared_beta_columns"]); columns = []; lookup = {}
for j in range(P):
    owners = [None] if j in shared else list(range(G))
    for owner in owners:
        k = len(columns); columns.append((owner, j))
        for g in range(G):
            if owner is None or owner == g: lookup[g, j] = k
B = np.zeros((G*N, len(columns)))
for k, (owner, j) in enumerate(columns):
    for g in range(G):
        if owner is None or owner == g: B[g*N:(g+1)*N, k] = X[g, :, j]
intercepts = sorted({lookup[g, 0] for g in range(G)}); B0 = np.delete(B, intercepts, axis=1); L = np.kron(np.eye(G), W)
H = np.column_stack((B, L @ B0, L @ L @ B0)); y = Y.ravel(); wy = (L @ y).reshape(G, N); E = np.zeros((G*N, G))
for g in range(G): E[g*N:(g+1)*N, g] = wy[g]
Z = np.column_stack((E, B)); Zh = H @ np.linalg.lstsq(H, Z, rcond=None)[0]; q = np.linalg.lstsq(Zh, y, rcond=None)[0]
R = (y - Zh @ q).reshape(G, N).T; R -= R.mean(axis=0); S = R.T @ R / (N-1); O = np.kron(np.linalg.inv(S), np.eye(N)); C = np.linalg.inv(Zh.T @ O @ Zh); theta = C @ Zh.T @ O @ y; se = np.sqrt(np.maximum(np.diag(C), 0))
beta = np.array([[theta[G + lookup[g,j]] for j in range(P)] for g in range(G)]); beta_se = np.array([[se[G + lookup[g,j]] for j in range(P)] for g in range(G)])
fit = (Z @ theta).reshape(G,N); corr2 = lambda u,z: float(np.corrcoef(u,z)[0,1]**2); direct=np.empty((G,P-1)); total=np.empty_like(direct)
for g in range(G):
    M=np.linalg.inv(np.eye(N)-theta[g]*W); direct[g]=beta[g,1:]*np.trace(M)/N; total[g]=beta[g,1:]*np.sum(M)/N
result={"beta":beta.tolist(),"beta_standard_errors":beta_se.tolist(),"rho":theta[:G].tolist(),"rho_standard_errors":se[:G].tolist(),"r2_by_equation":[corr2(Y[g],fit[g]) for g in range(G)],"pooled_r2":corr2(y,fit.ravel()),"direct_effects":direct.tolist(),"indirect_effects":(total-direct).tolist(),"total_effects":total.tolist()}
out=Path(a.output); out.mkdir(parents=True,exist_ok=True); (out/"output.json").write_text(json.dumps(result,allow_nan=False))
