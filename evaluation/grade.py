"""复算阶段：读取 benchmark 参考评论 + 提交的评审结果，计算榜单指标。

不 clone 任何被测仓库，只做评论级的四阶段匹配（path -> side -> line(k) -> semantic）。

指标分母口径（关键）：
- F1 / Precision / Recall：分母按 benchmark 全部样本计算。未提交的样本视为匹配失败
  （其参考评论仍计入 Recall 分母，matched=0，generated=0）。
- 平均时间 / 平均 token：分母只按实际提交的样本数 S 计算。

用法：
  python grade.py --submission submissions/<id> \
      --benchmark benchmark/aacr_bench.jsonl \
      --out leaderboard/data/<id>.json [--line-k 1]

裁判模式由环境变量控制（见 judge.py）：JUDGE_USE_MOCK / JUDGE_API_KEY /
JUDGE_BASE_URL / JUDGE_MODEL。仓库根目录若存在 .env 会被自动加载。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap_env() -> None:
    """在 import judge 之前加载 .env，使 JUDGE_* 变量就位。

    judge 的 USE_MOCK_LLM 在导入时即根据环境变量固化，故必须在其之前加载。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            return


_bootstrap_env()

import judge  # noqa: E402
from judge import compute_cr_statistics, evaluate_comments  # noqa: E402

try:
    import yaml  # noqa: E402
except ImportError:  # pragma: no cover
    yaml = None


# ---------- 数据加载 ----------

def load_benchmark(path: Path) -> List[Dict[str, Any]]:
    """读取 benchmark jsonl，返回 instance 列表。"""
    instances: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"benchmark 第 {line_no} 行解析失败: {error}") from error
            instances.append(data)
    return instances


def load_meta(submission_dir: Path) -> Dict[str, Any]:
    """读取 submission 的 meta.yaml（缺失则返回空 dict）。"""
    meta_path = submission_dir / "meta.yaml"
    if not meta_path.is_file() or yaml is None:
        return {}
    with meta_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def result_file(submission_dir: Path, instance_id: str) -> Path:
    """提交结果文件路径：results/<instance_id>.json。"""
    return submission_dir / "results" / f"{instance_id}.json"


# ---------- 评论格式转换 ----------

def _normalize_line_range(
    from_line: Optional[int], to_line: Optional[int]
) -> Dict[str, Optional[int]]:
    if from_line is None and to_line is None:
        return {"from_line": None, "to_line": None}
    if from_line is None:
        from_line = to_line
    if to_line is None:
        to_line = from_line
    if from_line > to_line:
        from_line, to_line = to_line, from_line
    return {"from_line": from_line, "to_line": to_line}


def build_reference_comments(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """benchmark reference_comments -> judge 比对格式。"""
    comments: List[Dict[str, Any]] = []
    for ref in instance.get("reference_comments", []) or []:
        if not isinstance(ref, dict):
            continue
        line_range = _normalize_line_range(ref.get("start_line"), ref.get("end_line"))
        comments.append(
            {
                "note": ref.get("text", ""),
                "path": ref.get("path", ""),
                "side": ref.get("side"),
                "from_line": line_range["from_line"],
                "to_line": line_range["to_line"],
                "line_match": False,
                "semantic_match": False,
                "matched_note": "",
            }
        )
    return comments


def build_target_comments(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """提交结果 review.comments -> 待评测评论；side 直接读取用户提交值。"""
    review = result.get("review")
    if not isinstance(review, dict):
        return []
    comments: List[Dict[str, Any]] = []
    for finding in review.get("comments", []) or []:
        if not isinstance(finding, dict):
            continue
        note = (finding.get("content") or "").strip()
        if not note:
            continue
        line_range = _normalize_line_range(finding.get("start_line"), finding.get("end_line"))
        comments.append(
            {
                "note": note,
                "path": finding.get("path", ""),
                "side": finding.get("side"),
                "from_line": line_range["from_line"],
                "to_line": line_range["to_line"],
            }
        )
    return comments


def load_submission_result(submission_dir: Path, instance_id: str) -> Optional[Dict[str, Any]]:
    """读取某 instance 的提交结果；缺失或解析失败返回 None。"""
    path = result_file(submission_dir, instance_id)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as error:
        logging.warning("跳过无法解析的结果文件 %s: %s", path.name, error)
        return None
    if not isinstance(data, dict):
        logging.warning("结果文件顶层非对象，跳过: %s", path.name)
        return None
    return data


def _extract_usage(result: Dict[str, Any]) -> Dict[str, Any]:
    """从提交结果提取耗时与 token。"""
    review = result.get("review") or {}
    summary = review.get("summary") or {}
    return {
        "duration_seconds": result.get("duration_seconds", 0) or 0,
        "input_tokens": summary.get("input_tokens", 0) or 0,
        "output_tokens": summary.get("output_tokens", 0) or 0,
    }


# ---------- 指标计算 ----------

def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    if (precision + recall) <= 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


async def grade(
    submission_dir: Path,
    benchmark_path: Path,
    line_k: int = 1,
) -> Dict[str, Any]:
    instances = load_benchmark(benchmark_path)
    meta = load_meta(submission_dir)

    # A 组计数器：F1 / P / R，分母覆盖全部 benchmark
    expected_notes = 0
    generated_notes = 0
    matched_semantic = 0

    # B 组计数器：平均时间 / token，分母只按实际提交数 S
    submitted = 0
    total_duration = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    missing_ids: List[str] = []
    eval_details: List[Dict[str, Any]] = []

    for instance in instances:
        instance_id = instance["instance_id"]
        reference = build_reference_comments(instance)
        expected_here = len([c for c in reference if c.get("note")])

        result = load_submission_result(submission_dir, instance_id)

        if result is None:
            # 缺失样本：参考评论计入 Recall 分母，matched=0，不贡献 generated
            missing_ids.append(instance_id)
            expected_notes += expected_here
            eval_details.append(
                {
                    "instance_id": instance_id,
                    "repo": instance.get("repo", ""),
                    "status": "missing",
                    "expected_notes": expected_here,
                    "generated_notes": 0,
                    "semantic_match_count": 0,
                }
            )
            continue

        # 已提交样本
        submitted += 1
        generated = build_target_comments(result)
        generated_count = len([c for c in generated if c.get("note")])

        if reference:
            await evaluate_comments(reference, generated, k=line_k)
        cr = compute_cr_statistics(reference, generated_count)

        expected_notes += cr["expected_notes"]
        generated_notes += generated_count
        matched_semantic += cr["semantic_match_count"]

        usage = _extract_usage(result)
        total_duration += usage["duration_seconds"]
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]

        eval_details.append(
            {
                "instance_id": instance_id,
                "repo": instance.get("repo", ""),
                "status": "evaluated",
                "expected_notes": cr["expected_notes"],
                "generated_notes": generated_count,
                "semantic_match_count": cr["semantic_match_count"],
            }
        )

    # A 组指标（分母：全部 benchmark）
    sem_p = _rate(matched_semantic, generated_notes)
    sem_r = _rate(matched_semantic, expected_notes)

    # B 组指标（分母：实际提交数 S）
    avg_duration = round(total_duration / submitted, 2) if submitted else 0.0
    avg_input = round(total_input_tokens / submitted) if submitted else 0
    avg_output = round(total_output_tokens / submitted) if submitted else 0
    avg_total = round((total_input_tokens + total_output_tokens) / submitted) if submitted else 0

    summary = {
        "total_instances": len(instances),
        "submitted_instances": submitted,
        "missing_instances": len(missing_ids),
        "expected_notes": expected_notes,
        "generated_notes": generated_notes,
        "matched_notes": matched_semantic,
        "precision": sem_p,
        "recall": sem_r,
        "f1": _f1(sem_p, sem_r),
        "total_duration_seconds": round(total_duration, 2),
        "avg_duration_seconds": avg_duration,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "avg_input_tokens": avg_input,
        "avg_output_tokens": avg_output,
        "avg_tokens": avg_total,
    }

    submission_id = meta.get("submission_id") or submission_dir.name
    return {
        "submission_id": submission_id,
        "meta": {
            "submission_name": meta.get("submission_name", submission_id),
            "reviewer": meta.get("reviewer", ""),
            "model": meta.get("model", ""),
            "org": meta.get("org", ""),
            "url": meta.get("url", ""),
            "contact": meta.get("contact", ""),
            "date": meta.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        },
        "summary": summary,
        "missing_instance_ids": missing_ids,
        "judge": {
            "mode": "mock" if judge.USE_MOCK_LLM else "llm",
            "model": os.getenv(judge.JUDGE_MODEL_VAR, "") if not judge.USE_MOCK_LLM else "",
            "line_k": line_k,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eval_details": eval_details,
    }


def print_summary(result: Dict[str, Any]) -> None:
    s = result["summary"]
    print("\n" + "=" * 56)
    print(f"复算汇总: {result['submission_id']}  (judge={result['judge']['mode']})")
    print("=" * 56)
    print(f"benchmark 样本:   {s['total_instances']}")
    print(f"已提交样本 (S):   {s['submitted_instances']}")
    print(f"缺失样本:         {s['missing_instances']}")
    print("-" * 56)
    print(f"F1:               {s['f1']}")
    print(f"Precision:        {s['precision']}")
    print(f"Recall:           {s['recall']}")
    print("-" * 56)
    print(f"平均耗时 (/S):    {s['avg_duration_seconds']}s")
    print(f"平均 token (/S):  {s['avg_tokens']:,}")
    print("=" * 56)


def main() -> None:
    parser = argparse.ArgumentParser(description="AACR-Bench 榜单复算")
    parser.add_argument("--submission", required=True, help="submission 目录，如 submissions/example-ocr")
    parser.add_argument("--benchmark", required=True, help="benchmark jsonl 路径")
    parser.add_argument("--out", required=True, help="输出指标 JSON 路径")
    parser.add_argument("--line-k", type=int, default=1, help="行号匹配容差 k（默认 1）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    submission_dir = Path(args.submission)
    benchmark_path = Path(args.benchmark)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(grade(submission_dir, benchmark_path, line_k=args.line_k))
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    print_summary(result)
    print(f"\n指标已保存到: {out_path}")


if __name__ == "__main__":
    main()
