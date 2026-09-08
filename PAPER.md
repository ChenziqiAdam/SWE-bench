# Paper Replication Task 构建规则

> **如何判断论文里哪一个 scientific algorithm 足够核心，使得只给完整论文 + public I/O，solver 自己就应该能够推断出需要实现它。**

这应该成为 paper selection / task construction 的第一道核心机制。

## Benchmark scope：一篇论文，一个 core algorithm

本 benchmark 复现的是论文的 **core scientific algorithm**，不是论文中任意一个
可以执行的 algorithm，也不是整个 repository。

每篇入选论文必须能够唯一确定一个 core algorithm。它需要同时满足：

1. 直接实现论文的主要 scientific contribution；
2. 论文的主要实验或结论依赖它；
3. 删除它后，论文的核心贡献不再成立；
4. 它不是 preprocessing、baseline、standard solver、plotting 或 evaluation；
5. 从完整论文与 public I/O 可以唯一识别，而不需要 task instruction 点名。

这里的 “one algorithm” 指一个边界清晰、科学目的统一的完整方法。它可以包含
不可分割的 stages、subroutines 或论文明确提出的 variants，但它们必须共同构成
同一个 contribution，不能被任意拆成多个 task。不同 baseline、下游 application
和 ablation 不属于这个 core algorithm，除非它们是该方法定义本身不可缺少的部分。

以下情况直接 reject：

- 论文有多个地位相同的核心算法，public I/O 无法唯一消歧；
- 只能挑出一个方便测试、但不承载主要贡献的 supporting algorithm；
- task 实际复现的是某个 figure、数据处理 pipeline 或 repository function；
- 必须在 instruction 中给出算法名、公式编号或实现步骤，solver 才能确定目标。

因此，paper selection 的单位不是 “paper 中存在一个可测试算法”，而是：

> **paper 存在且仅存在一个适合作为该 task 目标的 core scientific algorithm。**

### Step 1：先构造 paper 的 contribution graph

从论文中抽：

[
\text{Research Goal}
\rightarrow
\text{Scientific Contributions}
\rightarrow
\text{Algorithms / Procedures}
\rightarrow
\text{Experiments}
\rightarrow
\text{Reported Results}
]

例如：

```text
Main scientific question
 └── Contribution A: new theoretical formulation
      └── Algorithm A
           ├── Experiment 1
           ├── Experiment 2
           └── Figure 3

 └── Contribution B: analysis / comparison
      └── standard fitting procedure
           └── Figure 4
```

这样才能区别：

* paper 的真正核心算法
* supporting algorithm
* preprocessing
* baseline
* plotting / evaluation code

SciReplicate-Bench其实也强调先做 algorithm comprehension，再进入 implementation，而不是直接把 repo function 当 task。

---

### Step 2：对每个 candidate algorithm 建立一个 **Scientific Contract**

我觉得这是最重要的数据结构。

对于每个候选算法，必须给出：

```text
Algorithm:
Scientific purpose:
Inputs:
Outputs:
Core mathematical / scientific operations:
Assumptions:
Parameters:
Scientific invariants:
Which paper contributions depend on it:
Which experiments/results are produced by it:
Why this is not a standard off-the-shelf procedure:
Evidence from paper:
```

尤其要问：

> **如果删掉这个算法，论文的主要 scientific contribution 是否还成立？**

如果答案是 yes，那它通常就不是你要的 core algorithm。

完成所有 candidate contract 后，还必须做唯一性判断：

```text
Exactly one candidate satisfies all core-algorithm requirements -> continue
Zero candidates satisfy them                                -> reject paper
Multiple candidates satisfy them                            -> reject or redesign I/O
```

---

### Step 3：给 candidate algorithm 打“task suitability”分

| Dimension                   | 含义                                             |
| --------------------------- | ---------------------------------------------- |
| **Contribution centrality** | 是否直接承载论文主要贡献                                   |
| **Scientific novelty**      | 是否包含论文特有的 scientific reasoning，而非 standard API |
| **Executable closure**      | 能否形成明确 input → algorithm → output              |
| **Input generalizability**  | 能否自然构造不同输入，而不是只能复现一个 figure                    |
| **Paper identifiability**   | 看论文 + I/O 是否应该能唯一推断出这个算法                       |

其中最后一个对你尤其重要。

例如一个算法：

```text
input: temperature, spin, field
output: magnetization curve
```

如果论文里面只有一个主要方法产生这个量，那么很好。

反过来：

```text
input: dataset
output: RMSE
```

论文里面有五个 model 都能输出 RMSE，那 solver 根本不知道你要它实现哪个。

这种就应该 reject 或重新设计 public I/O。

---

### Step 4：加入一个非常关键的 **Blind Identification Test**

选完 core algorithm 后，不直接相信 constructor。

让另一个完全独立的 AI 只看到：

1. 完整论文
2. generic task instruction
3. public input
4. public output

**不给 repo，不告诉 algorithm name。**

问它：

> “为了使程序对这些输入产生这种类型的输出，你认为论文中的哪一个具体方法/算法需要实现？请指出论文依据。”

然后检查它是不是稳定识别到 constructor 选中的算法。

例如跑 3–5 次 / 多个模型：

```text
Target algorithm agreement = 5 / 5
```

才接受。

如果出现：

```text
Agent 1 → Algorithm A
Agent 2 → Algorithm B
Agent 3 → Algorithm A
Agent 4 → generic baseline
```

说明 task 本身 **under-specified**。

这个测试实际上直接验证了你最终想要的 property：

> **solver 能不能根据 full paper + public I/O 自己 infer implementation target。**

## Formal admission gates

所有 gate 都是 hard gate，不使用可以互相补偿的加权总分。

| Gate | 必须回答的问题 | Pass 标准 |
| --- | --- | --- |
| G1 Core centrality | 该方法是否直接承载论文主要贡献？ | 删除它后主要贡献不成立 |
| G2 Uniqueness | 是否只有一个方法满足 core 定义？ | 恰好一个；多个同级候选直接 reject 或重构 I/O |
| G3 Scientific specificity | 是否需要论文特有的 scientific reasoning？ | 不是 standard API、baseline 或普通数据处理 |
| G4 Executable closure | 是否有确定的 input → output contract？ | 不依赖未声明的人类判断或不可观测中间状态 |
| G5 Generalization | hidden input 是否能测试同一方法的泛化？ | 至少覆盖新的参数区域、分支或科学边界条件 |
| G6 Paper identifiability | paper + public I/O 是否唯一指向目标？ | blind identification test 通过 |
| G7 Blind implementation / dependency closure | 独立 solver 能否只凭 public prompt 与 bundle 完成实现？ | 在干净离线环境中独立生成的 submission 通过全部 cases，且不依赖未提供资源 |
| G8 Oracle validity | gold 是否来自可信实现并经独立科学核验？ | official reproduction 与 independent audit 一致 |

判定只有三种：

```text
ACCEPT  all gates pass
REVISE  core algorithm 唯一，但 I/O、依赖或 cases 可以修复
REJECT  G1/G2/G3 不通过，或任务本质上不是 core-algorithm replication
```

### Reference-guided hidden-case design

构建任务前必须完整阅读目标论文、最初提出 core algorithm 的来源论文，以及至少一篇
最容易与 core 混淆的 baseline、extension 或 failure-analysis 论文。相关论文只能用于
推导 core contract 内的困难输入，不能把 extension 的新算法功能加入任务。

每个任务必须建立 `Scientific Hazard Catalog`；每项至少记录来源论文、DOI/版本/hash
和具体证据，科学 failure mode 或边界现象，hidden-input 构造方法，预期 invariant，
能击穿的错误实现，以及对应 hidden case。Hidden suite 必须覆盖全部已识别的重要
hazard，包括文献反例或病态结构、参数边界和退化输入、高重叠/高拥堵/稀疏/高规模
区域、与主要 baseline 分歧最大的输入，以及容易从 public examples 学到 shortcut 的
区域。

不得直接复制论文 figure/table 的完整输入和输出；必须使用新参数、原始 benchmark
数据或重新组合的结构复现同一科学现象。G5 只有在完整保存并验证
`hazard × hidden case × shortcut` 覆盖矩阵后才能通过，不能只按 hidden-case 数量
判定。

### Blind Identification Test protocol

Blind reviewer 只能看到严格 public bundle：完整论文、只指定交付文件名的
task instruction、通用 runner schema 和 public 数值 I/O。不得提供字段科学语义、
repository、curation report、algorithm name、公式/算法编号、实现步骤或
hidden cases。

G6 必须在运行时从 `.env` 读取当前的 `ENDPOINT`、`API_KEY` 和 `MODEL_NAME`，
并使用该 `MODEL_NAME` 建立三个完全独立、无共享 conversation history 的
context。不得使用脚本默认模型、缓存回答、静默 fallback 或替换模型；若 endpoint
返回的实际模型与配置不一致，必须 fail closed。至少 2/3 必须识别出同一 core
algorithm，并引用正确的论文依据。

正式 audit 必须记录配置模型名、实际返回模型名、统一完整 prompt 及其 hash、每次
独立 run 的脱敏回答、论文依据与判定，并明确记录 independent context 数量。三次
运行应使用相同 prompt protocol，但必须分别发起新的请求。不得保留 credential、
endpoint、request/response ID、provider ID 或未脱敏响应。

### Blind Implementation Test protocol

G6 只证明 solver 能识别目标算法，不能证明 solver 能完成实现。G7 必须另开
全新 context，让 blind agent 只看到最终 public bundle 和 benchmark harness
实际发送的完整 generic prompt，由它独立生成 submission。该 submission 必须在
干净离线环境中通过全部 public 与 hidden cases。

G7 环境不得访问 official repository、curation code、gold、hidden data、先前
agent response 或网络。运行时只允许 public bundle、submission、统一 runner 和
任务声明中允许的依赖。正式 audit 必须保存模型名、完整 prompt、prompt hash、
public bundle hash、runner version、生成代码及其 hash、环境信息和逐 case 结果；
credential、endpoint、provider ID 和未脱敏响应不得持久化。

Curator 编写的 reference implementation 可以测试 evaluator，但不能作为 G7 的
blind agent submission。G7 submission 不得 import、复制或在生成时接触 verifier
中的 reference program。

### Evidence provenance and implementation independence

所有报告必须使用以下名称，不得混称：

- **official oracle**：从 pinned official source 提取并执行的论文实现，用于生成或
  核验 gold；
- **independent scientific implementation**：根据论文独立编写的数学实现，用于
  与 official oracle 交叉核验；
- **curator reference submission**：constructor 编写、通过统一 submission runner
  执行的实现，只用于验证 evaluator 和满分路径；
- **blind agent submission**：agent 仅凭最终 public prompt 与 bundle 生成的实现，
  是 G7 可独立复现的唯一证据。

这些实现必须分别保存 provenance 与 hash。official oracle、independent scientific
implementation 和 blind agent submission 不得共享算法源码、互相 import，或通过
同一个 helper 间接执行同一算法。独立核验必须比较独立计算结果，不能用同一实现
同时生成 gold、确定 tolerance 和证明自身正确。

### Public instruction disclosure boundary：禁止主动解释论文

Public instruction 不得重复任何可从论文直接读出的内容，包括算法名、公式或
算法编号，输入字段的科学意义，数学操作、执行顺序和中间变量关系，
随机分布、理论界和 scientific invariants，以及对 figures、experiments、
baselines 或代码位置的指引。

Task-specific `task.md` 只允许指定交付文件名。CLI、`submission.json` 和
`input.json`/`output.json` 约定只由统一 benchmark harness 提供。若确定性
评分需要论文未规定的工程信息，必须将它编码为原始输入数据，不得用文字
解释帮助 solver。

Public schema、文件名和 case 标签也必须通过 leakage scan；除论文、通用
runner schema 和数值 I/O 外，不得包含 method hints。若删除提示后无法完成
blind identification，说明 task under-specified，应修改 I/O 或 reject paper。

Hidden cases 必须主动覆盖能击穿 shortcut、baseline、figure memorization 和只实现
部分算法的科学输入。所有构建、PDF extraction、blind-run workspace、checkout
staging 和验证必须在成功、失败或中断后清理，只保留脱敏的正式 audit
artifacts。

每个 shortcut 必须表示一种明确且不同的错误假设；不得仅给相同代码换多个名称。
Audit 必须保存 `case × shortcut` 结果矩阵、每种 shortcut 的 hidden score 和最高
shortcut score。结论只能覆盖实际测试的实现，例如：

> 已测试的 N 种预设 shortcut 均未通过完整 hidden suite；最高 hidden score 为 X。

`fails the hidden suite` 仅表示至少失败一个 hidden case；只有所有 hidden cases 都
失败时才能写 `fails every hidden case`。不得由有限的 mutation tests 推广为“所有
错误实现均失败”。Public memorizer 必须单独报告，不能计入互不相同的 scientific
shortcut 数量。

## Required audit record

每篇 paper 在构建 task 前必须保存一份 audit record：

```text
Paper:
Research goal:
Main scientific contribution:
Contribution graph:

Candidate algorithms:
  - name:
    role: core | supporting | baseline | preprocessing | evaluation
    paper evidence:
    deletion test:

Selected core algorithm:
Why it is unique:
Scientific Contract:

Gate results:
  G1 ... G8: PASS | REVISE | REJECT
  evidence:

Blind identification runs:
  model/run:
  identified target:
  paper evidence:

Blind implementation run:
  model:
  complete harness prompt and hash:
  public bundle hash:
  runner version:
  generated submission and hash:
  isolation evidence:
  per-case results:

Implementation provenance:
  official oracle source / pin / hash:
  adapter patch and hash:
  independent scientific implementation hash:
  curator reference submission hash:
  blind agent submission hash:
  independence review:

Shortcut audit:
  distinct fault model:
  case-by-shortcut result matrix:
  hidden scores and maximum:
  public memorizer score:

Final decision: ACCEPT | REVISE | REJECT
Required changes:
Reviewer and date:
```

---

### 最终 public instruction 必须分层且一致

Task-specific `task.md` 仍然只能包含要求的交付文件名，例如：

> solution.py

下面这种完整句子属于所有任务共用的 **benchmark harness prompt**，不得复制进
`task.md`：

不要写：

> Implement Eq. 7 using the quantum finite-temperature spin algorithm.

而只写：

> Implement a general program that produces the required scientific outputs for the provided inputs according to the methodology described in the paper.

Harness 还负责统一说明 CLI、`submission.json`、输入输出路径和 runner contract。
每次 G6/G7 必须记录最终实际发送的完整 harness prompt 及其 hash，不能只记录模板
片段或 `task.md`。

然后给：

```json
{
  "spin": 0.5,
  "temperature": [...],
  "field_scale": 1.34
}
```

以及一个 public output。

**算法定位本身就是 benchmark 的一部分。**

这其实会形成一个很漂亮的能力链：

[
\text{Paper Understanding}
\rightarrow
\text{Algorithm Identification}
\rightarrow
\text{Scientific Implementation}
\rightarrow
\text{Generalization to Hidden Inputs}
]

而不是现在很多 benchmark 的：

[
\text{“Implement Algorithm X”}
\rightarrow
\text{Code}
]
