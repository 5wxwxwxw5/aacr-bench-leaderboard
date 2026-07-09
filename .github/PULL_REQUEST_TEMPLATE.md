## 提交说明

- **Submission ID**: `submissions/<你的-id>`
- **Reviewer**: <!-- ocr | claude | codex | custom -->
- **Model**: <!-- 底层模型 -->

## 检查清单

- [ ] 已在 `submissions/<id>/meta.yaml` 填写 `submission_name` / `reviewer` / `model`
- [ ] 结果文件位于 `submissions/<id>/results/<instance_id>.json`，文件名与 instance_id 一致
- [ ] 结果符合 `schema/submission.schema.json`（含 review.summary 的三个 token 字段、comments、stderr）
- [ ] 已知悉：缺失样本会计入 Recall/F1 分母（视为匹配失败）
- [ ] 未提交任何密钥 / 大文件

## 覆盖率

<!-- 提交了多少 / 196 个样本 -->

---
CI 会自动跑格式校验。校验通过后，等待 maintainer 打 `ready-to-eval` 标签触发正式复算。
