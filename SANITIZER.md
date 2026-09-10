# Scientific Sanitizer-Guided Test Generation

## 1. Overview

Scientific sanitizer-guided test generation is a benchmark task for evaluating
whether a coding agent can discover scientifically meaningful failures in an
existing repository.

The agent receives a repository instrumented with **public scientific
sanitizers**. It may inspect the sanitizer definitions, run the code, and
iteratively generate tests. Its objective is to trigger as many distinct
sanitizers as possible through valid uses of the repository's public APIs.

This is intentionally a guided task. The agent is not expected to blindly fuzz
the repository. Reading and reasoning about the sanitizers is part of the task.

## 2. Task Definition

### Input

The agent receives one public, instrumented repository containing:

- the original scientific implementation;
- public sanitizer source code and descriptions;
- instructions for enabling sanitizer logging;
- the normal build and test environment.

An additional uninstrumented repository is not required for the task.

### Agent objective

The agent must add tests that:

1. call the repository through normal public APIs;
2. use inputs allowed by the API and sanitizer preconditions;
3. execute successfully in the evaluation environment; and
4. trigger as many distinct scientific sanitizer families as possible.

The agent may read sanitizer conditions and use observed sanitizer triggers to
refine its tests. This behavior is intended, not leakage.

### Output

The agent submits a test-only patch. Production code and sanitizer changes are
not part of the scored output.

## 3. What Is a Scientific Sanitizer?

A scientific sanitizer is non-disruptive runtime instrumentation that observes
a program state and records when a scientifically, mathematically, or
numerically meaningful condition is violated.

Each sanitizer consists of four parts:

```text
Precondition  -> inputs and program states for which the rule applies
Invariant     -> the expected scientific or numerical property
Observation   -> the values observed at a meaningful execution point
Alarm         -> the predicate that records a trigger
```

A sanitizer should log an alarm rather than raise an exception or change the
program result. Instrumentation should be inactive unless evaluation explicitly
enables it.

## 5. Sanitizer Design Principles

### 5.1 Check meaningful assumptions

A sanitizer should protect an assumption that a downstream scientific
calculation relies on. A violation should indicate a state worth investigating,
even if the current repository never reaches it.

Good observation points include:

- after a nontrivial calculation or iterative process;
- before a value is used as a denominator, index, dimension, or model parameter;
- at a function or module boundary;
- after a scientific representation or unit conversion;
- before returning a derived scientific quantity.

### 5.2 Avoid local tautologies

Do not mechanically restate the immediately preceding implementation.

Weak sanitizer:

```python
cystine = reduced + cysteine_pairs * 125
sanitize(cystine >= reduced)
```

The condition is already guaranteed by the adjacent expression under ordinary
types and therefore observes no meaningful intermediate risk.

Stronger sanitizer:

```python
optimized = optimize_coding_sequence(sequence)
sanitize(translate(optimized) == translate(sequence))
```

This checks a scientific semantic property across a nontrivial transformation.

Distance in lines is not itself the criterion. The important question is
whether a value has passed through enough computation, transformation, or
cross-component data flow that the required property is not locally guaranteed.

### 5.3 State the precondition

Every sanitizer must define the inputs for which its invariant is valid. It
must distinguish a scientific violation from documented rejection of invalid
input.

### 5.4 Do not optimize for triggerability during design

Sanitizers are selected for scientific meaning, not because a witness is already
known. A well-designed sanitizer may be unreachable in the pinned version.
Reachability analysis is a later, separate activity and must not distort the
initial sanitizer design.

### 5.5 Preserve normal behavior

Instrumentation must not alter return values, exception behavior, persistent
state, numerical precision, or normal performance when disabled.

### 5.6 Guard a scientific law, not an arithmetic identity

Every sanitizer must protect a **scientific** invariant: a physical, chemical,
geometric, thermodynamic, or otherwise domain-level property whose violation
would change the scientific interpretation of a result. Examples: charge
neutrality at the isoelectric point, mass conservation across a condensation
reaction, monotonic dependence of melting temperature on ionic strength,
invariance of a bond angle under rigid motion, sign change of a dihedral under
reflection.

The following are **out of scope** and must not be added, even though a
violation would be a genuine bug:

- pure arithmetic identities that hold by construction under ordinary types
  (a partition of percentages summing to 100, a windowed average equal to the
  mean of its parts);
- range, finiteness, or `NaN`/`inf` checks with no independent cross-check of
  the value's correctness;
- round trips through a fixed lookup table or bijection (three-letter to
  one-letter amino-acid codes);
- generic software-correctness assertions a unit test would ordinarily make.

When a candidate invariant is really a restatement of the implementation's
arithmetic rather than a domain law, drop it. The bank's value is measured by
distinct triggered *scientific* root-cause families (section 7), not by
sanitizer count.

### 5.7 State a general law, not a known bug

A sanitizer must be one the curator could write **without knowing whether the
repository has a defect at that point**. It asserts a general scientific law
and lets the evaluation discover whether the code obeys it. It must not be
reverse-engineered from a specific failing input.

Concretely:

- **Precondition = the input class over which the law holds**, expressed as a
  continuous or enumerable family (all sequence lengths, all split points, all
  ionic strengths in a range, all rigid motions, all substitution matrices).
  It must **not** pin the single degenerate point that happens to fail (the
  empty sequence, the one-residue peptide, the all-`ATG`/`TGG` coding
  sequence, a two-element residue set).
- **Alarm = violation of the law.** It compares two values the law says must
  agree (a quantity and its transform through the real API, or a quantity and
  an independent path to it). It must **not** compare the result to a
  hard-coded constant that is the "right answer" for one input.
- **Domain of meaning.** The sanitizer must be meaningful across the whole
  precondition family, not on exactly one input. A degenerate case is in scope
  only when it is *covered by* a general family -- the empty sequence as the
  `k = 0` end of a split-additivity law, the one-residue peptide as `L = 1` of
  a length-decomposition law -- never as a hand-written special case.

Red flags that a candidate is a disguised bug report, not a law:

| Symptom | Why it is wrong |
|---|---|
| Precondition names one input or a tiny finite set | The curator already knows that input fails; the sanitizer only re-describes it. |
| Alarm is `result != <literal>` or `result != 0` | Asserts the expected output of one case, not a relationship that holds generally. |
| Removing the sanitizer would lose coverage of exactly one input | It is a unit test for a known bug, not a scientific invariant. |
| The rationale explains a mechanism ("end atoms of the chain are added even when empty") | The curator is describing the bug's cause, which means they worked backward from it. |

Good pattern: the sanitizer states a law over a family; whether any member of
that family violates it is unknown at design time and is exactly what the
evaluation measures (SANITIZER.md 5.4). Physical- and chemical-constant
consistency checks are a natural fit: assert that a constant used in a formula
(a condensation-water mass, a residue-mass table entry, the gas constant `R`)
matches the repository's own authoritative table or an accepted reference
value, without knowing whether it does.

#### 5.7.1 Order of work: law first, triggering later

The construction order is not negotiable:

1. Pick a function with an identifiable scientific quantity.
2. Write down the law that quantity must obey -- precondition, invariant,
   observation point, alarm, rationale -- **as a document, before writing any
   checker code and before running a single input through the function to see
   what it does.**
3. Implement the checker from that document.
4. Only *after* the sanitizer is written and reviewed, and as a **separate
   activity**, explore whether it can be triggered on the pinned commit
   (SANITIZER.md 5.4, 8). The result is recorded as audit metadata; it never
   feeds back into whether the sanitizer is kept.

If you have already run inputs and seen a failure at some spot, you are no
longer in a position to write an unbiased sanitizer there: you will
unconsciously shape the precondition and alarm around the failure you saw.
Either hand that spot to a different curator, or write the law you would have
written *without* the failure in view and check that the wording does not
mention it.

#### 5.7.2 The triggerability trap

Finding a bug gives instant feedback -- a trigger fires, the log fills, it
feels productive. Writing a law that may stay silent forever gives no
feedback at all. This asymmetry pulls curators toward "find something that
triggers" and away from "state the invariant that matters". Resist it:

- A bank of well-chosen laws that are **all silent** on the pinned commit is a
  *success*, not a failure -- it means the code is correct at every point
  checked, and the bank will catch the first regression that is not.
- Do not go looking for triggering inputs while designing. Do not prefer a
  candidate because you already have a witness for it. Do not drop a candidate
  because you cannot find one.
- The primary metric (distinct triggered scientific root-cause families) is
  raw audit data about the code under test. It is **not** a measure of bank
  quality. The bank's quality is the set of laws it states and whether each is
  a genuine domain invariant written without foreknowledge of a bug.

## 6. Scientific Scenarios to Inspect

Manual code scanning should consider more than long-range variable flow.
Candidate sanitizer scenarios include:

- **Domain constraints:** nonzero denominators, positive logarithm inputs,
  valid square-root arguments, and bounded probabilities or fractions.
- **Numerical validity:** unexpected `NaN`, infinity, overflow, underflow, or
  loss of an integer-valued scientific quantity.
- **Units and dimensions:** incompatible units, incorrect scale factors, and
  inconsistent dimensional quantities.
- **Conservation laws:** mass, charge, atom counts, sequence semantics, total
  probability, or other conserved quantities.
- **Normalization:** probabilities, frequencies, weights, and compositions that
  should sum to a specified value.
- **Symmetry and invariance:** transformations such as reversal, complement,
  rotation, translation, coordinate changes, or exchange of equivalent objects.
- **Monotonicity:** quantities that should move in a theoretically determined
  direction as pH, concentration, distance, dose, or an iteration variable
  changes.
- **Discrete structure:** valid shapes, reading frames, window sizes, indices,
  residue counts, and matrix structure.
- **Physical feasibility:** nonnegative distances, valid occupancies, plausible
  parameter ranges, and other model-specific constraints.
- **Convergence:** residuals, errors, gradients, or fixed-point conditions at
  the end of an iterative algorithm.
- **Cross-representation consistency:** equivalent dense and sparse forms,
  coordinate systems, sequence representations, or serialized forms.
- **Cross-method consistency:** independently implemented paths that should
  produce compatible scientific results.
- **Intermediate-state integrity:** scientific meaning preserved through
  filtering, sorting, caching, aggregation, and conversion.
- **Parameter interactions:** combinations that become invalid even when each
  parameter is individually valid.
- **Boundary and degenerate cases:** empty, singleton, homogeneous, extreme, or
  numerically ill-conditioned valid inputs.

These are search directions, not universal facts. Curators must interpret them
in the domain and API context of the selected code.

## 6. Construction Workflow

### Step 1: Select a scientific subsystem

Choose a bounded module or API with identifiable scientific quantities and an
executable test environment. Pin the repository commit and dependencies.

### Step 2: Scan the implementation

Read the code as a combination of data flow and scientific assumptions:

1. identify scientific quantities;
2. trace how they are computed and transformed;
3. identify what later operations assume about them;
4. locate places where those assumptions are not locally guaranteed.

Useful code patterns include division, normalization, iterative search,
windowing, aggregation, casting, unit conversion, translation, complementing,
matrix operations, and cross-module calls.

This step is a **static read for scientific quantities and their laws**. It is
not a debugging session: do not run inputs through the function to see whether
it misbehaves. Finding a concrete failure here biases every sanitizer you then
write for that spot (SANITIZER.md 5.7.1).

### Step 3: Formulate the sanitizer

For each candidate, write, **as a document, before implementing the checker
and before observing any run of the function**:

- the valid-input precondition -- the input family over which the law holds,
  never a single failing point (SANITIZER.md 5.7);
- the scientific invariant;
- the observation point;
- the alarm predicate -- a comparison of two things the law says must agree,
  never `result != <literal>`;
- why a violation would be meaningful;
- the root-cause family.

A reader of this document must not be able to tell whether the code has a bug
at this point. If they can, the candidate was reverse-engineered from a
failure -- rewrite it or drop it.

### Step 4: Instrument the code

Insert a lightweight runtime check at the semantic boundary. Trigger records
should contain stable sanitizer IDs and should be append-only. One execution may
trigger multiple sanitizers.

### Step 5: Manually review

Reject or revise sanitizers that:

- restate an adjacent assignment;
- lack a clear scientific or numerical interpretation;
- omit essential preconditions;
- merely duplicate another sanitizer without adding an observation point;
- change normal program behavior;
- alarm on documented valid behavior;
- were reverse-engineered from a known failing input: a precondition that pins
  one degenerate case, or an alarm of the form `result != <literal>` (see
  5.7).

Review test, applied to the formulation document alone: hand it to someone who
has not seen the code run. If they can tell that the code fails at this point,
the sanitizer encodes a known bug -- send it back.

The review need not establish whether the sanitizer is reachable. A sanitizer
that no known input triggers is accepted on the strength of its law
(SANITIZER.md 5.4, 5.7.2); do not weaken or discard it for being silent.

### Step 6: Group related sanitizers

Different alarms may expose the same underlying defect. Assign them to one
root-cause family so that redundant observations do not inflate the primary
score.

### Step 7: Freeze the task

Record the pinned commit, environment, sanitizer manifest, test policy, runtime
budget, and scoring rules before evaluating agents.

## 8. Sanitizer Metadata

Each sanitizer should have machine-readable metadata similar to:

```json
{
  "id": "BP-SEQ-005",
  "family": "cai_degenerate_sequence",
  "source": "Bio/SeqUtils/__init__.py",
  "symbol": "CodonAdaptationIndex.calculate",
  "scientific_quantity": "codon adaptation index",
  "precondition": "a valid in-frame coding DNA sequence",
  "invariant": "the calculated CAI is finite",
  "observation_point": "before returning the calculated CAI",
  "alarm": "the effective codon count is zero or the result is non-finite",
  "rationale": "a valid scientific metric should produce a numerical result"
}
```

Witnesses and reachability labels are not required during sanitizer design.
They may be added to evaluator-side audit artifacts later.

## 8. Triggerability Analysis

After the sanitizer set is designed and reviewed, curators may separately
explore whether each sanitizer can be triggered on the pinned repository.
Possible methods include manual tests, property-based testing, fuzzing, symbolic
reasoning, and agent-generated tests.

The outcomes should be described precisely:

- **observed triggered:** at least one valid witness was executed;
- **observed untriggered:** no witness was found within the stated search;
- **proven unreachable:** unreachable under explicit assumptions and a stated
  proof argument;
- **unknown:** not sufficiently analyzed.

Observed untriggered must not be reported as permanently unreachable. The task
allows meaningful sanitizers that happen not to trigger on the current version.

## 9. Evaluation Pipeline

The recommended evaluation flow is:

```text
public instrumented repository
            |
            v
agent reads sanitizers and generates tests
            |
            v
extract and validate the test-only patch
            |
            v
apply tests to a clean evaluator checkout
            |
            v
run only the submitted tests with sanitizer logging enabled
            |
            v
deduplicate triggers and produce a result record
```

### 9.1 Isolation and validity

The evaluator should:

- apply the submission to a fresh checkout at the pinned commit;
- accept only changes in approved test locations;
- reject direct calls to the sanitizer logger;
- reject fabricated trigger-log writes;
- prevent tests from modifying sanitizer or production source code;
- run tests with fixed dependencies and resource limits;
- count only triggers produced while submitted tests execute.

The agent must trigger sanitizers through normal repository behavior. Merely
calling a private `trigger()` function is not a valid solution.

### 9.2 Agent interaction

The sanitizer definitions are public. The agent may:

- inspect their source and metadata;
- reason backward from alarm predicates to candidate inputs;
- run its tests and observe trigger logs;
- revise tests within the allotted budget.

This targeted feedback loop is the central behavior under evaluation.

### 9.3 Metrics

The primary metric is:

```text
number of unique triggered root-cause families
```

Secondary metrics include:

- number of unique triggered sanitizer IDs;
- number and fraction of submitted tests that execute successfully;
- invalid-input or policy-violating tests;
- wall-clock time, interaction steps, and token cost;
- triggers per valid test or per unit of budget.

Because some meaningful sanitizers may be unreachable, raw counts should be
reported directly. A reachability-normalized score should only be reported when
the reachable set has been established separately and reliably.

## 10. Pilot Protocol

A minimal pilot should:

1. select one bounded Biopython subsystem;
2. manually construct and review a small sanitizer bank;
3. publish the instrumented repository and sanitizer descriptions;
4. implement a deterministic test-only evaluation runner;
5. give a fresh-context agent only the official task materials;
6. run several independent attempts under the same budget;
7. report family triggers, raw sanitizer triggers, invalid tests, and cost;
8. audit the generated tests and refine the construction guidelines.

Fresh-context agents are useful experimental subjects, but they do not replace
the evaluation pipeline. Reproducible scoring must come from a clean, automated
runner.

## 11. Scope and Non-Goals

This task does not require:

- an existing issue or closing pull request;
- a known bug for every sanitizer;
- a gold regression test;
- proof that every sanitizer is reachable or unreachable;
- blind random test generation;
- agent modification of production code.

The task evaluates whether an agent can understand public scientific runtime
conditions and construct valid tests that reach meaningful violations.

