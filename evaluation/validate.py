"""校验阶段：检查提交的格式与 instance_id 合法性，输出 markdown 报告。

校验项：
- meta.yaml 存在且含必填字段（submission_name / reviewer / model）
- results/*.json 均通过 JSON Schema
- 每个结果文件的 instance_id 属于 benchmark 且与文件名一致
- 覆盖率统计（提交 / benchmark 总数）；覆盖不足不阻断，仅提示

用法：
  python validate.py submissions/<id> [--benchmark benchmark/aacr_bench.jsonl] \
      [--schema schema/submission.schema.json]

报告写入 stdout（供 GitHub Action 回帖）。存在硬错误时以退出码 1 结束。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover
    Draft7Validator = None

REPO_ROOT = Path(__file__).resolve().parent.parent
META_REQUIRED = ["submission_name", "reviewer", "model"]


def load_benchmark_ids(path: Path) -> Set[str]:
    ids: Set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            ids.add(json.loads(line)["instance_id"])
    return ids


def validate_submission(
    submission_dir: Path, benchmark_ids: Set[str], schema: Dict[str, Any]
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    # meta.yaml
    meta_path = submission_dir / "meta.yaml"
    if not meta_path.is_file():
        errors.append("缺少 meta.yaml")
    elif yaml is not None:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        for key in META_REQUIRED:
            if not meta.get(key):
                errors.append(f"meta.yaml 缺少必填字段: {key}")

    # results 目录
    results_dir = submission_dir / "results"
    if not results_dir.is_dir():
        errors.append("缺少 results/ 目录")
        return {"errors": errors, "warnings": warnings, "submitted": 0, "missing": len(benchmark_ids)}

    validator = Draft7Validator(schema) if Draft7Validator else None
    submitted_ids: Set[str] = set()

    for result_path in sorted(results_dir.glob("*.json")):
        stem = result_path.stem
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{result_path.name}: JSON 解析失败 - {error}")
            continue

        if validator is not None:
            for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
                loc = "/".join(str(p) for p in err.path) or "(root)"
                errors.append(f"{result_path.name}: schema 校验失败 @ {loc} - {err.message}")

        inst_id = data.get("instance_id") if isinstance(data, dict) else None
        if inst_id:
            if inst_id != stem:
                errors.append(f"{result_path.name}: 文件名与 instance_id 不一致（{inst_id}）")
            if inst_id not in benchmark_ids:
                errors.append(f"{result_path.name}: instance_id 不在 benchmark 中（{inst_id}）")
            else:
                submitted_ids.add(inst_id)

    missing = benchmark_ids - submitted_ids
    if missing:
        warnings.append(
            f"覆盖不足：已提交 {len(submitted_ids)}/{len(benchmark_ids)}，"
            f"缺失 {len(missing)} 个样本将按匹配失败计入 Recall/F1 分母。"
        )

    return {
        "errors": errors,
        "warnings": warnings,
        "submitted": len(submitted_ids),
        "missing": len(missing),
        "total": len(benchmark_ids),
        "missing_ids": sorted(missing),
    }


def render_report(submission_dir: Path, result: Dict[str, Any]) -> str:
    ok = not result["errors"]
    lines = [f"## 校验报告: `{submission_dir.name}`", ""]
    lines.append(f"- 状态: {'✅ 通过' if ok else '❌ 未通过'}")
    lines.append(f"- 覆盖率: {result['submitted']}/{result.get('total', '?')}（缺失 {result['missing']}）")
    lines.append("")

    if result["errors"]:
        lines.append("### ❌ 错误（需修复）")
        for err in result["errors"][:50]:
            lines.append(f"- {err}")
        if len(result["errors"]) > 50:
            lines.append(f"- ...（另有 {len(result['errors']) - 50} 条）")
        lines.append("")

    if result["warnings"]:
        lines.append("### ⚠️ 提示")
        for warn in result["warnings"]:
            lines.append(f"- {warn}")
        lines.append("")

    if ok:
        lines.append("格式校验通过。等待 maintainer 打 `ready-to-eval` 标签触发评测。")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="AACR-Bench 提交校验")
    parser.add_argument("submission", help="submission 目录")
    parser.add_argument("--benchmark", default=str(REPO_ROOT / "benchmark" / "aacr_bench.jsonl"))
    parser.add_argument("--schema", default=str(REPO_ROOT / "schema" / "submission.schema.json"))
    args = parser.parse_args()

    submission_dir = Path(args.submission)
    benchmark_ids = load_benchmark_ids(Path(args.benchmark))
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))

    result = validate_submission(submission_dir, benchmark_ids, schema)
    print(render_report(submission_dir, result))

    sys.exit(1 if result["errors"] else 0)


if __name__ == "__main__":
    main()
