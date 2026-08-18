# scibench_replication_0015

Implement Gaussian-sketch fixed-sparsity matrix approximation. The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write finite `output.json`.

For every curve experiment, construct the named float64 matrix and normalize it to unit Frobenius norm. `tridiagonal_inverse` is `tridiag(-1,4,-1)^{-1}`. `trefethen_inverse` is the inverse of the diagonal matrix of the first `n` primes plus symmetric unit diagonals at offsets `2^j`, `j=1,...,floor(log2(n))`. `random_dense` uses standard normal entries. `random_sparse` chooses `pattern_parameters[0]` columns independently without replacement in each row and fills them with standard normal entries.

Construct `banded`, `power_bands`, `irregular`, `nonuniform`, or `matrix_support` Boolean patterns as follows. Banded includes offsets `-b,...,b`. Power bands include symmetric offsets within `b` of `2^j` for `j=0,...,floor(log2(n))`. Irregular chooses `s` columns independently per row. Nonuniform row `i` chooses `1+floor(i(s-1)/(n-1))` columns. Matrix support is the exact nonzero support.

At the case boundary initialize `numpy.random.RandomState(seed)` (MT19937), then process experiments and pattern parameters in listed order without reseeding. For every listed `m >= max_row_sparsity+2` and trial, draw `G` with shape `(n,m)`, compute `Z=AG`, and solve independently for each row `argmin_x ||Z_i-x G[S_i,:]||_2`. Return the exact structure shown by public outputs: maximum row sparsity, retained matvec counts, off-pattern Frobenius error, recovery RMSE, 10%/90% quantiles, displayed approximation values (off-pattern error plus recovery values), and Theorem 1 bounds `sqrt(s/(m-s-1))*off_error` and `off_error` plus that bound.

For `hard_coloring`, construct the paper pattern of dimension `k^2`: entry `(p*k+i,q*k+j)` is present iff `i=q` or `j=p`. Return its dimension, maximum row/column sparsity, exact coloring matvec count, and Gaussian exact-recovery threshold.
