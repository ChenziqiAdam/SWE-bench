"""Independent QR implementation of the paper's core row-wise recovery."""

from __future__ import annotations

import numpy as np

try:
    from .fixed_sparsity_core_common import validate_case
except ImportError:
    from fixed_sparsity_core_common import validate_case


def solve(value):
    matrix, mask, sketch = validate_case(value)
    observations = matrix @ sketch
    recovered = np.zeros_like(matrix)
    for row in range(matrix.shape[0]):
        columns = np.flatnonzero(mask[row])
        if columns.size:
            design = sketch[columns].T
            q, r = np.linalg.qr(design, mode="reduced")
            recovered[row, columns] = np.linalg.solve(r, q.T @ observations[row])
    if not np.isfinite(recovered).all():
        raise ValueError("non-finite recovery")
    return {"A_tilde": recovered.tolist()}
