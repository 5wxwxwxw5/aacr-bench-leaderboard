# Open-Leaderboard 设计方案（AACR-Bench 开源榜单）

## 1. 背景与目标

基于 GitHub 搭建 AACR-Bench 的开源 leaderboard。流程：

1. 贡献者在本地运行自己的 code review 系统（ocr / claude / codex / 自研），产出统一格式的评测结果 JSON。
2. 通过提 PR 的方式将结果上传到本仓库。
3. 仓库用 GitHub Action 复算指标。
4. 用静态页面（GitHub Pages）展示榜单。

### 说明

- 评测过程只读取参考评审意见（benchmark 里的 `reference_comments`）和提交的评审意见（`review.comments`），执行 `path → side → line(k) → semantic` 四阶段匹配。
- 评测/算分在仓库侧完成（用仓库配置的 judge 模型和 secrets），reviewer 运行在贡献者本地完成。

---

## 2. 统一数据契约（提交格式）

每个 instance 一个文件，文件名 = `{instance_id}.json`。以 OpenCodeReview 输出结构为准。必须保留的字段：

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
      { "path": "docs/build_docs.py", "content": "...", "start_line": 453, "end_line": 459, "side": "right" }
    ],
    "stderr": ""
  }
}
```

字段要求：
- 顶层必须：`instance_id` `repo` `base_commit` `head_commit` `started_at` `duration_seconds` `review`
- `review.summary` 必须：`total_tokens` `input_tokens` `output_tokens`
- `review.comments` 完全保留；每条含 `path` `content` `start_line` `end_line` `side`
  （`side` 取 `"left"` 或 `"right"`）
- `review.stderr` 保留

用 JSON Schema（`schema/submission.schema.json`）校验。`side` 直接读取用户提交值（`"left"`/`"right"`），不再硬编码。

---

## 3. 指标细节

benchmark 共 196 个样本。设贡献者实际提交 `S` 个（如 190），缺失 `M = 196 − S`（如 6）。两类指标的分母规则不同。

### A 组：F1 / Precision / Recall —— 分母按全部 196 计算，缺失样本算作未匹配

遍历 benchmark 全部 196 个 instance：

- 已提交的样本：正常做四阶段匹配，累加 `matched_notes`（同时通过行号+语义匹配的命中数）、`expected_notes`（该样本参考评论数）、`generated_notes`（该样本生成评论数）。
- 缺失的样本：`expected_notes` 仍累加其参考评论数（进入 Recall 分母），`matched_notes += 0`，`generated_notes += 0`。即缺失样本的参考评论算作未匹配。

公式：一条评论需同时通过 `path → side → line(k) → semantic` 全部四个阶段才计为命中（对应原代码的 `semantic_match`，其内部已包含行号匹配前置条件）。

| 指标 | 公式 | 分母含义 |
|------|------|----------|
| Precision | `matched_notes / generated_notes` | 全部已提交样本的生成评论总数 |
| Recall | `matched_notes / expected_notes` | 196 个样本全部参考评论之和（缺失样本照计入） |
| F1 | `2·P·R / (P + R)` | — |

### B 组：平均时间 / 平均 token —— 分母按实际提交的 S 个计算

只对已提交的 S 个样本累加：

- `total_duration_seconds += duration_seconds`
- `total_input_tokens += review.summary.input_tokens`
- `total_output_tokens += review.summary.output_tokens`

平均值：

- `avg_duration_seconds` = `total_duration_seconds / S`
- `avg_input_tokens` / `avg_output_tokens` / `avg_tokens` = 对应 total `/ S`

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
├── evaluation/                       # 评测代码
│   ├── judge.py                      # 四阶段匹配 + LLM 语义判定（内联 JUDGE_* 变量名）
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

说明：fork 的 PR 默认拿不到 secrets（`JUDGE_API_KEY`）。格式校验（①）对所有 PR 自动跑；需要密钥的评测（②）由 maintainer 打 label 触发，用 `pull_request_target` + GitHub Environment 管理 secrets。评测阶段只读 benchmark jsonl 和提交 JSON 做匹配。

---

## 6. 关键实现细节

### evaluation/judge.py
从参考 `judge.py` 移植。改动：去掉 `import config`，把 `JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL` 内联为常量，并在导入时校验三者均已配置（缺失即 `raise RuntimeError` 退出）。移除本地 Mock 近似匹配，只保留 LLM 裁判模型判定；四阶段匹配 `evaluate_comments`、`diff_location_is_same`、`compute_cr_statistics` 保持不变。

### evaluation/grade.py（改写自 evaluate.py）
- CLI：`grade.py --submission submissions/<id> --benchmark benchmark/aacr_bench.jsonl --out leaderboard/data/<id>.json [--line-k 1]`
- 读 `meta.yaml` 取 reviewer / model 等元信息写入产出。
- 保留 `build_reference_comments`（读 benchmark：text/path/start_line/end_line/side）与 `build_target_comments`（读 review.comments：content/path/start_line/end_line/side，side 直接读取用户提交值）。
- 两套计数器（见 §3）：A 组遍历全部 196，缺文件样本记 expected、matched=0、generated=0 并记入 `missing_instance_ids`；B 组只对已提交样本累加 duration/token，平均除以 S。
- 产出 `leaderboard/data/<id>.json`：

```json
{
  "submission_id": "example-ocr",
  "meta": { "submission_name": "...", "reviewer": "ocr", "model": "...", "org": "...", "url": "...", "date": "..." },
  "summary": {
    "total_instances": 196, "submitted_instances": 190, "missing_instances": 6,
    "expected_notes": 0, "generated_notes": 0, "matched_notes": 0,
    "precision": 0.0, "recall": 0.0, "f1": 0.0,
    "avg_duration_seconds": 0.0, "avg_input_tokens": 0, "avg_output_tokens": 0, "avg_tokens": 0
  },
  "missing_instance_ids": ["..."],
  "judge": { "mode": "llm", "model": "...", "line_k": 1 }
}
```

### evaluation/validate.py
用 jsonschema 逐个校验 `submissions/<id>/results/*.json`；校验 instance_id 属于 benchmark；统计覆盖率（提交 / 196）；读 meta.yaml 必填字段。输出 markdown 报告到 stdout（供 Action 回帖）。覆盖不足不阻断（允许缺失），但报告中提示缺失清单与对 Recall 的影响。

### evaluation/aggregate.py
扫描 `leaderboard/data/*.json` → 按 `f1` 降序排名，写 `leaderboard/site/leaderboard.json`。

### leaderboard/site（纯 vanilla HTML + JS）
主表列：`Rank / Model / F1 / Precision / Recall / Coverage(S/196) / Avg Time / Avg Tokens / Date`，表头可点击排序（默认 F1 降序）。点击行展开 meta 与逐 instance 匹配明细。GitHub Pages 托管。

---

## 7. 主指标

- 主指标：`f1`（行号+语义匹配 F1），默认排序键。
- 同时展示 precision/recall、avg time、avg tokens、coverage。
- 指标由仓库侧复算，不采用贡献者自报的分数。
- 固定 benchmark 版本和 judge 模型/参数（记录在 data JSON 的 `judge` 字段）。
- 缺失样本计入 F1/Recall 分母。

---

## 8. 验证方式（端到端）

1. 本地：准备 `example-ocr` 提交（含部分样本，故意缺几个）→ 配置 `JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL` 后 `python evaluation/grade.py ...` → 确认 data JSON 中 Recall 分母 = 196、avg_* 分母 = 已提交数。
2. `python evaluation/aggregate.py` → 生成 leaderboard.json；本地起 `python -m http.server` 打开 `index.html` 确认渲染与排序。
3. `python evaluation/validate.py submissions/example-ocr` → 确认 markdown 校验报告正确。
4. CI：先用 example 提交验证 validate.yml；evaluate.yml 需仓库配好 JUDGE_* secrets 后由 maintainer 打 label 验证。

---

## 9. 范围说明（不做）

- 不实现 / 不运行 reviewer（ocr/claude/codex 在贡献者本地跑），只开展评测。
- 不做后端服务 / 数据库，用静态前端。
- 不改动 aacr-bench / Evaluation 原仓库。
