"""汇总阶段：扫描 leaderboard/data/*.json，产出排序后的 leaderboard.json。

按 semantic_f1 降序排名，写入 leaderboard/site/leaderboard.json 供前端消费。

用法：
  python aggregate.py [--data-dir leaderboard/data] [--out leaderboard/site/leaderboard.json]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_entries(data_dir: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        summary = data.get("summary", {})
        meta = data.get("meta", {})
        entries.append(
            {
                "submission_id": data.get("submission_id", path.stem),
                "submission_name": meta.get("submission_name", path.stem),
                "reviewer": meta.get("reviewer", ""),
                "model": meta.get("model", ""),
                "org": meta.get("org", ""),
                "url": meta.get("url", ""),
                "date": meta.get("date", ""),
                "semantic_f1": summary.get("semantic_f1", 0.0),
                "semantic_precision": summary.get("semantic_precision", 0.0),
                "semantic_recall": summary.get("semantic_recall", 0.0),
                "line_f1": summary.get("line_f1", 0.0),
                "line_precision": summary.get("line_precision", 0.0),
                "line_recall": summary.get("line_recall", 0.0),
                "submitted_instances": summary.get("submitted_instances", 0),
                "total_instances": summary.get("total_instances", 0),
                "missing_instances": summary.get("missing_instances", 0),
                "avg_duration_seconds": summary.get("avg_duration_seconds", 0.0),
                "avg_tokens": summary.get("avg_tokens", 0),
                "avg_input_tokens": summary.get("avg_input_tokens", 0),
                "avg_output_tokens": summary.get("avg_output_tokens", 0),
                "judge_mode": data.get("judge", {}).get("mode", ""),
            }
        )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="AACR-Bench 榜单汇总")
    parser.add_argument("--data-dir", default=str(REPO_ROOT / "leaderboard" / "data"))
    parser.add_argument("--out", default=str(REPO_ROOT / "leaderboard" / "site" / "leaderboard.json"))
    args = parser.parse_args()

    entries = load_entries(Path(args.data_dir))
    entries.sort(key=lambda e: e["semantic_f1"], reverse=True)
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank

    payload = {
        "benchmark": "AACR-Bench",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "entries": entries,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"已汇总 {len(entries)} 条提交 -> {out_path}")


if __name__ == "__main__":
    main()
