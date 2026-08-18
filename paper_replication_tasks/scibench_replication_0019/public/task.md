# scibench_replication_0019

Implement sectional curvature of Grassmann, Stiefel, and SO(n) manifolds under the paper's four metrics. The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write finite `output.json` with fields `metric` (echoed) and `seccurv` (float).

Each input case gives `metric` plus the tangent-vector coordinate matrices for that metric (all as nested row-major float lists), and the caller must compute a single sectional curvature value `K` for the plane they span.

`stiefel_canonical` and `stiefel_euclidean` inputs give integer block sizes `p`, `np` (= n-p) and four `p x p` / `np x p` matrices `A1, B1, A2, B2`: `A1, A2` are `p x p` skew-symmetric, `B1, B2` are `np x p`. These represent tangent vectors `X = [[A1,-B1'],[B1,0]]`, `Y = [[A2,-B2'],[B2,0]]` at the identity of the Stiefel manifold St(n,p), n = p+np.

For `stiefel_canonical` (canonical metric), first orthonormalize: `normX = sqrt(0.5*trace(A1'A1) + trace(B1'B1))`, divide `A1,B1` by `normX`; then `d = 0.5*trace(A1'A2) + trace(B1'B2)`, subtract `d*(A1,B1)` from `(A2,B2)`, and normalize the result by `normY = sqrt(0.5*trace(A2'A2) + trace(B2'B2))`. With Lie brackets `[A1,A2] = A1A2-A2A1`, `L1 = B1'B2-B2'B1`, `L2 = B2B1'-B1B2'`, curvature is `K = (1/8)||[A1,A2]-L1||_F^2 + (1/4)||B1A2-B2A1||_F^2 + (1/2)||L2||_F^2`.

For `stiefel_euclidean` (Euclidean metric), orthonormalize using unweighted norms `normX = sqrt(trace(A1'A1)+trace(B1'B1))` and `d = trace(A1'A2)+trace(B1'B2)` (no 0.5 factors), then `K = (1/4)||[A1,A2]+L1||_F^2 + ||B1A2-B2A1||_F^2 + trace(B1(B2'B2)B1') - trace((B1'B2)(B2'B1))`.

`grassmann` inputs give `B1, B2` (both `np x p`) representing `X=[0;B1], Y=[0;B2]` in the tangent space of Gr(n,p). Normalize `B1` by its Frobenius norm; subtract `trace(B2'B1)*B1` from `B2` and normalize the result by its Frobenius norm. With `M = B1'B2`, `K = trace(MM') + trace((B1'B1)(B2'B2)) - 2*trace(MM)`.

`so_n` inputs give an integer `n` and two `n x n` skew-symmetric matrices `X, Y` representing tangent vectors at the identity of SO(n). Normalize `X` by its Frobenius norm; subtract `trace(X'Y)*X` from `Y` and normalize by its Frobenius norm. `K = 0.5*trace([X,Y]'[X,Y])` where `[X,Y] = XY-YX`.
