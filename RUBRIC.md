# Task Scoring Protocol

## 1. Goal

For every benchmark task, characterize **what type of expertise it primarily requires** and **how difficult the scientific and software-engineering components are**.

Each task receives five primary annotations:

- **Domain**
- **Science Share**
- **SWE Share**
- **Science Difficulty**
- **SWE Difficulty**

The two concepts are deliberately separated:

- **Science/SWE Composition** = _Which type of expertise is required to solve the task reliably?_
- **Science/SWE Difficulty** = _How demanding is each side, considered independently?_

Therefore, a task may simultaneously be:

> Science 50% / SWE 50%  
> Science Difficulty = Hard  
> SWE Difficulty = Hard

Difficulty must **not** be used to determine composition.

---

## 2. General Annotation Principle

We use a **holistic rubric**, rather than decomposing each task into many weighted sub-dimensions.

This avoids:

1. overlapping dimensions;
2. double-counting the same challenge;
3. arbitrary weighting choices;
4. unnecessary complexity for AI judges and human annotators.

The rubric is anchored to the task's scientific discipline, concrete human expertise profiles, and code-reasoning scope:

- Domain: **Scientific discipline primarily required by the task**
- Composition: **Programmer / Scientist–Programmer Collaboration / Scientist**
- Science Difficulty: **Undergraduate / Graduate / Research level**
- SWE Difficulty: **Function-level / Module-level / System-level**

The annotation should characterize the **minimum expertise needed for reliable completion**, not the observed performance of a particular AI model.

---

# 3. Domain

## 3.1 Definition

Domain asks:

> **Which scientific discipline provides the primary domain knowledge required to solve the task?**

Assign exactly one primary scientific domain using a consistent controlled vocabulary across the benchmark. Example labels include:

- Mathematics
- Physics
- Astronomy
- Chemistry
- Materials Science
- Biology
- Bioinformatics
- Neuroscience
- Earth Science
- Geographical Information Science
- Energy Science
- Other

The label should reflect the **scientific knowledge actually required by the task**, not merely the repository name, paper venue, or application context.

For interdisciplinary tasks, assign the domain that is most central to determining the scientifically correct solution. If no single domain is clearly primary, use `interdisciplinary`.

Domain is **descriptive metadata, not a difficulty or composition score**. It must not influence Science Share, SWE Share, Science Difficulty, or SWE Difficulty.

---

# 4. Science vs. SWE Composition

## 4.1 Definition

Composition asks:

> **Which human expertise profile would be sufficient to solve the task reliably?**

We use three composition classes and map them to fixed percentages for reporting.

| Composition Class | Human Expertise Anchor | Science | SWE |
|---|---|---:|---:|
| **SWE-dominant** | Programmer | **20%** | **80%** |
| **Joint** | Scientist–Programmer Collaboration | **50%** | **50%** |
| **Science-dominant** | Scientist | **80%** | **20%** |

The percentages are **fixed labels for visualization and dataset statistics**, not fine-grained measurements estimated by the judge.

---

## 4.2 SWE-dominant — Programmer

### Definition

A **strong general programmer without specialized scientific training** can reliably solve the task from the provided task materials, codebase, and explicit scientific specification.

Scientific content may be present, but it can be treated largely as an external specification rather than something the solver must independently derive or interpret.

### Typical evidence

- The correct scientific behavior, formula, constraint, or expected output is already explicitly stated.
- The solver does not need to infer a non-obvious scientific oracle, valid scientific input, or scientific method.
- The main challenge is repository exploration, localization, API usage, implementation, debugging, testing, or integration.
- Supplying one explicit domain fact is enough for a general programmer to complete the rest of the task independently.

### Counterfactual test

> If the scientific terminology were replaced by an explicit behavioral specification, would a strong general programmer still be able to solve the task reliably?

If **yes**, the task is likely **SWE-dominant (20/80)**.

---

## 4.3 Joint — Scientist–Programmer Collaboration

### Definition

Reliable completion requires **both domain-scientific expertise and non-trivial software-engineering expertise**. Neither side can be reduced to a simple specification or mechanical implementation.

A domain scientist is needed to determine part of the correct scientific solution, while a programmer is needed to realize that solution in a non-trivial codebase or software workflow.

### Typical evidence

The scientific side must independently determine one or more of:

- the scientifically valid input or trigger condition;
- the correct scientific oracle or expected behavior;
- the appropriate equation, algorithm, model, or assumption;
- a numerical, physical, chemical, biological, or statistical constraint.

At the same time, the SWE side still requires one or more of:

- non-obvious repository localization;
- tracing data/control flow across several functions or files;
- understanding internal APIs;
- integrating multiple components;
- substantial debugging or test setup.

### Counterfactual test

Both statements should be true:

1. **If the programmer fully understood the codebase but lacked the relevant science, the correct scientific behavior would still be unclear.**
2. **If the scientist supplied the correct scientific interpretation, substantial non-trivial engineering work would still remain.**

If both hold, the task is **Joint (50/50)**.

---

## 4.4 Science-dominant — Scientist

### Definition

A **domain scientist with ordinary research-programming ability** can reliably solve the task, while a strong general programmer without the relevant scientific expertise would be unlikely to determine the correct solution.

The central challenge is scientific interpretation, derivation, or method selection; once this scientific reasoning is correct, the coding work is relatively local and straightforward.

### Typical evidence

- The solver must independently infer the correct scientific oracle.
- The solver must construct a scientifically valid edge case or trigger condition.
- The solver must understand or derive the paper's scientific method, equation, or algorithm.
- Scientific assumptions, invariants, or domain semantics determine the implementation.
- Once the scientific reasoning is resolved, implementation is a local test, standalone function, small script, or straightforward numerical program.

### Counterfactual test

> If the correct scientific derivation, method, and expected behavior were explicitly given, would the remaining implementation be relatively straightforward for a competent programmer?

If **yes**, and the scientific reasoning itself is indispensable, the task is likely **Science-dominant (80/20)**.

---

## 4.5 Scientific Relevance Filter

Tasks in this benchmark are intended to require meaningful scientific reasoning.

If a strong general programmer can solve the task entirely from code behavior, API contracts, or explicit specifications **without any substantive scientific understanding**, the judge should flag:

```text
science_relevance = insufficient
```

Such tasks should be manually reviewed and considered for exclusion rather than assigned an artificial Science share.

---

# 5. Science Difficulty

## Definition

Science Difficulty asks:

> **What is the minimum level of scientific expertise required to reliably solve the scientific component of the task?**

The judge directly assigns one of three levels.

| Difficulty | Human Expertise Anchor | Definition |
|---|---|---|
| **Easy** | **Undergraduate level** | A student who has completed relevant undergraduate coursework can reliably solve the scientific component using standard textbook concepts, definitions, formulas, or well-established methods. |
| **Medium** | **Graduate / early-research level** | Requires graduate-level coursework or initial research exposure. The solver must understand specialized methods, combine multiple scientific concepts, reason about assumptions or boundary conditions, or correctly interpret a research-paper method. |
| **Hard** | **Research-expert level** | Requires active research expertise in the relevant area. The task depends on subtle theory, non-obvious derivation/generalization, specialist conventions, paper-specific methodology, or domain knowledge that a typical graduate student would not reliably possess without additional literature study. |

### Important rule

Science Difficulty measures the **scientific component only**. A scientifically simple task does not become Hard merely because the codebase is large.

---

# 6. SWE Difficulty

## Definition

SWE Difficulty asks:

> **Once the intended scientific behavior is known, what scope of software reasoning is required to produce and validate a correct executable solution?**

The judge directly assigns one of three levels based on the **minimum code scope that must be understood jointly**, not patch size or number of modified lines.

| Difficulty | Code Scope Anchor | Definition |
|---|---|---|
| **Easy** | **Function-level / Local** | The solution can be implemented and validated by understanding one function, one test target, or a small local code region. The relevant interface is clear; little or no cross-file tracing is required. Typical work includes a standalone function/script, localized regression test, simple control flow, or direct API usage. |
| **Medium** | **Module-level / Component-level** | Correctness requires understanding interactions among multiple functions/classes within one coherent module or subsystem. The solver may need to trace data/control flow across several files, understand internal APIs, coordinate related components, and perform iterative debugging, but does not need system-wide architectural reasoning. |
| **Hard** | **System-level / Cross-component** | Correctness requires reasoning across multiple modules, subsystems, packages, or execution layers. The solver must understand non-local interactions or architecture, and may need to handle cross-language boundaries, build systems, distributed/HPC/GPU execution, complex dependency chains, or end-to-end integration. |

### Scope rule

The level is determined by the **reasoning scope required for a correct solution**, not by superficial code statistics.

For example:

- A one-line patch can still be **Hard** if finding and validating it requires system-level reasoning.
- A 100-line standalone numerical implementation can still be **Easy** if it is self-contained and function-level.

### Paper-replication interpretation

For paper replication tasks:

- **Easy:** a self-contained function, notebook, or script implementing the method;
- **Medium:** a multi-stage experimental component or data-processing pipeline with interacting internal components;
- **Hard:** an end-to-end research software system requiring several subsystems, complex dependencies, build/runtime infrastructure, or distributed execution.

---

# 7. What Information the Judge Should See

The annotation should characterize the **actual benchmark task**, not merely its title or natural-language description.

## Bug-reproduction Test Generation

Provide curator-side information sufficient to understand the intended task:

- issue description;
- buggy repository snapshot or relevant source code;
- reference/fixed patch;
- relevant PR discussion when necessary;
- intended buggy vs. fixed behavior.

The judge should not infer difficulty solely from patch size, file count, or lines changed.

## Paper Replication

Provide:

- the complete paper supplied to the solver;
- task instruction;
- public input/output specification;
- reference implementation or official code for curator-side analysis;
- evaluator/hidden-input design when relevant.

The judge evaluates what the benchmark solver must infer and implement, not how complicated the official repository happens to be.

---

# 8. AI-as-a-Judge Procedure

Each task is independently annotated by multiple judges.

## Step 1 — Summarize the essential solution requirements

Before assigning labels, the judge writes a short factual summary:

> What must a successful solver actually understand and do?

The summary should separately identify the essential scientific reasoning and engineering work.

## Step 2 — Extract supporting evidence

The judge provides concrete task-specific evidence for:

- why scientific expertise is required;
- why the chosen scientific difficulty level is appropriate;
- what code scope must be understood for implementation;
- why the chosen composition persona is sufficient or insufficient.

Generic statements such as "physics is difficult" or "the repository is large" are not valid justifications.

## Step 3 — Assign Domain

Choose exactly one primary scientific discipline according to Section 3.

The judge should identify the domain based on the scientific knowledge needed for a correct solution, not solely from the repository or paper title.

## Step 4 — Assign Composition

Choose exactly one:

- `swe_dominant` → Programmer → Science 20% / SWE 80%
- `joint` → Scientist–Programmer Collaboration → Science 50% / SWE 50%
- `science_dominant` → Scientist → Science 80% / SWE 20%

The judge should explicitly state **which persona can solve the task reliably and why the alternative persona cannot**.

## Step 5 — Assign Science Difficulty

Choose exactly one:

- `easy` → Undergraduate level
- `medium` → Graduate / early-research level
- `hard` → Research-expert level

## Step 6 — Assign SWE Difficulty

Assume the intended scientific behavior is already known. Choose exactly one:

- `easy` → Function-level / Local
- `medium` → Module-level / Component-level
- `hard` → System-level / Cross-component

---

# 9. Required Judge Output

```json
{
  "domain": "physics",

  "composition": "science_dominant",
  "science_share": 80,
  "swe_share": 20,

  "science_difficulty": "hard",
  "swe_difficulty": "easy",

  "solution_requirements": {
    "science": "...",
    "swe": "..."
  },

  "composition_rationale": "...",
  "science_difficulty_rationale": "...",
  "swe_difficulty_rationale": "...",

  "persona_check": {
    "general_programmer_sufficient": false,
    "domain_scientist_with_research_coding_sufficient": true,
    "collaboration_required": false
  },

  "science_relevance": "sufficient"
}
```

---

# 10. Multiple-Judge Aggregation

Use **3 independent AI judgments per task**.

Judges must:

- receive the same task materials;
- receive the same rubric;
- not see one another's outputs.

Use **majority vote** for the categorical annotations.

### Domain

Take the majority domain label across judges. If all three judges choose different domains, send the task for manual review.

### Composition

Take the majority class among:

- SWE-dominant
- Joint
- Science-dominant

Then apply the fixed percentage mapping.

### Difficulty

Take the majority class separately for:

- Science Difficulty
- SWE Difficulty

### Human adjudication

Send the task for manual review if:

- all three judges choose different domain labels;
- all three judges choose different composition classes;
- all three judges choose different difficulty levels on either axis;
- at least one judge flags `science_relevance = insufficient`;
- the judge identifies ambiguity or contradiction between the issue/paper and the reference implementation.

---

# 11. Interpretation Examples

## Example A — Science-dominant, SWE Easy

Scientific understanding determines the valid edge case and expected physical behavior, while the regression test itself is local.

> Composition: **Science-dominant — Scientist**  
> Science / SWE: **80 / 20**  
> Science Difficulty: **Hard — Research-expert level**  
> SWE Difficulty: **Easy — Function-level**

---

## Example B — Joint, both difficult

A specialized numerical method must be understood scientifically and integrated across several interacting components of a scientific codebase.

> Composition: **Joint — Scientist–Programmer Collaboration**  
> Science / SWE: **50 / 50**  
> Science Difficulty: **Hard — Research-expert level**  
> SWE Difficulty: **Hard — System-level**

---

## Example C — SWE-dominant, module-level engineering

The scientific requirement is explicitly specified, but reproducing the bug requires tracing several internal APIs and interacting functions within one subsystem.

> Composition: **SWE-dominant — Programmer**  
> Science / SWE: **20 / 80**  
> Science Difficulty: **Easy — Undergraduate level**  
> SWE Difficulty: **Medium — Module-level**

---

## Example D — Science-dominant paper replication

Understanding the paper requires graduate-level scientific reasoning, but once the algorithm is understood it can be implemented as a compact standalone numerical program.

> Composition: **Science-dominant — Scientist**  
> Science / SWE: **80 / 20**  
> Science Difficulty: **Medium — Graduate / early-research level**  
> SWE Difficulty: **Easy — Function-level**

---

# 12. Final Design Principle

The scoring system intentionally avoids weighted sub-dimensions and intermediate numerical scores.

Each task answers four substantive questions:

1. **Which scientific domain does the task primarily belong to?**
2. **Who is sufficient to solve it reliably: a programmer, a scientist, or a scientist–programmer collaboration?**
3. **What minimum scientific expertise is required: undergraduate, graduate, or research-expert level?**
4. **What minimum software reasoning scope is required: function-level, module-level, or system-level?**

These produce the reported benchmark annotations:

> **Domain, Science Share, SWE Share, Science Difficulty, SWE Difficulty**

The central interpretation is:

> **Domain identifies the scientific discipline; composition identifies the type of expertise the task requires; difficulty identifies the depth and scope required on each side.**
