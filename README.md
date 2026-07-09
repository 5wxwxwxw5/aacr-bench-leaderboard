# AACR-Bench Open Leaderboard

面向 AACR-Bench（代码评审基准）的开源榜单。使用者在本地运行自己的 code review
系统，把结果按统一格式提 PR 上传；仓库通过 GitHub Action 复算指标，并在静态页面
上展示排名。

- 贡献者负责在本地产出评测结果（运行 reviewer、调用模型、clone 仓库等）。
- 榜单只做评论级匹配和算分，不 clone 被测仓库。

## 榜单指标

主指标为 F1（每条匹配需同时满足行号匹配和语义匹配）。展示以下指标：

| 指标 | 说明 | 分母 |
|------|------|------|
| F1 / Precision / Recall | 匹配质量（行号+语义，主指标） | 全部 196 个样本 |
| Avg Time | 平均单样本耗时 | 实际提交的样本数 S |
| Avg Tokens | 平均单样本 token | 实际提交的样本数 S |
| Coverage | 提交覆盖率 S/196 | — |

### 指标细节

benchmark 共 196 个样本。若只提交了 S 个（例如 190，缺 6 个）：

- F1 / Precision / Recall：分母按全部 196 计算。缺失样本的参考评论仍计入 Recall
  分母、matched 记 0，即算作未匹配。
- 平均耗时 / 平均 token：分母只按实际提交的 S 个样本计算。

匹配算法（`evaluation/judge.py`）：对每条参考评论按 `path → side → line(k) → semantic`
四阶段过滤，语义阶段由 LLM（或本地 Mock）判定两条评论是否表达同一关注点。一条评论
同时通过全部四个阶段才计为命中，F1 / Precision / Recall 基于命中数计算。

## 目录结构

```
open-leadboard/
├── benchmark/aacr_bench.jsonl        # 196 条参考数据集（reference_comments）
├── schema/submission.schema.json     # 提交格式的 JSON Schema
├── submissions/<id>/                 # 贡献者提交（meta.yaml + results/*.json）
├── evaluation/                       # 评测代码
│   ├── judge.py                      # 四阶段匹配 + LLM/Mock 语义判定
│   ├── grade.py                      # 复算指标（两套分母口径）
│   ├── validate.py                   # 格式 + 覆盖率校验
│   └── aggregate.py                  # 汇总 → leaderboard.json
├── leaderboard/
│   ├── data/<id>.json                # 每个提交的复算指标（Action 生成）
│   └── site/                         # 纯静态前端（GitHub Pages）
└── .github/workflows/                # validate / evaluate / publish
```

## 提交格式

文件名 = `<instance_id>.json`（instance_id 取自 benchmark）。以 OpenCodeReview 输出为准：

```json
{
  "instance_id": "libsdl-org__SDL@96dfef3",
  "repo": "libsdl-org/SDL",
  "base_commit": "...",
  "head_commit": "...",
  "started_at": "2026-06-04T07:01:48Z",
  "duration_seconds": 21.55,
  "review": {
    "summary": { "total_tokens": 12197, "input_tokens": 11113, "output_tokens": 1084 },
    "comments": [
      { "path": "docs/build_docs.py", "content": "...", "start_line": 453, "end_line": 459, "side": "right" }
    ],
    "stderr": ""
  }
}
```

必须字段：顶层 `instance_id` `repo` `base_commit` `head_commit` `started_at`
`duration_seconds` `review`；`review.summary` 的 `total_tokens` `input_tokens`
`output_tokens`；`review.comments`（完整保留，每条含 `path` `content` `start_line`
`end_line` `side`，其中 `side` 取 `"left"` 或 `"right"`）；`review.stderr`。

## 如何提交（贡献者）

1. Fork 本仓库。
2. 在本地跑你的 reviewer，为 benchmark 中的样本产出上面格式的结果文件。
3. 放入 `submissions/<你的-id>/`：
   ```
   submissions/<你的-id>/
   ├── meta.yaml
   └── results/<instance_id>.json
   ```
4. 提 PR。CI 自动跑格式校验并回帖结果。
5. Maintainer 审核后打 `ready-to-eval` 标签 → 触发复算 → 分数回帖 PR。
6. 合并后榜单自动更新。

`meta.yaml` 模板见 [`submissions/README.md`](submissions/README.md)。

## 本地运行（复算 / 调试）

```bash
pip install -r evaluation/requirements.txt

# 1) 格式校验
python evaluation/validate.py submissions/example-ocr

# 2) 复算指标（无 API key 时自动走 Mock 语义匹配）
JUDGE_USE_MOCK=true python evaluation/grade.py \
  --submission submissions/example-ocr \
  --benchmark benchmark/aacr_bench.jsonl \
  --out leaderboard/data/example-ocr.json

# 用真实裁判模型：设置环境变量 JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL

# 3) 汇总榜单数据
python evaluation/aggregate.py

# 4) 本地预览前端
cd leaderboard/site && python -m http.server 8000   # 打开 http://localhost:8000
```

## 在线验证（GitHub）

除本地运行外，你可以直接在 GitHub 上验证提交。分两种角色：

### A. 贡献者：提 PR 触发在线校验

1. 在 GitHub 上 Fork 本仓库到你的账号。
2. 在 Fork 中新建分支，添加 `submissions/<你的-id>/`（`meta.yaml` + `results/*.json`）。
   也可以直接在 GitHub 网页端 Add file → Create new file 逐个上传，无需本地依赖。
3. 向本仓库发起 Pull Request。
4. `validate.yml` 会自动运行（不需要密钥），在 PR 下回帖格式校验报告
   （Schema 是否通过、instance_id 是否合法、覆盖率 S/196）。若报错，修正后 push 会重跑。
5. 校验通过后，等待 maintainer 打 `ready-to-eval` 标签触发复算。`evaluate.yml` 会用
   仓库配置的裁判模型复算，并把 F1 / Precision / Recall / Avg Time / Avg Tokens 回帖到 PR。
6. 合并后 `publish.yml` 会更新在线榜单。

> 可以在 PR 页面的 Checks / Actions 标签查看每一步日志。

### B. 维护者 / 自己的仓库：手动触发在线复算

想在自己的仓库里、不经过 PR 直接跑一次在线复算与发布：

1. 配置密钥：仓库 `Settings → Environments → New environment` 建 `evaluation`，
   添加 secrets `JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL`（可加 Required reviewers 审批）。
2. 触发复算：给已提交的 PR 打上 `ready-to-eval` 标签即可触发 `evaluate.yml`。
   首次可用仓库自带的 `submissions/example-ocr` 拉一个测试 PR 验证链路。
3. 发布榜单：把 `leaderboard/data/<id>.json` 合并到 `main`，或在
   Actions → Publish Leaderboard → Run workflow 手动触发，即部署到 GitHub Pages。
4. 开启 Pages：`Settings → Pages → Source: GitHub Actions`，部署完成后在该页拿到榜单 URL。

> `evaluate.yml` 用 `pull_request_target` 以便访问仓库 secrets。fork 的 PR 默认拿不到
> 密钥，需要 maintainer 打标签才会触发。

## 维护者配置

- 在 GitHub 仓库创建名为 `evaluation` 的 Environment，配置 secrets：
  `JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL`，并设置审批者，仅允许可信
  maintainer 打 `ready-to-eval` 标签触发复算（`evaluate.yml` 用 `pull_request_target`）。
- 开启 GitHub Pages（Source: GitHub Actions），`publish.yml` 会在 main 更新时部署。

## 工作流

| Workflow | 触发 | 作用 | 密钥 |
|----------|------|------|------|
| `validate.yml` | 每个 PR | JSON Schema + instance_id + 覆盖率校验，回帖 PR | 无 |
| `evaluate.yml` | 打 `ready-to-eval` 标签 | clone-free 复算 → 写 `leaderboard/data/<id>.json` → 回帖 | JUDGE_* |
| `publish.yml` | push main | 汇总 + 部署 GitHub Pages | 无 |

## 致谢

数据集与评测方法来自 [AACR-Bench](https://github.com/alibaba/aacr-bench)。
