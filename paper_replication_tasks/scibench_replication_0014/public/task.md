# scibench_replication_0014

Implement the paper's approximate Sherman–Morrison–Woodbury inverse and its forward/backward error expressions. The runner invokes `<entrypoint> --input <input.json> --output <new-output-dir>`; write `output.json`.

For every case, use float64 spectral norms. Let `B=A+U V^T`, `lambda=||U||_2 ||V||_2`, `A_tilde_inverse=A^{-1}+E1`, `Z_inverse=(I+V^T A_tilde_inverse U)^{-1}+E2`, and `B_tilde_inverse=A_tilde_inverse-A_tilde_inverse U Z_inverse V^T A_tilde_inverse`. Set `epsilon_1=||E1||_2`, `epsilon_2=||E2||_2`, `alpha=||(I+V^T A^{-1}U)^{-1}||_2`, and `beta=||I+V^T A^{-1}U||_2`.

Return exactly eight arrays: `epsilon_1`, `epsilon_2`, `forward_error_mean`, `forward_simplified_expression`, `forward_full_bound`, `backward_error_mean`, `backward_simplified_expression`, and `backward_full_bound`. Forward error is `||B^{-1}-B_tilde_inverse||_2`; backward error is `||B-B_tilde_inverse^{-1}||_2`. The simplified expressions are `2 epsilon_2 ||A^{-1}||_2 + 12 epsilon_1` and `2 epsilon_1 ||A||_2^2 + 8 epsilon_2`. The full bounds are Theorem 2 equation (16) and Theorem 6 equation (22).

`point` inputs supply `A,U,V,E1,E2` and produce arrays of length one. `sweep` inputs supply `n,k,update_regime,update_factor,epsilon_grid,replicates,seed`. Use `numpy.random.RandomState(seed)` (MT19937), float64, and draw in the order `A`, normalized `U`, normalized `V`, then for each epsilon and replicate `E1`, `E2`. Normalize each noise matrix to the epsilon spectral norm. Scale both normalized update factors by `sqrt(update_factor*sigma_min(A))` for `small` or `sqrt(update_factor*sigma_max(A))` for `large`. Average each quantity over replicates. Do not return matrices.
