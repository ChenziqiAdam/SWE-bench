"""Build and validate the offline Codex core-algorithm review.

This entrypoint is deliberately local-only: it reads repository PDFs and review
artifacts, never reads an environment file, and contains no network client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from paper_replication_tasks.review_core_algorithms import (
    PAPER_IDS,
    SCHEMA_VERSION,
    PaperSource,
    atomic_write_json,
    atomic_write_text,
    extract_pdf,
    validate_final_record,
)


MODEL = "codex-local-review"
CALL_MODE = "local_manual_review"
DEFAULT_OUTPUT = Path("paper_replication_tasks/core_algorithm_review_v2_codex")
V2_ROOT = Path("paper_replication_tasks/core_algorithm_review_v2")
GLM_ROOT = Path("paper_replication_tasks/core_algorithm_review_v2_glm52")
EXPECTED_HASHES = {
    "0011": "4503b909fb05528f6bde5f58dd1a7705152914fcfa0853f8dd21de12483345ab",
    "0014": "18789c49fe7354fbd23d4be9106da2c0321d92a06be34b6204b2d5fe03b74011",
    "0015": "b1f124097fed43903ef37f434904ee140b727b30f593a6a8bb895c42a8ea53cc",
    "0017": "997614b78010b3fbe8cd7858a1f1821c3dc40d34f0fcbd60490451088908e5de",
    "0018": "f7de9fe507fe2bb0bff801bbc9975deb13c0a4b0853fd588935bd04f3af39dfa",
    "0019": "4699a7ca940b385fec7068c5f8fdf9f238db482442b86f24c3e99243965eb704",
    "0020": "380ffdb8a8c1e48cf204fb1742aa7f071d8c2898734b1dbe16b9b543570a02f2",
    "0021": "b7f61555afe1e784318af286c6120a0f8b86cd39f06f9b9d3b69a9988e4ea453",
    "0022": "ba434fecc9ffe9c73279e1a51921c589abc6df3f0cd0619b6b9dab31d21570f0",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_path(repo_root: Path, paper_id: str) -> Path:
    if paper_id == "0021":
        return repo_root / V2_ROOT / "sources/0021_arxiv_2406.19339v3.pdf"
    if paper_id == "0022":
        return repo_root / "paper_replication_tasks/curation_tools/ssarnoldi_paper/paper_original_arxiv_v3.pdf"
    return repo_root / f"paper_replication_tasks/scibench_replication_{paper_id}/public/paper.pdf"


def evidence(items: Iterable[tuple[int, str, str]]) -> list[dict[str, Any]]:
    return [
        {"id": f"E{index}", "page": page, "section": section, "excerpt": excerpt}
        for index, (page, section, excerpt) in enumerate(items, 1)
    ]


def candidate(
    name: str,
    role: str,
    description: str,
    refs: list[str],
    outcome: str,
    deletion_reason: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "description": description,
        "evidence": refs,
        "deletion_test": {
            "outcome": outcome,
            "reason": deletion_reason,
            "evidence": refs,
        },
    }


def gates(statuses: dict[str, str], reasons: dict[str, str], refs: dict[str, list[str]]) -> dict[str, Any]:
    result = {
        gate: {"status": statuses[gate], "reason": reasons[gate], "evidence": refs[gate]}
        for gate in ("G1", "G2", "G3", "G4", "G5")
    }
    result.update(
        {
            gate: {
                "status": "NOT_EVALUATED",
                "reason": "deferred to later benchmark-design stage",
                "evidence": [],
            }
            for gate in ("G6", "G7", "G8")
        }
    )
    return result


def accepted_gates(refs: dict[str, list[str]], reasons: dict[str, str]) -> dict[str, Any]:
    return gates({gate: "PASS" for gate in refs}, reasons, refs)


def contract(
    algorithm: str,
    purpose: str,
    inputs: list[str],
    outputs: list[str],
    operations: list[str],
    assumptions: list[str],
    parameters: list[str],
    invariants: list[str],
    contributions: list[str],
    results: list[str],
    specificity: str,
    refs: list[str],
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "scientific_purpose": purpose,
        "inputs": inputs,
        "outputs": outputs,
        "core_operations": operations,
        "assumptions": assumptions,
        "parameters": parameters,
        "scientific_invariants": invariants,
        "dependent_contributions": contributions,
        "dependent_experiments_results": results,
        "specificity_reason": specificity,
        "evidence": refs,
    }


def record_0011() -> dict[str, Any]:
    ev = evidence(
        [
            (2, "I. Introduction", "Here, we describe an approximate Bayesian regression method for estimatingD ∗ with near-maximal statistical efficiency while accurately estimating the corresponding statistical uncertainty using data from a single simulation."),
            (2, "I. Introduction", "We model the statistical population of simulation MSDs as a multivariate normal distribution, using an analytical covariance matrix derived for an equivalent system of freely diffusing particles, with this covariance matrix parameterised from the observed simulation data."),
            (7, "VI. Summary and Discussion", "We use Markov-Chain Monte Carlo to sample the posterior distribution of linear models compatible with the observed MSD data."),
            (7, "VI. Summary and Discussion", "We have benchmarked our approach using simulation data for an ideal 3D lattice random walk and for the lithium-ion solid electrolyte Li 7La3Zr2O12 (LLZO)."),
            (7, "VI. Summary and Discussion", "The approximate Bayesian regression scheme therefore provides more accurate single-point estimates of the self-diffusion coefficient than the commonly used OLS or WLS methods, when applied to the same input simulation data."),
        ]
    )
    core = "Single-trajectory approximate Bayesian MSD regression"
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_id": "0011",
        "evidence_catalog": ev,
        "research_goal": {"summary": "Estimate self-diffusion coefficients and their uncertainty efficiently from one molecular-dynamics trajectory.", "evidence": ["E1"]},
        "main_contributions": [
            {"id": "C1", "summary": "A Bayesian MSD regression scheme with an analytically modelled and data-parameterized covariance matrix.", "evidence": ["E1", "E2", "E3"]},
            {"id": "C2", "summary": "Near-optimal statistical efficiency and useful uncertainty estimates from a single trajectory.", "evidence": ["E4", "E5"]},
        ],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is solved by", "evidence": ["E1"]}, {"from": "C1", "to": "C2", "relation": "produces and is validated by", "evidence": ["E4", "E5"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Fit the MSD population with a free-diffusion covariance model and sample the posterior linear-model distribution.", ["E1", "E2", "E3"], "FAILS_WITHOUT_ALGORITHM", "Removing the combined covariance model and posterior regression eliminates the paper's estimator and both claimed outputs."),
            candidate("Analytical free-diffusion covariance construction", "supporting", "Construct and recondition the covariance used by the Bayesian estimator.", ["E2"], "FAILS_WITHOUT_ALGORITHM", "The selected estimator needs this covariance component, but the component alone does not produce the paper's scientific output."),
            candidate("OLS, WLS, and converged-covariance GLS", "baseline", "Conventional and theoretical-optimum regression comparators.", ["E5"], "SURVIVES_WITHOUT_ALGORITHM", "The proposed estimator remains defined without these comparison methods."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "Only the integrated single-trajectory Bayesian estimator carries both the efficient point estimate and uncertainty contribution; covariance construction is a component and OLS/WLS/GLS are comparators.",
        "scientific_contract": contract(core, "Infer a self-diffusion coefficient and its statistical uncertainty from noisy, correlated MSD observations.", ["lag times", "observed MSD values", "squared-displacement variance information"], ["posterior diffusion-coefficient estimate", "estimated uncertainty"], ["parameterize analytical covariance", "recondition covariance", "sample linear-model posterior"], ["long-time free-diffusion covariance is an adequate approximation", "linear MSD regime"], ["diffusion coefficient", "intercept", "covariance scale"], ["covariance remains positive definite", "MSD mean is linear in time", "posterior uncertainty reflects correlated heteroscedastic noise"], ["C1", "C2"], ["lattice-random-walk benchmark", "LLZO benchmark"], "It couples diffusion physics, correlated MSD statistics, covariance reconditioning, and Bayesian inference rather than calling a generic regression API.", ["E1", "E2", "E3", "E4"]),
        "gates": accepted_gates(
            {"G1": ["E1", "E5"], "G2": ["E1", "E2", "E3"], "G3": ["E2", "E3"], "G4": ["E1", "E3"], "G5": ["E4", "E5"]},
            {"G1": "Deleting the estimator removes the main efficiency and uncertainty contribution.", "G2": "The covariance construction and MCMC are coupled stages of one estimator; the other regressions are baselines.", "G3": "The method requires a diffusion-specific covariance model and correlated-MSD inference.", "G4": "Trajectory-derived MSD inputs map to a diffusion posterior and uncertainty.", "G5": "The same estimator is tested on a stochastic lattice model and a chemically realistic solid electrolyte."},
        ),
        "evidence_gaps": [],
        "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0014() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "We study the numerical stability of the Sherman–Morrison–Woodbury (SMW) identity."),
            (1, "1 Introduction", "Our work provides forward and backward error bounds for the update formula of eqn. (1)."),
            (10, "4 Numerical Experiments", "The goal of our numerical experiments is to verify the tightness of our forward and backward error bounds as well as examining the dominating terms."),
            (12, "5 Future Work", "Theorems 2 and 6 provide general error bounds, they do not fully explain this observed correlation between update magnitude and bound tightness."),
        ]
    )
    statuses = {gate: "REJECT" for gate in ("G1", "G2", "G3", "G4", "G5")}
    reasons = {"G1": "The main contribution is a theorem-level stability analysis, not a new scientific algorithm.", "G2": "No candidate algorithm uniquely carries the forward and backward error-bound contribution.", "G3": "The executable SMW update is a pre-existing identity; the new content is mathematical analysis.", "G4": "The paper does not define a paper-specific algorithmic input-output contract beyond evaluating a standard identity and its bounds.", "G5": "New matrices can test bound tightness, but that evaluates theorems rather than generalization of a core algorithm."}
    refs = {"G1": ["E1", "E2"], "G2": ["E1", "E2", "E3"], "G3": ["E1", "E2"], "G4": ["E2", "E3"], "G5": ["E3", "E4"]}
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0014", "evidence_catalog": ev,
        "research_goal": {"summary": "Derive and empirically assess forward and backward stability bounds for approximate SMW inversion.", "evidence": ["E1", "E2"]},
        "main_contributions": [{"id": "C1", "summary": "Forward and backward error bounds for SMW with approximate inverses.", "evidence": ["E2"]}, {"id": "C2", "summary": "Numerical evaluation of tightness and dominant error terms.", "evidence": ["E3", "E4"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is answered by proofs of", "evidence": ["E2"]}, {"from": "C1", "to": "C2", "relation": "is empirically checked by", "evidence": ["E3"]}],
        "candidate_algorithms": [
            candidate("Sherman–Morrison–Woodbury inverse update", "supporting", "Apply the established low-rank inverse-update identity with approximate inverses.", ["E1", "E2"], "SURVIVES_WITHOUT_ALGORITHM", "The paper's novel contribution is the error analysis of this pre-existing identity, not the identity itself."),
            candidate("Random-matrix stability experiment", "evaluation", "Perturb approximate inverses and compare observed errors with the derived bounds.", ["E3"], "SURVIVES_WITHOUT_ALGORITHM", "The formal bounds remain the principal contribution without the evaluation procedure."),
        ],
        "selected_core_algorithm": None,
        "uniqueness_reason": "The paper contributes stability theorems. Its executable SMW update predates the paper and the random-matrix procedure only evaluates the theorems, so no candidate is a core scientific algorithm.",
        "scientific_contract": None,
        "gates": gates(statuses, reasons, refs),
        "evidence_gaps": ["No novel, uniquely central algorithmic input-output procedure is stated."],
        "decision": "REJECT_PAPER",
    }


def record_0015() -> dict[str, Any]:
    ev = evidence(
        [
            (2, "1.1 Fixed-sparsity matrix approximation", "In this work, we focus on the task of approximating A with a matrix of a specified sparsity pattern, with error competitive with the best approximation with the given sparsity pattern."),
            (3, "1.2 Our contributions and roadmap", "Our first contribution is to analyze a simple algorithm (Algorithm 2.1) that solves Problems 1.1 and 1.2."),
            (3, "1.2 Our contributions and roadmap", "the algorithm computes Z = AG"),
            (4, "1.2 Our contributions and roadmap", "We show that up to constant factors in the query complexity, the upper bound in Corollary 1.4 is optimal, even for the stronger class of adaptive matvec query algorithms."),
            (7, "2 An algorithm and upper bound", "This algorithm proceeds row-by-row, taking advantage of the fact that different rows of the solution to (1.2) do not depend on one another"),
            (18, "6 Outlook", "our lower bound Theorem 1.5 shows that only constant factors can be improved for some families of problem instances."),
        ]
    )
    core = "Gaussian-sketch fixed-sparsity matrix approximation"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0015", "evidence_catalog": ev,
        "research_goal": {"summary": "Recover a near-optimal approximation with a prescribed sparsity pattern using few nonadaptive matrix-vector products.", "evidence": ["E1"]},
        "main_contributions": [{"id": "C1", "summary": "A Gaussian-sketch, row-wise least-squares algorithm using O(s/epsilon) matvecs.", "evidence": ["E2", "E3", "E5"]}, {"id": "C2", "summary": "Matching query-complexity lower bounds up to constants.", "evidence": ["E4", "E6"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is constructively solved by", "evidence": ["E1", "E2"]}, {"from": "C1", "to": "C2", "relation": "has optimality certified by", "evidence": ["E4"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Sketch A with an iid Gaussian query matrix and solve one restricted least-squares problem per output row.", ["E2", "E3", "E5"], "FAILS_WITHOUT_ALGORITHM", "Removing Algorithm 2.1 eliminates the constructive upper bound and matrix approximation."),
            candidate("Adaptive-query Wishart lower-bound construction", "supporting", "Prove a lower bound against adaptive matvec algorithms.", ["E4"], "SURVIVES_WITHOUT_ALGORITHM", "It certifies optimality but does not construct the requested approximation."),
            candidate("Graph-coloring fixed-sparsity recovery", "baseline", "Established comparator for structured sparse recovery.", ["E4"], "SURVIVES_WITHOUT_ALGORITHM", "The proposed Gaussian method is independently defined."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "Algorithm 2.1 is the sole constructive method introduced for the stated approximation problem; lower bounds are analysis and coloring is comparative prior work.",
        "scientific_contract": contract(core, "Approximate a matrix on a fixed support from matrix-vector queries.", ["linear operator A", "binary sparsity pattern S", "sketch size m", "random seed"], ["S-sparse approximation A_tilde"], ["draw iid Gaussian G", "compute AG", "solve support-restricted row least squares", "assemble sparse output"], ["at most s selected entries per row", "m is large enough for the requested accuracy"], ["m", "sparsity pattern S"], ["output is zero off S", "exact recovery when A already has support S and m>=s", "expected error follows the stated query bound"], ["C1", "C2"], ["model matrix experiment", "Trefethen-primes experiment"], "The support-constrained Gaussian probing and row-specific pseudoinverse construction are the paper's matrix-free scientific procedure.", ["E1", "E2", "E3", "E5"]),
        "gates": accepted_gates({"G1": ["E2", "E4"], "G2": ["E2", "E5"], "G3": ["E1", "E3", "E5"], "G4": ["E1", "E3", "E5"], "G5": ["E4", "E6"]}, {"G1": "The algorithm supplies the paper's constructive upper bound.", "G2": "Only Algorithm 2.1 is a constructive core candidate.", "G3": "It requires a paper-specific Gaussian matvec sketch and support-restricted recovery argument.", "G4": "A, S, m, and randomness determine an S-sparse matrix output.", "G5": "The theorem covers arbitrary matrices and admissible sparsity patterns, including new hard instances."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0017() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "we investigate differentials in accessibility to stations using a balanced floating catchment area approach and compare accessibility with and without the equity stations."),
            (12, "4.1 Balanced Floating Catchment Area", "The BFCA method was developed to address issues with demand and supply inflation that result from the overlapping catchment areas produced by earlier FCA methods"),
            (13, "4.1 Balanced Floating Catchment Area", "With these weights, accessibility can be calculated without risk of demand or supply inflation"),
            (14, "4.2 Pycnophylactic Interpolation", "Pycnophylactic interpolation involves smoothing out the population from each DA while preserving total volume."),
            (16, "5.1 Accessibility by Distance Thresholds", "accessibility calculated using the BFCA method increased with a threshold between two and four minutes, but was then maximized at five minutes."),
            (29, "6 Discussion", "Unlike the 2SFCA method, there was no inflation or deflation in our accessibility estimates because population and level of service were preserved"),
        ]
    )
    core = "Balanced floating catchment area accessibility calculation"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0017", "evidence_catalog": ev,
        "research_goal": {"summary": "Measure whether added equity stations changed bike-share accessibility across populations and income groups.", "evidence": ["E1"]},
        "main_contributions": [{"id": "C1", "summary": "A BFCA-based micro-scale accessibility analysis that preserves total population and service.", "evidence": ["E2", "E3", "E6"]}, {"id": "C2", "summary": "A sensitivity and equity comparison across walking thresholds and station configurations.", "evidence": ["E1", "E5"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is operationalized by", "evidence": ["E1", "E2"]}, {"from": "C1", "to": "C2", "relation": "supplies accessibility estimates for", "evidence": ["E5", "E6"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Normalize origin and destination impedance weights, allocate demand and service proportionally, and compute accessibility.", ["E2", "E3", "E6"], "FAILS_WITHOUT_ALGORITHM", "Without balanced allocation the accessibility measure and no-inflation contribution disappear."),
            candidate("Conventional two-step floating catchment area", "baseline", "Unbalanced comparison method used to expose demand and supply inflation.", ["E2", "E6"], "SURVIVES_WITHOUT_ALGORITHM", "BFCA and its equity analysis remain defined without the comparator."),
            candidate("Pycnophylactic population interpolation", "preprocessing", "Disaggregate census population to small cells while preserving totals.", ["E4"], "SURVIVES_WITHOUT_ALGORITHM", "It improves spatial resolution but is not the accessibility algorithm."),
            candidate("Walking-threshold sensitivity analysis", "evaluation", "Repeat accessibility calculations over travel-time thresholds.", ["E5"], "SURVIVES_WITHOUT_ALGORITHM", "It evaluates robustness rather than defining accessibility."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "BFCA alone generates the paper's defining accessibility measure; interpolation prepares demand, 2SFCA is a baseline, and threshold sweeps evaluate sensitivity.",
        "scientific_contract": contract(core, "Quantify balanced access to bike-share station capacity without double-counting demand or supply.", ["population by origin", "station rack supply", "origin-station impedance weights"], ["accessibility per population unit", "aggregate accessibility summaries"], ["normalize weights by origin", "normalize weights by station", "compute station service ratios", "sum weighted service at origins"], ["nonnegative population and supply", "reachable pairs are encoded by impedance", "normalization denominators are nonzero where used"], ["walking-time threshold", "distance-decay weights"], ["normalized origin weights sum to one", "normalized station weights sum to one", "population and level of service are preserved"], ["C1", "C2"], ["with/without equity stations", "walking-threshold sensitivity", "income-group comparison"], "The doubly normalized spatial allocation and conservation properties are specialized accessibility reasoning.", ["E1", "E2", "E3", "E6"]),
        "gates": accepted_gates({"G1": ["E1", "E6"], "G2": ["E2", "E3", "E4"], "G3": ["E2", "E3"], "G4": ["E2", "E3"], "G5": ["E5", "E6"]}, {"G1": "BFCA directly produces the accessibility quantities supporting the equity conclusions.", "G2": "The other computational procedures are preprocessing, baseline, or evaluation.", "G3": "Balanced spatial allocation enforces domain-specific demand and supply conservation.", "G4": "Population, station supply, and impedance weights determine accessibility outputs.", "G5": "The same method supports new thresholds, station configurations, and service areas."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0018() -> dict[str, Any]:
    ev = evidence(
        [
            (5, "2 This paper's contribution", "we introduce a posteriori time series aggregation schemes for capacity expansion planning models with storage."),
            (5, "2 This paper's contribution", "These schemes (1) tailor aggregation to the underlying energy system model and (2) preserve chronology, allowing the representation of long-term storage patterns."),
            (6, "3.2 Framework: storage importance subsampling", "We determine a first-stage optimal design estimate DA0 using a priori aggregation."),
            (6, "3.2 Framework: storage importance subsampling", "Partition time series T into"),
            (7, "3.3 Remarks", "We preserve chronology for storage technologies using ordered and linked representative days"),
            (9, "4.3 Validation", "The a posteriori Methods D-F have significantly lower levels of unmet demand than A-C."),
            (11, "5.1 Conclusions", "This paper introduces a framework for a posteriori time series aggregation schemes for energy system (capacity expansion) planning models with storage."),
        ]
    )
    core = "Storage importance subsampling framework"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0018", "evidence_catalog": ev,
        "research_goal": {"summary": "Compress long climate and demand time series for storage-aware capacity planning while retaining system-relevant extremes and chronology.", "evidence": ["E1", "E2"]},
        "main_contributions": [{"id": "C1", "summary": "A two-stage a posteriori aggregation framework customized by operational variables and storage chronology.", "evidence": ["E1", "E2", "E3", "E5"]}, {"id": "C2", "summary": "Reduced unmet demand relative to a priori aggregation in capacity-planning simulations.", "evidence": ["E6", "E7"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is addressed by", "evidence": ["E1", "E2"]}, {"from": "C1", "to": "C2", "relation": "is validated by", "evidence": ["E6"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Use a preliminary design and full-series operation to identify extremes, build a chronology-preserving aggregation, and re-optimize design.", ["E1", "E2", "E3", "E4", "E5"], "FAILS_WITHOUT_ALGORITHM", "Removing the two-stage importance subsampling removes the paper's adaptive aggregation contribution."),
            candidate("A priori representative-period clustering", "baseline", "Aggregate from time-series inputs before model outputs are available.", ["E3", "E6"], "SURVIVES_WITHOUT_ALGORITHM", "It supplies the preliminary design and comparator but is not the introduced adaptive method."),
            candidate("Capacity planning and operational optimization models", "supporting", "Produce preliminary/final designs and operational variables.", ["E3"], "FAILS_WITHOUT_ALGORITHM", "These solvers are necessary components, but the paper's core novelty is how their outputs drive aggregation."),
            candidate("Unserved-energy and generation-cost importance functions", "supporting", "Alternative scalar functions for ranking extreme periods.", ["E4", "E6"], "SURVIVES_WITHOUT_ALGORITHM", "They are interchangeable configurations within the common framework."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "The paper presents one overarching two-stage a posteriori framework; clustering, optimizers, and alternative importance measures are replaceable components or baselines.",
        "scientific_contract": contract(core, "Estimate storage-aware capacity designs from long time series at reduced cost and climate-sampling risk.", ["demand/weather time series", "planning model", "operational model", "representative-period budget"], ["final capacity design estimate", "aggregated chronology"], ["build a priori aggregation", "solve preliminary planning design", "simulate full-series operation", "rank and stratify extremes", "aggregate extreme and regular periods", "solve final design"], ["operational model can evaluate a fixed design", "representative periods remain chronologically linked for storage"], ["number of representative periods", "extreme proportion", "importance function", "clustering rule"], ["chronology is preserved", "extreme and regular samples exhaust the timeline", "final design is computed from the adaptive aggregation"], ["C1", "C2"], ["three-year validation", "thirty-year aggregation", "unserved-energy comparison"], "It couples energy-system operation, extreme-event selection, storage chronology, and capacity re-optimization.", ["E1", "E2", "E3", "E4", "E5"]),
        "gates": accepted_gates({"G1": ["E1", "E7"], "G2": ["E1", "E3", "E4"], "G3": ["E2", "E5"], "G4": ["E3", "E4", "E5"], "G5": ["E6", "E7"]}, {"G1": "The introduced framework is the paper's main scientific contribution.", "G2": "Alternative importance functions and clustering choices instantiate one framework rather than independent core algorithms.", "G3": "It requires storage chronology and model-derived extreme-event reasoning.", "G4": "The staged optimization and aggregation define a deterministic contract given solver and clustering choices.", "G5": "The same framework is evaluated across time-series lengths, model runs, and aggregation budgets."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0019() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "We provide refined inequalities for such terms and pay special attention to the maximizers of the curvature bounds."),
            (2, "1 Introduction", "we prove the conjectured global curvature bounds"),
            (20, "4 Numerical Experiments", "we illustrate the behavior of the sectional curvature on SO(n), Gr(n, p) and St(n, p) at special parametric sections"),
            (24, "5 Summary", "we establish that the curvature on the Stiefel manifold equipped with this metric globally does not exceed 5/4."),
            (24, "5 Summary", "these tangent space sections are necessarily spanned by special rank-two matrices."),
        ]
    )
    statuses = {gate: "REJECT" for gate in ("G1", "G2", "G3", "G4", "G5")}
    reasons = {"G1": "The central contributions are proofs of trace inequalities and sharp curvature bounds, not an algorithm.", "G2": "No executable candidate uniquely carries the theorem-level contribution.", "G3": "Direct curvature evaluation uses stated formulas, while the paper-specific novelty lies in proofs and maximizer characterization.", "G4": "The paper does not specify a core algorithmic input-output contract for its main contribution.", "G5": "Parametric experiments illustrate the proved geometry but do not test generalization of a selected core algorithm."}
    refs = {"G1": ["E1", "E2", "E4"], "G2": ["E1", "E3"], "G3": ["E1", "E5"], "G4": ["E2", "E4"], "G5": ["E3", "E5"]}
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0019", "evidence_catalog": ev,
        "research_goal": {"summary": "Establish sharp sectional-curvature bounds and characterize their low-rank maximizers on Grassmann and Stiefel manifolds.", "evidence": ["E1", "E2", "E4", "E5"]},
        "main_contributions": [{"id": "C1", "summary": "Refined matrix trace inequalities and proofs of global curvature bounds.", "evidence": ["E1", "E2", "E4"]}, {"id": "C2", "summary": "Low-rank characterization of extremal tangent sections.", "evidence": ["E5"]}],
        "contribution_graph": [{"from": "C1", "to": "C2", "relation": "enables characterization of", "evidence": ["E1", "E5"]}, {"from": "C2", "to": "numerical illustrations", "relation": "is illustrated by", "evidence": ["E3"]}],
        "candidate_algorithms": [
            candidate("Closed-form sectional-curvature evaluation", "supporting", "Evaluate known canonical or Euclidean curvature formulas for supplied tangent matrices.", ["E2", "E4"], "SURVIVES_WITHOUT_ALGORITHM", "The paper's main results are universal inequalities and proofs, not merely numerical evaluation."),
            candidate("Parametric rank-versus-curvature experiment", "evaluation", "Generate structured tangent sections of increasing rank and evaluate curvature.", ["E3", "E5"], "SURVIVES_WITHOUT_ALGORITHM", "The theorems and maximizer characterization stand without the illustrative experiment."),
        ],
        "selected_core_algorithm": None,
        "uniqueness_reason": "The mathematical proofs and extremal characterizations are central, but neither is an input-output scientific algorithm; formula evaluation and numerical sweeps are supporting evaluation procedures.",
        "scientific_contract": None,
        "gates": gates(statuses, reasons, refs),
        "evidence_gaps": ["No unique algorithm is introduced for the theorem-driven scientific contribution."],
        "decision": "REJECT_PAPER",
    }


def record_0020() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "Use of spatial Seemingly Unrelated Regressions (SUR) allows us to model the incidence of reported cases of the disease per 100,000 population as an interregional contagion process"),
            (2, "1 Introduction", "our objective with this paper is to investigate the influence of environmental factors, concretely temperature, humidity, and sunshine, on the progression of the pandemic."),
            (7, "4 Methods: the Spatial SUR Model", "The basis of this approach is well-known since the initial works of Zellner (1962)"),
            (9, "4 Methods: the Spatial SUR Model", "spatial SUR model that incorporates a spatial lag of the dependent variable as an explanatory factor."),
            (9, "4 Methods: the Spatial SUR Model", "The coefficients of the spatially lagged variable are estimated for each time period"),
            (13, "5.2 SUR Models", "we estimate three spatial SUR models to test the differences between the various temporal lags and weighting schemes for the environmental variables."),
            (23, "7 Concluding Remarks", "Our results offer strong support for the hypothesis that incidence of COVID-19 at the population level is lower at higher temperatures and levels of humidity"),
        ]
    )
    core = "Spatial-lag seemingly unrelated regression analysis"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0020", "evidence_catalog": ev,
        "research_goal": {"summary": "Estimate environmental associations with COVID-19 incidence while representing temporal covariance and interprovincial contagion in Spain.", "evidence": ["E1", "E2"]},
        "main_contributions": [{"id": "C1", "summary": "A spatial SUR analysis with date-specific spatial-lag contagion effects and environmental lag specifications.", "evidence": ["E1", "E4", "E5", "E6"]}, {"id": "C2", "summary": "Estimated temperature, humidity, sunshine, and control-variable effects under contagion.", "evidence": ["E7"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is estimated with", "evidence": ["E1", "E2"]}, {"from": "C1", "to": "C2", "relation": "supports inference of", "evidence": ["E7"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Fit a SUR system with temporal residual covariance and date-specific spatial lags, then derive spatial impacts.", ["E1", "E4", "E5", "E6"], "FAILS_WITHOUT_ALGORITHM", "Removing the spatial SUR eliminates both contagion adjustment and the reported conditional environmental effects."),
            candidate("Classical non-spatial SUR", "baseline", "Stack date equations with cross-equation residual covariance but no spatial lag.", ["E3"], "SURVIVES_WITHOUT_ALGORITHM", "It is methodological background and a comparator, not the selected contagion model."),
            candidate("Incubation-lag environmental averaging", "preprocessing", "Construct lag8, lag11, and weighted lag11 environmental covariates.", ["E6"], "FAILS_WITHOUT_ALGORITHM", "The empirical variants require it, but it does not itself estimate contagion or effects."),
            candidate("Direct/indirect spatial-impact calculation", "evaluation", "Translate spatial-lag coefficients into own-province and spillover effects.", ["E4", "E7"], "SURVIVES_WITHOUT_ALGORITHM", "It interprets the fitted model rather than defining the estimator."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "The spatial SUR-SLM is the only method joining temporal covariance, spatial contagion, and environmental inference; lag construction and impact decomposition are adjacent stages, and classical SUR is background.",
        "scientific_contract": contract(core, "Estimate time-varying environmental and contagion effects on provincial disease incidence.", ["province-by-date incidence", "environmental and socioeconomic covariates", "spatial weights matrix"], ["spatial-lag coefficients", "regression coefficients", "fit statistics", "direct and indirect effects"], ["construct lagged covariates", "stack SUR equations", "estimate temporal covariance and spatial lags", "compute spatial impacts"], ["spatial weights encode relevant contagion neighbors", "SUR residual covariance links dates", "model restrictions identify coefficients"], ["lag window", "coefficient restrictions", "spatial weights", "estimation method"], ["dimensions agree across dates and provinces", "spatial-lag operator remains invertible", "reported impacts correspond to fitted spatial feedback"], ["C1", "C2"], ["three environmental-lag models", "date-wise and pooled fit", "direct/indirect effect summaries"], "The procedure combines disease-incubation lags, temporal equation covariance, geographic contagion feedback, and spatial-impact interpretation.", ["E1", "E4", "E5", "E6"]),
        "gates": accepted_gates({"G1": ["E1", "E7"], "G2": ["E3", "E4", "E6"], "G3": ["E1", "E4", "E5"], "G4": ["E4", "E5", "E6"], "G5": ["E5", "E6"]}, {"G1": "The environmental conclusions depend directly on the spatial SUR analysis.", "G2": "One fitted spatial SUR family is central; non-spatial SUR and lag construction have subordinate roles.", "G3": "The estimator embodies spatiotemporal contagion and epidemiological lag reasoning beyond generic regression.", "G4": "The panel, covariates, spatial weights, and restrictions define estimable outputs.", "G5": "The same model can be tested on new panels, spatial structures, dates, and lag variants."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0021() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "We present a new rational approximation algorithm based on the empirical interpolation method for interpolating a family of parametrized functions to rational polynomials with invariant poles"),
            (2, "1 Introduction", "Our rEIM adaptively selects basis functions from the set"),
            (2, "1 Introduction", "the rEIM directly outputs approximants of the form (1.1)"),
            (3, "2 Rational Approximation via the Empirical Interpolation Method", "Output: the rational interpolant Π nf for a family of target functions f which are not necessarily in D(B)."),
            (4, "2 Rational Approximation via the Empirical Interpolation Method", "For any input target function f , the rEIM interpolant Π nf has a fixed set of poles"),
            (6, "2.1 Convergence Estimate of the rEIM", "Combining Theorem 2.3 with the order of convergence"),
            (21, "6 Concluding Remarks", "we have developed the rEIM, a new rational approximation algorithm for producing partial fraction approximation of a target function set."),
        ]
    )
    core = "Rational approximation via empirical interpolation (rEIM)"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0021", "evidence_catalog": ev,
        "research_goal": {"summary": "Efficiently approximate families of parameterized functions in partial-fraction form with shared invariant poles.", "evidence": ["E1", "E3"]},
        "main_contributions": [{"id": "C1", "summary": "The adaptive rEIM algorithm selecting rational dictionary functions and interpolation points once for many targets.", "evidence": ["E1", "E2", "E4", "E5"]}, {"id": "C2", "summary": "A convergence estimate and applications to fractional PDEs, preconditioning, and matrix functions.", "evidence": ["E6", "E7"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is solved by", "evidence": ["E1", "E3"]}, {"from": "C1", "to": "C2", "relation": "is supported and applied by", "evidence": ["E6", "E7"]}],
        "candidate_algorithms": [
            candidate(core, "core", "Greedily select rational dictionary poles and interpolation points, then interpolate every target through a shared small system.", ["E1", "E2", "E3", "E4", "E5"], "FAILS_WITHOUT_ALGORITHM", "Removing rEIM eliminates the new approximation procedure, invariant-pole output, and applications."),
            candidate("Rational orthogonal greedy algorithm", "baseline", "Alternative dictionary-based rational approximation presented for comparison.", ["E6"], "SURVIVES_WITHOUT_ALGORITHM", "rEIM remains fully defined without this comparator."),
            candidate("AAA-type rational approximation", "baseline", "Prior barycentric rational approximation approach.", ["E3"], "SURVIVES_WITHOUT_ALGORITHM", "It motivates the partial-fraction advantage but is not the proposed method."),
            candidate("rEIM-based fractional PDE solvers", "supporting", "Use the selected poles and residues to combine shifted local solves.", ["E7"], "SURVIVES_WITHOUT_ALGORITHM", "These are downstream applications of the general approximation algorithm."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "rEIM is explicitly introduced as the new general algorithm; ROGA and AAA are alternatives, while PDE and matrix-function solvers consume rEIM output.",
        "scientific_contract": contract(core, "Produce efficient shared-pole rational approximants for a family of target functions.", ["positive approximation interval", "finite pole dictionary", "candidate interpolation grid", "target functions", "approximation order"], ["selected poles", "interpolation points", "per-target residues", "rational interpolants"], ["greedy dictionary residual maximization", "greedy interpolation-point selection", "form Cauchy interpolation matrix", "solve coefficients for each target"], ["positive interval endpoint", "dictionary and sampling sets cover useful candidates", "interpolation matrices remain nonsingular"], ["order n", "dictionary B", "sample set Sigma"], ["all targets share poles", "each approximant interpolates its target at selected points", "output is in partial-fraction form"], ["C1", "C2"], ["power-function approximation", "fractional PDE solutions", "adaptive time stepping", "matrix-function approximations"], "The coupled rational dictionary, adaptive shared poles, and interpolation points are specific to the proposed method.", ["E1", "E2", "E3", "E4", "E5"]),
        "gates": accepted_gates({"G1": ["E1", "E7"], "G2": ["E1", "E7"], "G3": ["E2", "E3", "E5"], "G4": ["E3", "E4", "E5"], "G5": ["E5", "E7"]}, {"G1": "rEIM directly carries the new-method contribution.", "G2": "The paper distinguishes rEIM from comparison methods and downstream applications.", "G3": "It requires paper-specific rational-dictionary and invariant-pole reasoning.", "G4": "Its algorithm states finite inputs and rational interpolant outputs.", "G5": "Shared poles support new target families, orders, intervals, and application operators."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


def record_0022() -> dict[str, Any]:
    ev = evidence(
        [
            (1, "Abstract", "A sketch-and-select Arnoldi process to generate a well-conditioned basis of a Krylov space at low cost is proposed."),
            (4, "1 Introduction", "The goal of this paper is to provide a procedure to construct a Krylov basis Vm with the same O(N mk) runtime as truncated Arnoldi"),
            (4, "2 The sketch-and-select Arnoldi process", "instead of projecting each new Krylov basis vector against the k previous basis vectors, we use the sketched version of the Krylov basis to identify k candidates for the projection."),
            (5, "2 The sketch-and-select Arnoldi process", "we propose to select the index set I of the nonzero coefficients hi,j by approximately solving the following sparse least squares problem"),
            (6, "2 The sketch-and-select Arnoldi process", "all sketch-and-select variants only perform operations on small sketched matrices and vectors to determine the projection coefficients."),
            (12, "3.4 Application to sketched GMRES", "ssa-pinv, ssa-OMP, ssa-SP and ssa-greedy obtain on average two more digits of accuracy compared to truncated Arnoldi."),
            (23, "6 Conclusions and future work", "We have introduced a sketch-and-select Arnoldi process and demonstrated its potential to generate Krylov bases that are significantly better conditioned than those computed with the truncated Arnoldi process"),
        ]
    )
    core = "Sketch-and-select Arnoldi process"
    return {
        "schema_version": SCHEMA_VERSION, "paper_id": "0022", "evidence_catalog": ev,
        "research_goal": {"summary": "Construct a low-cost Krylov basis that stays better conditioned than truncated Arnoldi for sketch-based solvers.", "evidence": ["E1", "E2"]},
        "main_contributions": [{"id": "C1", "summary": "A sketch-and-select Arnoldi process casting limited projection as sketched sparse subset selection.", "evidence": ["E1", "E3", "E4", "E5"]}, {"id": "C2", "summary": "Better-conditioned bases and improved attainable sGMRES accuracy at linear-in-basis-dimension projection cost.", "evidence": ["E2", "E6", "E7"]}],
        "contribution_graph": [{"from": "goal", "to": "C1", "relation": "is addressed by", "evidence": ["E2", "E3"]}, {"from": "C1", "to": "C2", "relation": "is evaluated through", "evidence": ["E6", "E7"]}],
        "candidate_algorithms": [
            candidate(core, "core", "At each Arnoldi step use sketched sparse least squares to select k prior basis vectors, project, and sketch-normalize the next vector.", ["E1", "E3", "E4", "E5"], "FAILS_WITHOUT_ALGORITHM", "Removing adaptive sketch-based selection eliminates the proposed process and conditioning contribution."),
            candidate("Standard full Arnoldi", "baseline", "Orthogonalize against every preceding vector.", ["E1"], "SURVIVES_WITHOUT_ALGORITHM", "It defines the reference process but not the proposed low-cost method."),
            candidate("Truncated Arnoldi", "baseline", "Project only against the k most recent vectors.", ["E2", "E7"], "SURVIVES_WITHOUT_ALGORITHM", "It is the primary runtime-matched comparator."),
            candidate("Sparse subset-selection heuristics", "supporting", "pinv, OMP, subspace pursuit, and greedy strategies approximately choose projection support.", ["E4", "E5"], "SURVIVES_WITHOUT_ALGORITHM", "They are interchangeable solvers inside the common sketch-and-select process."),
            candidate("sGMRES", "evaluation", "Use the generated basis in a sketched linear-system solver.", ["E6"], "SURVIVES_WITHOUT_ALGORITHM", "It tests a downstream use and is not the basis-generation contribution."),
        ],
        "selected_core_algorithm": core,
        "uniqueness_reason": "The sketch-and-select process is the single umbrella algorithm; selection heuristics are replaceable inner solvers, Arnoldi variants are baselines, and sGMRES is an application.",
        "scientific_contract": contract(core, "Generate a Krylov basis with bounded projection cost and delayed conditioning growth.", ["matrix or linear operator A", "starting vector b", "basis dimension m", "selection width k", "sketch operator S"], ["Krylov basis V", "sketched basis SV", "projection coefficients H"], ["apply A", "sketch candidate vector", "solve approximate sparse subset selection", "project selected basis vectors", "normalize in sketch norm"], ["S embeds the relevant Krylov space", "k is smaller than the growing basis dimension", "no breakdown in normalization"], ["m", "k", "sketch dimension", "selection heuristic"], ["basis spans the intended Krylov sequence absent breakdown", "each sketched new vector is normalized", "at most k prior vectors are projected per step"], ["C1", "C2"], ["SuiteSparse conditioning profiles", "sGMRES accuracy tests"], "It integrates randomized embeddings, sparse model selection, and Krylov recurrence while retaining linear projection cost.", ["E1", "E2", "E3", "E4", "E5"]),
        "gates": accepted_gates({"G1": ["E1", "E7"], "G2": ["E3", "E4", "E5"], "G3": ["E3", "E4"], "G4": ["E2", "E3", "E4"], "G5": ["E6", "E7"]}, {"G1": "The process directly carries the paper's conditioning-versus-cost contribution.", "G2": "Inner selection variants instantiate one process; other Arnoldi methods and sGMRES are not co-core.", "G3": "The method requires a paper-specific coupling of Krylov recurrence, randomized sketching, and sparse selection.", "G4": "A, b, m, k, and S determine basis and coefficient outputs.", "G5": "The same process can be tested across matrices, starts, sketch dimensions, k, and selection strategies."}),
        "evidence_gaps": [], "decision": "ACCEPT_FOR_DESIGN",
    }


RECORD_BUILDERS = {
    "0011": record_0011,
    "0014": record_0014,
    "0015": record_0015,
    "0017": record_0017,
    "0018": record_0018,
    "0019": record_0019,
    "0020": record_0020,
    "0021": record_0021,
    "0022": record_0022,
}


def load_sources(repo_root: Path) -> dict[str, PaperSource]:
    sources: dict[str, PaperSource] = {}
    for paper_id in PAPER_IDS:
        path = source_path(repo_root, paper_id)
        if not path.is_file():
            raise ValueError(f"{paper_id}: missing source PDF: {path}")
        source = extract_pdf(path, paper_id)
        if source.sha256 != EXPECTED_HASHES[paper_id]:
            raise ValueError(f"{paper_id}: source SHA256 mismatch")
        if source.redaction_markers:
            raise ValueError(f"{paper_id}: source contains redaction markers")
        for prior_root in (V2_ROOT, GLM_ROOT):
            metadata_path = repo_root / prior_root / paper_id / "metadata.json"
            if metadata_path.is_file():
                prior = json.loads(metadata_path.read_text(encoding="utf-8"))
                if prior.get("source_sha256") != source.sha256:
                    raise ValueError(f"{paper_id}: source differs from {prior_root.name}")
        sources[paper_id] = source
    return sources


def validate_records(sources: dict[str, PaperSource]) -> dict[str, dict[str, Any]]:
    records = {paper_id: RECORD_BUILDERS[paper_id]() for paper_id in PAPER_IDS}
    for paper_id in PAPER_IDS:
        validate_final_record(records[paper_id], sources[paper_id])
    return records


def metadata(source: PaperSource, rubric_hash: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_id": source.paper_id,
        "source_path": str(source.path),
        "source_sha256": source.sha256,
        "rubric_sha256": rubric_hash,
        "model": MODEL,
        "page_count": len(source.pages),
        "character_count": source.char_count,
        "nonempty_page_ratio": source.nonempty_page_ratio,
        "redaction_markers": list(source.redaction_markers),
        "reviewed_at": now(),
        "call_mode": CALL_MODE,
        "call_count": 0,
        "token_usage": [],
    }


def write_reviews(repo_root: Path, output_root: Path, sources: dict[str, PaperSource], records: dict[str, dict[str, Any]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    rubric_hash = sha256(repo_root / "PAPER.md")
    for paper_id in PAPER_IDS:
        paper_dir = output_root / paper_id
        atomic_write_json(paper_dir / "metadata.json", metadata(sources[paper_id], rubric_hash))
        atomic_write_json(paper_dir / "call_events.json", [])
        atomic_write_json(paper_dir / "raw_responses.json", [])
        atomic_write_json(paper_dir / "errors.json", [])
        atomic_write_json(paper_dir / "record.json", records[paper_id])


def summary_item(paper_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "status": "COMPLETE",
        "selected_core_algorithm": record["selected_core_algorithm"],
        "gates": {gate: record["gates"][gate]["status"] for gate in record["gates"]},
        "decision": record["decision"],
        "evidence_gaps": record["evidence_gaps"],
    }


def write_summary(output_root: Path, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    papers = [summary_item(paper_id, records[paper_id]) for paper_id in PAPER_IDS]
    value = {"schema_version": SCHEMA_VERSION, "generated_at": now(), "model": MODEL, "call_mode": CALL_MODE, "complete_count": len(papers), "failed_count": 0, "blind_review": False, "blind_review_disclosure": "This was a local evidence-based review, but not a strict blind review: Codex had seen parts of earlier review summaries in the conversation.", "papers": papers}
    atomic_write_json(output_root / "summary.json", value)
    lines = ["# Local Codex Core-Algorithm Review", "", "Model: `codex-local-review` (local manual review; zero API calls)", "", "> This is evidence-based but not a strict blind review: Codex had seen parts of earlier review summaries in the conversation.", "", "| Paper | Core algorithm | G1–G5 | Decision |", "| --- | --- | --- | --- |"]
    for item in papers:
        gate_text = ", ".join(f"{gate}:{item['gates'][gate]}" for gate in ("G1", "G2", "G3", "G4", "G5"))
        lines.append(f"| {item['paper_id']} | {item['selected_core_algorithm'] or '—'} | {gate_text} | {item['decision']} |")
    atomic_write_text(output_root / "summary.md", "\n".join(lines) + "\n")
    return value


def load_run(root: Path) -> dict[str, Any]:
    path = root / "summary.json"
    if not path.is_file():
        return {"model": root.name, "complete_count": 0, "failed_count": len(PAPER_IDS), "papers": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_comparison(repo_root: Path, output_root: Path, codex_summary: dict[str, Any]) -> None:
    runs = {"v2": load_run(repo_root / V2_ROOT), "glm52": load_run(repo_root / GLM_ROOT), "codex": codex_summary}
    by_run = {name: {item["paper_id"]: item for item in run["papers"]} for name, run in runs.items()}
    rows = []
    disagreement_count = 0
    for paper_id in PAPER_IDS:
        complete = {name: values.get(paper_id) for name, values in by_run.items() if values.get(paper_id, {}).get("status") in {"COMPLETE", "RESUMED"}}
        comparisons: dict[str, Any] = {}
        names = tuple(complete)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                a, b = complete[left], complete[right]
                gate_matches = {gate: a["gates"][gate] == b["gates"][gate] for gate in ("G1", "G2", "G3", "G4", "G5")}
                mismatch = a.get("selected_core_algorithm") != b.get("selected_core_algorithm") or a.get("decision") != b.get("decision") or not all(gate_matches.values())
                comparisons[f"{left}_vs_{right}"] = {"core_match": a.get("selected_core_algorithm") == b.get("selected_core_algorithm"), "gate_matches": gate_matches, "decision_match": a.get("decision") == b.get("decision"), "disagreement": mismatch}
                disagreement_count += int(mismatch)
        rows.append({"paper_id": paper_id, "statuses": {name: by_run[name].get(paper_id, {"status": "MISSING"}).get("status", "MISSING") for name in runs}, "completed_reviews": list(complete), "comparisons": comparisons, "note": "FAILED or MISSING runs are excluded from disagreement calculations."})
    value = {"schema_version": SCHEMA_VERSION, "generated_at": now(), "models": {name: run.get("model") for name, run in runs.items()}, "coverage": {name: {"complete": run.get("complete_count", 0), "failed": run.get("failed_count", 0)} for name, run in runs.items()}, "pairwise_disagreement_count": disagreement_count, "aggregation": "none; FAILED is not a disagreement and no majority vote was performed", "papers": rows}
    atomic_write_json(output_root / "comparison_all_reviews.json", value)
    lines = ["# Comparison of All Core-Algorithm Reviews", "", "FAILED/MISSING runs are excluded from disagreement calculations. No merge or majority vote was performed.", "", "| Paper | v2 | GLM-5.2 | Codex | Comparable pairs |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        pair_text = "; ".join(f"{pair}:{'disagree' if data['disagreement'] else 'match'}" for pair, data in row["comparisons"].items()) or "—"
        lines.append(f"| {row['paper_id']} | {row['statuses']['v2']} | {row['statuses']['glm52']} | {row['statuses']['codex']} | {pair_text} |")
    atomic_write_text(output_root / "comparison_all_reviews.md", "\n".join(lines) + "\n")


def validate_output(output_root: Path, sources: dict[str, PaperSource]) -> None:
    expected_common = {"metadata.json", "call_events.json", "raw_responses.json", "errors.json", "record.json"}
    for paper_id in PAPER_IDS:
        paper_dir = output_root / paper_id
        names = {path.name for path in paper_dir.iterdir() if path.is_file()}
        if names != expected_common:
            raise ValueError(f"{paper_id}: incompatible artifact set: {sorted(names)}")
        metadata_value = json.loads((paper_dir / "metadata.json").read_text(encoding="utf-8"))
        if metadata_value.get("model") != MODEL or metadata_value.get("call_mode") != CALL_MODE:
            raise ValueError(f"{paper_id}: local review provenance mismatch")
        if metadata_value.get("call_count") != 0 or metadata_value.get("token_usage") != []:
            raise ValueError(f"{paper_id}: local review contains call or token usage")
        for empty_name in ("call_events.json", "raw_responses.json", "errors.json"):
            if json.loads((paper_dir / empty_name).read_text(encoding="utf-8")) != []:
                raise ValueError(f"{paper_id}: {empty_name} must be empty")
        record_value = json.loads((paper_dir / "record.json").read_text(encoding="utf-8"))
        validate_final_record(record_value, sources[paper_id])
    required_top = {"summary.json", "summary.md", "comparison_all_reviews.json", "comparison_all_reviews.md"}
    if not required_top.issubset({path.name for path in output_root.iterdir()}):
        raise ValueError("missing top-level summary/comparison artifacts")
    forbidden = ("api_key", "api endpoint", '"endpoint":', "endpoint_url", "http response", "request_config")
    for path in output_root.rglob("*"):
        if path.is_file():
            lowered = path.read_text(encoding="utf-8", errors="ignore").lower()
            if any(marker in lowered for marker in forbidden):
                raise ValueError(f"forbidden remote-call material in {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true", help="write records, then summaries and comparisons")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    sources = load_sources(repo_root)
    records = validate_records(sources)
    if args.write:
        write_reviews(repo_root, output_root, sources, records)
        codex_summary = write_summary(output_root, records)
        write_comparison(repo_root, output_root, codex_summary)
    validate_output(output_root, sources)
    print(f"validated {len(records)} local Codex review records in {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
