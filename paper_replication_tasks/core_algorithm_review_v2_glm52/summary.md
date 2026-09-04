# Core Algorithm Review v2

Model: `z-ai/glm-5.2:free`

| Paper | Core algorithm | G1–G5 | Decision | Evidence gaps |
| --- | --- | --- | --- | --- |
| 0011 | Approximate Bayesian regression for D* estimation | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Exact MCMC sampling parameters may need verification from kinisi source code; SI derivation details for covariance matrix (Eqn 6) span multiple pages but core formula is clear |
| 0014 | — | G1:REJECT, G2:REJECT, G3:REJECT, G4:REJECT, G5:REJECT | REJECT_PAPER | No executable algorithm identified as the core contribution; paper is a theoretical analysis paper with numerical verification. |
| 0015 | Algorithm 2.1: Fixed-sparse-matrix approximation | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | No gaps identified; Algorithm 2.1 is clearly specified with inputs, outputs, and mathematical guarantees in the paper. |
| 0017 | BFCA (Balanced Floating Catchment Area) | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Exact implementation details of weight normalization for binary threshold function not fully specified beyond equations |
| 0018 | Storage importance subsampling framework | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Blind identification test not yet performed; Dependency closure and oracle validity not yet assessed |
| 0019 | Matrix trace inequality optimization | G1:REJECT, G2:PASS, G3:PASS, G4:REJECT, G5:REJECT | REJECT_PAPER | No executable algorithm with clear I/O contract exists; the paper is a theoretical mathematics paper proving inequalities and curvature bounds.; The numerical experiments in Section 4 are illustrative evaluations, not core algorithms. |
| 0020 | SUR-SLM estimation via maximum likelihood | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Exact ML estimation procedure details (log-likelihood, optimization) are referenced to López et al. (2014) and the spsur R package rather than fully specified in the paper |
| 0021 | rEIM (Algorithm 2.1) | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | No explicit pseudocode for the application solvers beyond the core rEIM; implementation details for D(B) and Sigma sampling are in the referenced repository |
| 0022 | Sketch-and-select Arnoldi process | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | No explicit pseudocode for OMP, SP, and Greedy variants in the paper; references to external sources are given instead. |
