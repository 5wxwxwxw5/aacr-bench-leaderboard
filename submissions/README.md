# Submissions

每个提交是本目录下的一个子目录 `submissions/<submission_id>/`，包含：

```
submissions/<submission_id>/
├── meta.yaml                     # 模型元信息（必填）
└── results/
    └── <instance_id>.json        # 每个 benchmark instance 一个结果文件
```

## meta.yaml 模板

```yaml
submission_name: "GPT-5 + OpenCodeReview"   # 展示名（必填）
reviewer: ocr                                # ocr | claude | codex | custom（必填）
model: gpt-5                                 # 底层模型（必填）
org: "Acme AI"                               # 团队/组织（可选）
url: "https://..."                           # 论文/项目链接（可选）
contact: "@github_user"                      # 联系人（可选）
date: "2026-07-09"                           # 提交日期（可选，缺省取复算日期）
```

## 结果文件格式

文件名必须为 `<instance_id>.json`，其中 `instance_id` 来自
`benchmark/aacr_bench.jsonl`。格式见根目录 `schema/submission.schema.json`。
必须字段：`instance_id` `repo` `base_commit` `head_commit` `started_at`
`duration_seconds` `review`；`review` 内必须含 `summary`（`total_tokens`
`input_tokens` `output_tokens`）、`comments`、`stderr`。`comments` 中每条评论必须含
`path` `content` `start_line` `end_line` `side`，其中 `side` 取 `"left"` 或 `"right"`
（评审对象在 diff 左侧旧代码填 `left`，右侧新代码填 `right`）。

## 覆盖率与指标

- benchmark 共 **196** 个样本。允许只提交部分样本，但：
  - **F1 / Precision / Recall** 分母按全部 196 计算，未提交样本视为匹配失败（拉低 Recall/F1）。
  - **平均耗时 / 平均 token** 分母只按实际提交的样本数计算。
- 因此建议尽量提交全部 196 个样本。

## 提交流程

1. Fork 本仓库，在 `submissions/<你的-id>/` 下放入 meta.yaml 与 results。
2. 提 PR。CI 会自动跑格式校验并在 PR 上回帖。
3. Maintainer 审核后打 `ready-to-eval` 标签触发复算，分数表会回帖到 PR。
4. 合并后榜单自动更新。
