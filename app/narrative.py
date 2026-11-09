"""结论生成：优先大模型，带数字校验；模型不可用时由规则引擎生成。"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from . import llm
from .config import llm_configured
from .utils import extract_numbers, fmt_number, fmt_percent

NARRATIVE_SYSTEM = """你是严谨的中文数据分析师。你会收到一份已经由本地引擎计算好的分析结果。
请撰写结论，必须遵守：
1. 只能使用输入中出现的数字、字段名和事实，绝对不得新增或推算任何数字；不确定就不要写数字。
2. 明确区分“数据事实”和“推测/建议”。事实必须能在输入中核对。
3. 不做因果断言，不预测未来，不使用“必然”“证明”“导致”等表述；推测需使用“可能”“或许”等措辞。
4. 语言简洁、专业，适合业务人员阅读。
只输出 JSON 对象，不要 Markdown 代码块：
{"one_liner": "一句话结论（不超过 60 字）", "facts": ["数据事实，2-5 条"], "inferences": ["推测或解释，1-3 条"], "suggestions": ["下一步建议，2-4 条"]}"""


def _display(result: dict, value: Any) -> str:
    if value is None:
        return "—"
    if result.get("unit") == "%":
        return fmt_percent(value)
    number = fmt_number(value)
    unit = result.get("unit") or ""
    return f"{number}{unit}" if unit else number


def rule_conclusion(result: dict) -> dict:
    intent = result.get("intent", "query")
    metric = result.get("metric") or "记录数"
    unit = result.get("unit") or ""
    chart = result.get("chart") or {}
    categories = chart.get("categories") or []
    values = (chart.get("series") or [{}])[0].get("data") or []
    stats = result.get("stats") or {}
    aggregation = result.get("aggregation") or "sum"
    agg_word = "平均" if aggregation == "avg" else ("合计" if aggregation == "sum" else "统计")
    facts = list(result.get("facts") or [])
    inferences = list(result.get("inferences") or [])
    suggestions = list(result.get("suggestions") or [])

    if intent == "trend":
        direction = stats.get("direction", "平稳")
        peak_label = stats.get("peak_label", "—")
        peak = _display(result, stats.get("peak"))
        if aggregation == "avg":
            headline = (
                f"{len(values)} 个周期内{metric}平均 {_display(result, stats.get('average'))}，"
                f"整体呈{direction}趋势，{peak_label} 达到峰值。"
            )
        else:
            headline = (
                f"{len(values)} 个周期内{metric}{agg_word} {_display(result, stats.get('total'))}，"
                f"整体呈{direction}趋势，{peak_label} 达到峰值。"
            )
    elif intent == "anomaly":
        anomalies = result.get("anomalies") or []
        if anomalies:
            strongest = anomalies[0]
            headline = (
                f"识别到 {len(anomalies)} 个异常点，{strongest.get('label')} 的{metric} "
                f"{_display(result, strongest.get('value'))}偏离最为显著。"
            )
        else:
            headline = f"按稳健 Z 分数阈值未发现显著异常，{metric}整体波动处于正常范围。"
    elif intent == "compare":
        top_label = stats.get("top_label", "—")
        top_value = _display(result, stats.get("top_value"))
        headline = f"{top_label} 的{metric}最高，为 {top_value}，共对比 {stats.get('n_groups', len(values))} 个分组。"
    else:
        records = stats.get("records")
        if records is not None:
            headline = f"当前数据共 {records:,} 条记录，已完成{metric}的汇总查询。"
        else:
            headline = f"已完成{metric}的查询，共返回 {len(values) or len(result.get('table', {}).get('rows', []))} 条汇总结果。"

    if not facts:
        facts = [f"分析口径：{result.get('method', {}).get('aggregation', '聚合')} {metric}。"]
    if not inferences:
        inferences = ["以上为描述性统计结果，不代表因果结论或未来走势。"]
    if not suggestions:
        suggestions = ["可继续补充时间范围、分组字段或筛选条件，缩小分析口径。"]
    return {
        "one_liner": headline,
        "facts": facts,
        "inferences": inferences,
        "suggestions": suggestions,
        "source": "rules",
        "model": None,
    }


def _collect_allowed_numbers(value: Any, allowed: set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _collect_allowed_numbers(item, allowed)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_allowed_numbers(item, allowed)
    elif isinstance(value, str):
        allowed.update(extract_numbers(value))
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(number):
            return
        for rounder in (None, 0, 1, 2, 3):
            candidate = number if rounder is None else round(number, rounder)
            allowed.update(extract_numbers(f"{candidate}"))
            allowed.update(extract_numbers(f"{abs(candidate)}"))


def _allowed_numbers(result: dict, rule: dict) -> set[str]:
    allowed: set[str] = set()
    _collect_allowed_numbers(result, allowed)
    _collect_allowed_numbers(rule, allowed)
    # 常见的方法阈值与时间单位，避免误伤合理表述
    allowed.update({"1", "2", "3", "4", "5", "12", "100", "3.5", "1.5"})
    return allowed


def _validate_numbers(texts: list[str], allowed: set[str]) -> list[str]:
    unknown: list[str] = []
    for text in texts:
        for token in extract_numbers(text):
            if token not in allowed:
                unknown.append(token)
    return sorted(set(unknown), key=lambda token: float(token))


def _compact_context(result: dict, rule: dict) -> str:
    chart = result.get("chart") or {}
    table = result.get("table") or {}
    context = {
        "问题相关分析": {
            "类型": result.get("intent_label"),
            "工作表": (result.get("sheet") or {}).get("name"),
            "指标": result.get("metric"),
            "单位": result.get("unit"),
            "聚合方式": result.get("aggregation"),
            "数据行数": (result.get("sheet") or {}).get("row_count"),
            "统计摘要": result.get("stats"),
        },
        "关键指标卡": result.get("metrics"),
        "图表数据": {
            "维度": chart.get("categories", [])[:24],
            "数值": (chart.get("series") or [{}])[0].get("data", [])[:24],
            "异常点": chart.get("anomalies", [])[:10],
        },
        "数据明细（前 12 行）": table.get("rows", [])[:12],
        "本地规则生成的事实": rule.get("facts"),
        "本地规则生成的推测": rule.get("inferences"),
        "分析口径": {
            key: value
            for key, value in (result.get("method") or {}).items()
            if key in {"time_field", "granularity", "aggregation", "period", "group_field", "detection", "threshold", "filters"}
        },
    }
    return json.dumps(context, ensure_ascii=False, default=str)


def ai_conclusion(result: dict, rule: dict) -> tuple[dict, str | None]:
    if not llm_configured():
        return rule, None
    prompt = (
        "请基于以下分析结果撰写结论。再次强调：不得出现输入中没有的数字。\n\n"
        + _compact_context(result, rule)
    )
    try:
        raw = llm.chat_json(NARRATIVE_SYSTEM, prompt, temperature=0.2, max_tokens=900)
        if not isinstance(raw, dict):
            return rule, "模型结论格式异常"
        one_liner = str(raw.get("one_liner") or "").strip()
        facts = [str(item).strip() for item in (raw.get("facts") or []) if str(item).strip()]
        inferences = [str(item).strip() for item in (raw.get("inferences") or []) if str(item).strip()]
        suggestions = [str(item).strip() for item in (raw.get("suggestions") or []) if str(item).strip()]
        if not one_liner or not facts:
            return rule, "模型结论缺少必要字段"
        if len(one_liner) > 120:
            one_liner = one_liner[:119] + "…"
        texts = [one_liner, *facts, *inferences, *suggestions]
        unknown = _validate_numbers(texts, _allowed_numbers(result, rule))
        if unknown:
            return rule, "模型结论出现未在结果中出现的数字，已自动改用规则结论"
        return {
            "one_liner": one_liner,
            "facts": facts[:5],
            "inferences": inferences[:3],
            "suggestions": suggestions[:4],
            "source": "model",
            "model": None,
        }, None
    except llm.LLMError as exc:
        return rule, f"模型结论生成失败（{exc}），已使用本地规则结论"
    except Exception as exc:  # pragma: no cover - 防御性处理
        return rule, f"模型结论生成异常（{type(exc).__name__}），已使用本地规则结论"


def build_conclusion(result: dict) -> tuple[dict, list[str]]:
    rule = rule_conclusion(result)
    warnings: list[str] = []
    if not llm_configured():
        return rule, warnings
    conclusion, warning = ai_conclusion(result, rule)
    if warning:
        warnings.append(warning)
    return conclusion, warnings
