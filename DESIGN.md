# Open-Leaderboard 设计方案（AACR-Bench 开源榜单）

## 1. 背景与目标

基于 GitHub 建设 AACR-Bench 的开源 leaderboard。核心流程：

1. 贡献者在**本地**运行自己的 code review 系统（ocr / claude / codex / 自研），产出统一格式的评测结果 JSON。
2. 通过**提 PR** 的方式将结果上传到本仓库。
3. 仓库侧用 **GitHub Action** 统一复算指标（同一把尺子，防止自报分数造假）。
4. 以**纯静态前端**（GitHub Pages）展示榜单。

### 关键设计原则

- **评测过程不 clone 任何被测仓库**。评测只做一件事：读取「参考评审意见」（benchmark 数据集里的 `reference_comments`）与「生成的评审意见」（提交的 `review.comments`），执行 `path → side → line(k) → semantic` 四阶段匹配。clone 只发生在 reviewer 运行阶段，由贡献者本地承担，本榜单不涉及。
- **评测/算分放仓库侧**（用仓库统一的 judge 模型和 secrets），**reviewer 运行放贡献者本地**（重、需各种 CLI/API），以此保证公平并降低贡献门槛。

---

## 2. 统一数据契约（提交格式）

每个 instance 一个文件，文件名 = `{instance_id}.json`。以 OpenCodeReview 输出结构为准。**必须保留的字段**：

```json
{
  "instance_id": "libsdl-org__SDL@96dfef3",
  "repo": "libsdl-org/SDL",
  "base_commit": "ab34ea5...",
  "head_commit": "96dfef3...",
  "started_at": "2026-06-04T07:01:48Z",
  "duration_seconds": 21.55,
  "review": {
    "summary": {
      "total_tokens": 12197,
      "input_tokens": 11113,
      "output_tokens": 1084
    },
    "comments": [
      { "path": "docs/build_docs.py", "content": "...", "start_line": 453, "end_line": 459 }
    ],
    "stderr": ""
  }
}
```

字段要求：
- 顶层必须：`instance_id` `repo` `base_commit` `head_commit` `started_at` `duration_seconds` `review`
- `review.summary` 必须：`total_tokens` `input_tokens` `output_tokens`
- `review.comments` 完全保留；每条含 `path` `content` `start_line` `end_line`
- `review.stderr` 保留

用 **JSON Schema**（`schema/submission.schema.json`）硬校验。judge 侧 `side` 硬编码为 `right`（reviewer 均评 diff 新增侧）。

---

## 3. 指标口径（核心）

benchmark 共 **196** 个样本。设贡献者实际提交 `S` 个（如 190），缺失 `M = 196 − S`（如 6）。**要求全部 196 个样本参与**，但两类指标分母规则不同。

### A 组：F1 / Precision / Recall —— 分母按全部 196 计算，缺失样本视为匹配失败

遍历 benchmark **全部 196** 个 instance：

- **已提交的样本**：正常做四阶段匹配，累加 `matched_semantic_notes`、`matched_line_notes`、`expected_notes`（该样本参考评论数）、`generated_notes`（该样本生成评论数）。
- **缺失的样本**：`expected_notes` 仍累加其参考评论数（进入 Recall 分母），`matched_* += 0`，`generated_notes += 0`。即缺失样本的参考评论全部算作「未召回 / 未匹配」。

公式（沿用 `judge.py` / `evaluate.py`）：

| 指标 | 公式 | 分母含义 |
|------|------|----------|
| **Precision** | `matched_semantic / generated_notes` | 全部已提交样本的生成评论总数 |
| **Recall** | `matched_semantic / expected_notes` | **196 个样本全部参考评论之和**（缺失样本照计入） |
| **F1** | `2·P·R / (P + R)` | — |

同时输出 line 维度的 `line_precision / line_recall / line_f1`（定位能力参考）。

> 效果：少交样本会拉低 Recall 与 F1，无法通过「只交容易的样本」刷高分。

### B 组：平均时间 / 平均 token —— 分母按实际提交的 S 个计算

只对**已提交**的 S 个样本累加：

- `total_duration_seconds += duration_seconds`
- `total_input_tokens += review.summary.input_tokens`
- `total_output_tokens += review.summary.output_tokens`

平均值：

- **avg_duration_seconds** = `total_duration_seconds / S`
- **avg_input_tokens / avg_output_tokens / avg_tokens** = 对应 total `/ S`

> 效果：耗时 / token 只反映「实际跑过的样本」的平均成本，不被缺失样本稀释。

### 与参考实现的差异

参考 `evaluate.py` 遇到缺文件直接 `continue` 跳过、不计入任何分母。本榜单必须区分**两套计数器**：缺失样本计入 A 组的 Recall / F1 分母（记 `expected`、`matched=0`），而 B 组平均值只除以实际提交数 S。

---

## 4. 仓库结构

```
open-leadboard/
├── README.md                         # 项目介绍 + 提交指南 + 榜单链接
├── DESIGN.md                         # 本设计方案
├── benchmark/
│   └── aacr_bench.jsonl              # 196 条参考数据集（只读基准）
├── schema/
│   └── submission.schema.json        # JSON Schema 提交格式校验
├── submissions/
│   ├── README.md                     # 目录说明 + meta.yaml 模板
│   └── example-ocr/                  # 示例提交（跑通流水线）
│       ├── meta.yaml                 # 模型元信息
│       └── results/<instance_id>.json
├── evaluation/                       # 复算代码（移植自 eval_all，去掉 clone/pipeline）
│   ├── judge.py                      # 四阶段匹配 + LLM/Mock 语义判定（内联 JUDGE_* 变量名）
│   ├── grade.py                      # 精简 evaluate：仅 OCR 统一格式 + 新分母口径
│   ├── validate.py                   # Schema + instance_id 覆盖率 + meta.yaml 校验 → markdown
│   ├── aggregate.py                  # 汇总 leaderboard/data/*.json → leaderboard.json
│   └── requirements.txt              # openai, jsonschema, pyyaml, python-dotenv, tqdm
├── leaderboard/
│   ├── data/<submission_id>.json     # 每个 submission 复算后的指标（Action 生成）
│   └── site/
│       ├── index.html                # 榜单主表（可点列排序）
│       ├── app.js                    # fetch leaderboard.json 渲染 + 排序 + 详情
│       ├── style.css
│       └── leaderboard.json          # aggregate 产出，前端数据源
└── .github/
    ├── PULL_REQUEST_TEMPLATE.md
    └── workflows/
        ├── validate.yml              # pull_request：格式校验（无 secrets）
        ├── evaluate.yml              # label 触发：复算 + 回帖 PR
        └── publish.yml               # push main：aggregate + 部署 Pages
```

`meta.yaml` 示例：

```yaml
submission_name: "GPT-5 + OpenCodeReview"
reviewer: ocr            # ocr | claude | codex | custom
model: gpt-5
org: "Acme AI"
url: https://...         # 论文 / 项目链接
contact: "@github_user"
```

---

## 5. 评测流水线（三段式 GitHub Action）

```
贡献者 fork → 放 submissions/<id>/ → 提 PR
  │
  ① validate.yml  (pull_request, 无 secrets)
  │     Schema 校验 + instance_id 覆盖率 + meta.yaml 必填 → 结果贴 PR 评论
  ▼
  ② evaluate.yml  (maintainer 打 ready-to-eval label 触发; pull_request_target)
  │     pip install → python evaluation/grade.py（用 secrets.JUDGE_*）
  │     → 产出 leaderboard/data/<id>.json → summary 表回帖 PR
  │     → GitHub Environment 保护 secrets，仅 maintainer 打 label 可触发
  ▼
  Maintainer 审核合并 main
  ▼
  ③ publish.yml   (push main, paths leaderboard/data/**)
        python evaluation/aggregate.py → 部署 leaderboard/site 到 GitHub Pages
```

**安全关键点**：fork 的 PR 默认拿不到 secrets（`JUDGE_API_KEY`）。因此格式校验（①）对所有 PR 自动跑；真正需密钥的评测（②）由 maintainer 审核代码无害后打 label 触发，用 `pull_request_target` + GitHub Environment 保护，避免恶意 PR 盗用密钥或刷分。**评测阶段不 clone 被测仓库**，只读 benchmark jsonl + 提交 JSON 做语义匹配。

---

## 6. 关键实现细节

### evaluation/judge.py
从参考 `judge.py` 直接拷贝。唯一改动：去掉 `import config`，把 `JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL / JUDGE_USE_MOCK` 内联为常量。保留 `USE_MOCK_LLM`、四阶段匹配 `evaluate_comments`、`diff_location_is_same`、`compute_cr_statistics`、Mock/LLM 双模式。

### evaluation/grade.py（改写自 evaluate.py）
- CLI：`grade.py --submission submissions/<id> --benchmark benchmark/aacr_bench.jsonl --out leaderboard/data/<id>.json [--line-k 1]`
- 读 `meta.yaml` 取 reviewer / model 等元信息写入产出。
- 保留 `build_reference_comments`（读 benchmark：text/path/start_line/end_line/side）与 `build_target_comments_from_ocr`（读 review.comments：content/path/start_line/end_line，side=right）。
- **两套计数器**（见 §3）：A 组遍历全部 196，缺文件样本记 expected、matched=0、generated=0 并记入 `missing_instance_ids`；B 组只对已提交样本累加 duration/token，平均除以 S。
- 产出 `leaderboard/data/<id>.json`：

```json
{
  "submission_id": "example-ocr",
  "meta": { "submission_name": "...", "reviewer": "ocr", "model": "...", "org": "...", "url": "...", "date": "..." },
  "summary": {
    "total_instances": 196, "submitted_instances": 190, "missing_instances": 6,
    "expected_notes": 0, "generated_notes": 0,
    "matched_semantic_notes": 0, "matched_line_notes": 0,
    "semantic_precision": 0.0, "semantic_recall": 0.0, "semantic_f1": 0.0,
    "line_precision": 0.0, "line_recall": 0.0, "line_f1": 0.0,
    "avg_duration_seconds": 0.0, "avg_input_tokens": 0, "avg_output_tokens": 0, "avg_tokens": 0
  },
  "missing_instance_ids": ["..."],
  "judge": { "mode": "llm", "model": "...", "line_k": 1 }
}
```

### evaluation/validate.py
用 jsonschema 逐个校验 `submissions/<id>/results/*.json`；校验 instance_id 属于 benchmark；统计覆盖率（提交 / 196）；读 meta.yaml 必填字段。输出 markdown 报告到 stdout（供 Action 回帖）。覆盖不足**不阻断**（允许缺失），但报告中提示缺失清单与对 Recall 的影响。

### evaluation/aggregate.py
扫描 `leaderboard/data/*.json` → 按 `semantic_f1` 降序排名，写 `leaderboard/site/leaderboard.json`。

### leaderboard/site（纯 vanilla HTML + JS）
主表列：`Rank / Model / Sem-F1 / Precision / Recall / Coverage(S/196) / Avg Time / Avg Tokens / Date`，表头可点击排序（默认 Sem-F1 降序）。点击行展开 meta 与逐 instance 匹配明细。GitHub Pages 托管，零构建零运维。

---

## 7. 主指标与防作弊

- **主指标**：`semantic_f1`（语义匹配 F1），默认排序键。
- 同时展示 semantic precision/recall、avg time、avg tokens、coverage。
- 结果由仓库侧复算，贡献者自报分数无效。
- 固定 benchmark 版本 + 固定 judge 模型 / 参数（记录在 data JSON 的 `judge` 字段）。
- 缺失样本计入 F1/Recall 分母，杜绝「只交容易样本」刷分。

---

## 8. 验证方式（端到端）

1. 本地：准备 `example-ocr` 提交（含部分样本，故意缺几个）→ `JUDGE_USE_MOCK=true python evaluation/grade.py ...` → 确认 data JSON 中 Recall 分母 = 196、avg_* 分母 = 已提交数。
2. `python evaluation/aggregate.py` → 生成 leaderboard.json；本地起 `python -m http.server` 打开 `index.html` 确认渲染与排序。
3. `python evaluation/validate.py submissions/example-ocr` → 确认 markdown 校验报告正确。
4. CI：先用 example 提交验证 validate.yml；evaluate.yml 需仓库配好 JUDGE_* secrets 后由 maintainer 打 label 验证。

---

## 9. 范围说明（不做）

- 不实现 / 不运行 reviewer（ocr/claude/codex 在贡献者本地跑），**评测阶段不 clone 仓库**。
- 不做后端服务 / 数据库，纯静态前端。
- 不改动 aacr-bench / Evaluation 原仓库。
