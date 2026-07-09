"""评测核心：参考评论与生成评论的四阶段匹配 + 指标统计 + 语义判定。

本模块自包含，不依赖框架外的任何资源，也不 clone 任何被测仓库。
语义匹配调用裁判模型（LLM）判断两条评论是否表达同一关注点 / 建议。

环境变量（直接读取，无中间映射）：
  JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL —— 三者均为必填，缺失即报错退出。

匹配按 path -> side -> line(k) -> semantic 四个阶段进行，任一阶段不通过即跳过候选。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List

# 环境变量名（内联，不再依赖外部 config 模块）
JUDGE_BASE_URL_VAR = "JUDGE_BASE_URL"
JUDGE_API_KEY_VAR = "JUDGE_API_KEY"
JUDGE_MODEL_VAR = "JUDGE_MODEL"

# 裁判模型三项配置均为必填，缺失直接报错退出（不再回退到本地近似匹配）
_missing_env = [
    name
    for name in (JUDGE_BASE_URL_VAR, JUDGE_API_KEY_VAR, JUDGE_MODEL_VAR)
    if not os.getenv(name)
]
if _missing_env:
    raise RuntimeError(
        "缺少裁判模型环境变量: "
        + ", ".join(_missing_env)
        + "。请配置 JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL 后重试。"
    )

# 语义匹配请求计数
llm_request_count = 0

# LLM 客户端延迟初始化
_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        from openai import AsyncOpenAI

        _llm_client = AsyncOpenAI(
            base_url=os.getenv(JUDGE_BASE_URL_VAR),
            api_key=os.getenv(JUDGE_API_KEY_VAR),
        )
    return _llm_client


async def match_semantic(reference_note: str, generated_note: str) -> Dict[str, Any]:
    """判断两条评论是否表达相同的关注点或建议。"""
    global llm_request_count
    llm_request_count += 1

    prompt = (
        "-Role-\n"
        "You are an expert code reviewer assistant specialized in analyzing and "
        "comparing code review comments.\n\n"
        "-Task-\n"
        "Determine whether two given review comments express the same concern or "
        "suggestion. Ignore differences in wording, tone, or formatting—focus solely "
        "on semantic equivalence of the underlying issue. If the core intent and "
        'technical substance are identical, answer "yes"; otherwise, answer "no".\n\n'
        f"Review Comment 1:\n{reference_note}\n\n"
        f"Review Comment 2:\n{generated_note}\n\n"
        "-Task-\n"
        "Determine whether the two review comments given above express the same concern or "
        "suggestion. Ignore differences in wording, tone, or formatting—focus "
        "solely on semantic equivalence of the underlying issue. If the core intent and "
        'technical substance are identical, answer "yes"; otherwise, answer "no".\n\n'
        "Your answer:"
    )

    try:
        response = await _get_llm_client().chat.completions.create(
            model=os.getenv(JUDGE_MODEL_VAR, "multiline_judge_model"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=40000,
            top_p=0.95,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        result_text = response.choices[0].message.content.strip().lower()
        is_similar = (
            "yes" in result_text
            or "similar" in result_text
            or "same" in result_text
            or "identical" in result_text
            or "equivalent" in result_text
        ) and ("no" not in result_text.split("yes")[0] if "yes" in result_text else True)
        return {"is_similar": is_similar, "reason": result_text}
    except Exception as error:  # noqa: BLE001 - 单条判定失败不应中断整体评测
        logging.error("裁判模型调用失败: %s", error)
        return {"is_similar": False, "reason": f"评估过程出错: {error}"}


def diff_location_is_same(
    from_line1: int, from_line2: int, to_line1: int, to_line2: int, k: int = 1
) -> bool:
    """判断两个行号范围是否重叠，或最小距离在 k 范围内。"""
    has_overlap = not (from_line1 > to_line2 or from_line2 < to_line1)
    if has_overlap:
        min_distance = 0
    else:
        min_distance = min(abs(from_line1 - to_line2), abs(from_line2 - to_line1))
    return min_distance <= k


def _normalize_path(path: str) -> str:
    """归一化路径，统一分隔符为 /。"""
    if not path:
        return ""
    return path.replace("\\/", "/").replace("\\", "/")


def _strip_thinking_tags(text: str) -> str:
    """去除评论中的思考过程标签（如 <details>...</details>）。"""
    if not text:
        return ""
    cleaned = re.sub(r"<details>.*?</details>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def evaluate_comments(
    reference_comments: List[Dict[str, Any]],
    generated_comments: List[Dict[str, Any]],
    k: int = 1,
) -> List[Dict[str, Any]]:
    """对单个样本的参考评论逐条评测。

    遍历每条参考评论，在生成评论中按 path -> side -> line(k) -> semantic 依次过滤，
    原地写入参考评论的 line_match / semantic_match / matched_note 字段。

    去重：每条生成评论最多被行号匹配一次、语义匹配一次。
    """
    matched_gen_ids_by_line: set = set()
    matched_gen_ids_by_semantic: set = set()

    for ref_comment in reference_comments:
        if not isinstance(ref_comment, dict):
            continue
        ref_note = ref_comment.get("note", "")
        if not ref_note:
            continue
        ref_note_cleaned = _strip_thinking_tags(ref_note)
        if not ref_note_cleaned:
            continue

        ref_path = _normalize_path(ref_comment.get("path", ""))
        ref_side = ref_comment.get("side")
        ref_from_line = ref_comment.get("from_line")
        ref_to_line = ref_comment.get("to_line")

        line_matched = False
        semantic_matched = False
        matched_note_text = ""

        for gen_idx, gen_comment in enumerate(generated_comments):
            if not isinstance(gen_comment, dict):
                continue
            gen_note = gen_comment.get("note", "")
            if not gen_note:
                continue
            gen_note_cleaned = _strip_thinking_tags(gen_note)
            if not gen_note_cleaned:
                continue

            gen_path = _normalize_path(gen_comment.get("path", ""))
            gen_side = gen_comment.get("side")
            gen_from_line = gen_comment.get("from_line")
            gen_to_line = gen_comment.get("to_line")

            # 阶段 1：文件路径匹配
            if ref_path and gen_path and ref_path != gen_path:
                continue

            # 阶段 2：side 匹配
            if ref_side is not None and gen_side is not None and ref_side != gen_side:
                continue

            # 阶段 3：行号匹配 line(k)
            if all(x is not None for x in [ref_from_line, ref_to_line, gen_from_line, gen_to_line]):
                if not diff_location_is_same(
                    ref_from_line, ref_to_line, gen_from_line, gen_to_line, k
                ):
                    continue

            # 行号匹配成功（一条生成评论只能贡献一次行号匹配）
            if not line_matched and gen_idx not in matched_gen_ids_by_line:
                line_matched = True
                matched_gen_ids_by_line.add(gen_idx)

            # 已被语义匹配过的生成评论跳过
            if gen_idx in matched_gen_ids_by_semantic:
                continue

            # 阶段 4：语义匹配
            similarity = await match_semantic(ref_note_cleaned, gen_note_cleaned)
            if similarity.get("is_similar", False):
                semantic_matched = True
                matched_note_text = gen_note
                matched_gen_ids_by_semantic.add(gen_idx)
                break

        ref_comment["line_match"] = line_matched
        ref_comment["semantic_match"] = semantic_matched
        ref_comment["matched_note"] = matched_note_text

    return reference_comments


def compute_cr_statistics(
    comments: List[Dict[str, Any]], generated_count: int
) -> Dict[str, Any]:
    """根据评测后的 comments 计算单个样本的统计指标。"""
    total_expected = len([c for c in comments if isinstance(c, dict) and c.get("note")])
    line_match_count = sum(
        1 for c in comments if isinstance(c, dict) and c.get("line_match", False)
    )
    semantic_match_count = sum(
        1 for c in comments if isinstance(c, dict) and c.get("semantic_match", False)
    )
    return {
        "expected_notes": total_expected,
        "generated_notes": generated_count,
        "line_match_count": line_match_count,
        "semantic_match_count": semantic_match_count,
    }


def print_llm_request_statistics() -> None:
    """打印语义匹配请求统计信息。"""
    print("\n" + "=" * 50)
    print("语义匹配请求统计")
    print("=" * 50)
    print(f"裁判模型: {os.getenv(JUDGE_MODEL_VAR, '')}")
    print(f"总请求数: {llm_request_count}")
    print("=" * 50 + "\n")
