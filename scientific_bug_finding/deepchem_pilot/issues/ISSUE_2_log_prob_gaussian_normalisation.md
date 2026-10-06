# `ElectronSampler.log_prob_gaussian` returns a wrong log-density unless `sigma` has one entry per electron

### Setup

DeepChem master (`455d07f3e`, 2.8.1.dev), NumPy 2.5, SciPy 1.18, Python 3.12.

### Expected behaviour

The docstring says `sigma` is "Same shape as x or should be broadcastable to
x" and that the method returns the log probability of a Gaussian. The result
should equal the sum of independent normal log-densities over the coordinates
of each batch element, up to the constant `-(N/2) log(2 pi)` the method omits,
for every `sigma` shape the docstring allows.

### Actual behaviour

```python
import numpy as np
from scipy.stats import norm
from deepchem.utils.electron_sampler import ElectronSampler

s = ElectronSampler(np.zeros((1, 3)), lambda x: np.zeros(len(x)))
rs = np.random.RandomState(0)
b, n = 2, 4
y, mu = rs.randn(b, n, 1, 3), rs.randn(b, n, 1, 3)
const = -(n * 3) / 2 * np.log(2 * np.pi)

def truth(sig):
    sig = np.broadcast_to(sig, y.shape)
    return norm.logpdf(y, mu, sig).sum(axis=(1, 2, 3))

for shape in [(b, n, 1, 1), (b, n, 1, 3), (b, 1, 1, 1)]:
    sig = rs.uniform(0.2, 2.0, shape)
    print(shape, s.log_prob_gaussian(y, mu, sig) - (truth(sig) - const))
```

```
(2, 4, 1, 1) [-7.1e-15  0.0e+00]
(2, 4, 1, 3) [2.752617   5.01275648]      # sigma with the same shape as y
(2, 1, 1, 1) [-2.31234948  3.03685184]    # one sigma per batch element
```

With one `sigma` per electron the result is exact; with the two other shapes
the docstring permits it is off by a sigma-dependent amount.

### Cause

```python
numer = np.sum((-0.5 * ((y - mu)**2) / (sigma**2)), axis=(1, 2, 3))
denom = y.shape[-1] * np.sum(np.log(sigma), axis=(1, 2, 3))
```

`denom` is meant to be `sum over all coordinates of log(sigma)`. It multiplies
by `y.shape[-1]` and then sums over `sigma`'s own axes, which is only correct
when `sigma` has exactly one entry per electron (`(batch, n, 1, 1)`). If `sigma`
has the shape of `y` the coordinate count is applied twice (3x too large); if
it has fewer entries the term is too small.

`move()` always passes `(batch, n, 1, 1)`, so the sampler itself is not
affected, but direct callers are. The existing `test_log_prob` uses
`sigma = np.ones(...)`, where `log(sigma) = 0`, so it cannot see the problem.

### Suggested fix

```python
sigma = np.broadcast_to(sigma, y.shape)
numer = np.sum(-0.5 * ((y - mu)**2) / sigma**2, axis=(1, 2, 3))
denom = np.sum(np.log(sigma), axis=(1, 2, 3))
return numer - denom
```

With this the script above prints zeros for all three shapes.
