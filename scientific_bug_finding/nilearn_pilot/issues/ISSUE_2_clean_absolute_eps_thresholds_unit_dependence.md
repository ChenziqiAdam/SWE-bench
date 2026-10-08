# [BUG] `signal.clean`: confound regression and `zscore_sample` silently do nothing for data in small units (absolute `eps` thresholds)

### Is there an existing issue for this?

I searched open and closed issues and PRs (`clean confounds scale`, `standardize_confounds small`, `zscore_sample eps`,
`confounds QR`, `standardize constant eps`); no report of unit-dependent behaviour. Related but different: #563
(rank-deficient confounds), #3497 (non-aggressive denoising).

### Environment

nilearn `main` (d6c09c9a4, 2026-10-02; `signal.py` unchanged since), Python 3.13, numpy 2.5, scipy 1.18.

### Expected behavior

`clean` is linear/scale-equivariant: multiplying the signals and the confounds by the same positive constant
(i.e. changing units) must not change which components are removed, and `standardize="zscore_sample"` is documented
to give unit variance for any non-constant column.

### Current behavior

```python
import numpy as np
from nilearn.signal import clean

rng = np.random.default_rng(0)
x = rng.standard_normal((200, 1))
conf = rng.standard_normal((200, 1))
y = x + 3 * conf

for scale in (1.0, 1e-12, 1e-16, 1e-18):
    z = clean(x * scale, detrend=False, standardize="zscore_sample")
    r = clean(y * scale, confounds=conf * scale, detrend=False, standardize=None)
    print(scale, z.std(ddof=1), abs(np.corrcoef(r[:, 0], conf[:, 0])[0, 1]))
```

```
1       1.0        3.8e-16
1e-12   1.0        1.0e-15
1e-16   9.6e-17    0.953     <- not unit variance; confound NOT removed
1e-18   9.6e-19    0.953
```

Below roughly 2e-16 the column is not scaled to unit variance, and the confound (which explains most of the signal)
is left in the "cleaned" data with no warning. Data stored in small SI units (e.g. femto/atto-scale quantities)
are affected.

### Cause

Two absolute float64 thresholds in `nilearn/signal.py` that are not relative to the data scale:

1. `standardize_signal`: `std[std < np.finfo(np.float64).eps] = 1.0` treats any column with std < 2.2e-16 as
   constant, so it is left unscaled (the same constant is used for the `psc` mean test).
2. `clean`, confound projection: `Q = Q[:, np.abs(np.diag(R)) > np.finfo(np.float64).eps * 100.0]` drops
   confound directions whose QR diagonal is below 2.2e-14 in absolute terms. Since the default
   `standardize_confounds=True` goes through (1), small-amplitude confounds are not rescaled first and are then
   discarded here. With `standardize_confounds=False` the confounds are divided by their maximum and the result is
   correct.

### Suggested fix

Make both tests relative: compare `std` with `eps * max|column|` (or with the column mean scale), and compare the
QR diagonal with `eps * max(shape) * abs(R[0, 0])` as in `numpy.linalg.matrix_rank`. At minimum, warn when columns
are dropped.
