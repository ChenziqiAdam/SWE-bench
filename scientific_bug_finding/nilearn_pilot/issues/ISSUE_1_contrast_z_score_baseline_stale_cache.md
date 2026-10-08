# [BUG] `Contrast.z_score(baseline=...)` returns wrong (sign-flipped) z-scores after a previous call with another baseline

### Is there an existing issue for this?

I searched open and closed issues and PRs for `z_score baseline`, `Contrast baseline`, `one_minus_pvalue` and
`Contrast.z_score`; nothing describes this (closest: #2567, which introduced `one_minus_pvalue_`).

### Environment

nilearn `main` (d6c09c9a4, 2026-10-02; `contrasts.py` unchanged on `main` as of 2026-10-08), Python 3.13, numpy 2.5, scipy 1.18.

### Expected behavior

`Contrast.z_score(baseline)` returns the z-score of the test "contrast equals `baseline`". The result should
depend only on the contrast and on `baseline`, not on which baseline was requested before on the same object.

### Current behavior

```python
import numpy as np
from nilearn.glm import Contrast

effect = np.array([[2.0, 4.0]])   # contrast estimate at two voxels
variance = np.array([1.0, 1.0])

c = Contrast(effect, variance, dof=40, stat_type="t")
print(c.z_score())                      # [1.94047209 3.64642659]   (correct, baseline 0)
print(c.z_score(baseline=3.0))          # [1.94047209 0.98765465]   <-- wrong

print(Contrast(effect, variance, dof=40, stat_type="t").z_score(baseline=3.0))
                                        # [-0.98765465 0.98765465]  (correct)
```

For voxel 0 the effect (2) is below the baseline (3), so the z-score must be negative. The same object returns
`+1.94`, i.e. the value for baseline 0: wrong sign and wrong magnitude. Only the first call on a fresh object is right.

### Cause

`Contrast.z_score` (nilearn/glm/contrasts.py) recomputes `p_value_` when the baseline changes but only computes
`one_minus_pvalue_` when it is `None`:

```python
if self.p_value_ is None or self.baseline != baseline:
    self.p_value_ = self.p_value(baseline)
if self.one_minus_pvalue_ is None:                      # <- never refreshed for a new baseline
    self.one_minus_pvalue_ = self.one_minus_pvalue(baseline)
z_score(self.p_value_, one_minus_pvalue=self.one_minus_pvalue_)
```

`glm._utils.z_score` uses `p_value_` for the upper tail and `one_minus_pvalue_` for the lower tail, so after the
first call the two arrays belong to different baselines and the result mixes them.

### Suggested fix

Refresh both cached arrays when the baseline changed (checked before `p_value` updates `self.baseline`):

```python
stale = self.baseline != baseline
if self.p_value_ is None or stale:
    self.p_value(baseline)
if self.one_minus_pvalue_ is None or stale:
    self.one_minus_pvalue(baseline)
```

With this change the repeated call above returns `[-0.98765465, 0.98765465]`, identical to the fresh object.
