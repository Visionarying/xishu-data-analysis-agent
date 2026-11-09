"""问题理解与字段映射：规则优先兜底 + 大模型规划。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import llm
from .config import llm_configured
from .utils import compact_text

INTENT_LABELS = {
    "trend": "趋势分析",
    "anomaly": "异常识别",
    "compare": "指标对比",
    "query": "数据查询",
}
VALID_INTENTS = set(INTENT_LABELS)
VALID_GRANULARITIES = {"day", "week", "month", "quarter", "year"}
VALID_AGGREGATIONS = {"sum", "avg", "count", "min", "max"}
VALID_OPS = {"=", "!=", ">", ">=", "<", "<=", "contains", "in"}
GRANULARITY_LABELS = {"day": "日", "week": "周", "month": "月", "quarter": "季度", "year": "年"}
AGGREGATION_LABELS = {"sum": "求和", "avg": "平均值", "count": "计数", "min": "最小值", "max": "最大值"}

METRIC_PRIORITY = (
    "销售额",
    "销售金额",
    "成交额",
    "营收",
    "收入",
    "利润",
    "毛利",
    "销量",
    "数量",
    "订单量",
    "成本",
    "单价",
    "价格",
    "金额",
    "gmv",
)
GROUP_PRIORITY = ("区域", "地区", "省份", "城市", "部门", "产品", "类别", "渠道", "客户", "门店", "行业", "员工")
YEAR_HINTS = ("年份", "年度", "年", "year")


def select_sheet(question: str, sheets: list[dict], requested_id: str | None = None) -> dict:
    if requested_id:
        for sheet in sheets:
            if sheet["id"] == requested_id:
                return sheet
    if len(sheets) == 1:
        return sheets[0]

    lowered = question.lower().replace(" ", "")
    best = sheets[0]
    best_score = float("-inf")
    for sheet in sheets:
        score = 0.0
        if sheet["name"].lower().replace(" ", "") in lowered:
            score += 8
        mentioned = _mentioned(sheet["columns"], lowered)
        score += sum(score_item for _, score_item in mentioned) * 2.0
        types = {column["dtype"] for column in sheet["columns"]}
        if "datetime" in types and "number" in types:
            score += 2.0
        if sheet["row_count"] > 0:
            score += min(sheet["row_count"] / 100_000, 0.5)
        if score > best_score:
            best_score = score
            best = sheet
    return best


def _base_name(name: str) -> str:
    stripped = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    return stripped or name


def _note_aliases(note: str | None) -> list[str]:
    """把字段备注拆成可用于匹配的别名，如「毛利口径，不含运费」→ 毛利口径 / 毛利 / 不含运费。"""
    if not note:
        return []
    text = re.sub(r"[（(][^）)]*[）)]", "", note)
    aliases: set[str] = set()
    for part in re.split(r"[、，,;；/|\s]+", text):
        cleaned = re.sub(r"[=＝:：]", " ", part)
        for token in cleaned.split():
            token = token.strip()
            if len(token) < 2 or token.isdigit():
                continue
            aliases.add(token)
            for suffix in ("口径", "说明", "定义", "含义", "备注", "字段", "金额", "数值", "比例", "范围"):
                if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                    aliases.add(token[: -len(suffix)])
    return sorted(aliases)


def _mentioned(columns: list[dict], lowered_question: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for column in columns:
        candidates = {column["name"], _base_name(column["name"])}
        candidates.update(_note_aliases(column.get("note")))
        for candidate in candidates:
            key = candidate.lower().replace(" ", "")
            if len(key) >= 2 and key in lowered_question:
                found.append((column["name"], len(key)))
                break
    return found


def _mentioned_in(columns: list[dict], question: str) -> list[dict]:
    lowered = question.lower().replace(" ", "")
    names = {name for name, _ in _mentioned(columns, lowered)}
    return [column for column in columns if column["name"] in names]


def _pick_metric(columns: list[dict], question: str) -> str | None:
    numeric = [
        column
        for column in columns
        if column["dtype"] == "number"
        and column.get("unique", 0) > 1
        and not any(hint in column["name"].lower() for hint in YEAR_HINTS)
        and column.get("role") != "id"
    ]
    if not numeric:
        numeric = [column for column in columns if column["dtype"] == "number" and column.get("unique", 0) > 1]
    if not numeric:
        return None
    mentioned = _mentioned_in(numeric, question)
    if mentioned:
        return max(mentioned, key=lambda c: len(_base_name(c["name"])))["name"]
    for keyword in METRIC_PRIORITY:
        for column in numeric:
            note = (column.get("note") or "").lower()
            if keyword.lower() in column["name"].lower() or keyword.lower() in note:
                return column["name"]
    return numeric[0]["name"]


def _pick_time(columns: list[dict], question: str) -> str | None:
    dates = [column for column in columns if column["dtype"] == "datetime"]
    if not dates:
        return None
    mentioned = _mentioned_in(dates, question)
    if mentioned:
        return mentioned[0]["name"]
    for keyword in ("日期", "时间", "月份", "年月", "date", "time", "month"):
        for column in dates:
            if keyword in column["name"].lower():
                return column["name"]
    return dates[0]["name"]


def _pick_group(columns: list[dict], question: str, metric: str | None) -> str | None:
    candidates = [
        column
        for column in columns
        if column["name"] != metric
        and column["dtype"] in {"category", "text"}
        and column.get("role") != "id"
        and 2 <= column.get("unique", 0) <= 60
    ]
    if not candidates:
        return None
    mentioned = _mentioned_in(candidates, question)
    if mentioned:
        return mentioned[0]["name"]
    for keyword in GROUP_PRIORITY:
        if keyword in question:
            for column in candidates:
                if keyword in column["name"] or keyword in (column.get("note") or ""):
                    return column["name"]
    for keyword in GROUP_PRIORITY:
        for column in candidates:
            if keyword in column["name"] or keyword in (column.get("note") or ""):
                return column["name"]
    return min(candidates, key=lambda c: c.get("unique", 999))["name"]


def detect_intent(question: str) -> str:
    lowered = question.lower()
    scores = {"trend": 0, "anomaly": 0, "compare": 0, "query": 0}
    anomaly_words = ("异常", "波动", "突增", "突降", "离群", "outlier", "尖峰", "低谷", "骤降", "骤增")
    compare_strong = ("对比", "比较", "排名", "排序", "占比", "分布")
    compare_weak = ("各区域", "各城市", "各部门", "不同", "哪个", "最高", "最低", "谁")
    trend_words = ("趋势", "走势", "变化", "增长", "下降", "近", "最近", "过去", "每月", "月度", "逐月", "同比", "环比", "时间")

    for word in anomaly_words:
        if word in lowered:
            scores["anomaly"] += 3
    for word in compare_strong:
        if word in lowered:
            scores["compare"] += 3
    for word in compare_weak:
        if word in lowered:
            scores["compare"] += 1
    for word in trend_words:
        if word in lowered:
            scores["trend"] += 1
    if re.search(r"近\s*\d+\s*个?\s*(月|天|日|周|年|季度)", question):
        scores["trend"] += 2
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "query"


def extract_period(question: str) -> tuple[int | None, str | None]:
    match = re.search(r"(?:近|最近|过去|前)\s*(\d+)\s*个?\s*(天|日|周|月|季度|年)", question)
    if not match:
        return None, None
    value = int(match.group(1))
    unit = {"天": "day", "日": "day", "周": "week", "月": "month", "季度": "quarter", "年": "year"}[match.group(2)]
    return (value if 1 <= value <= 120 else None), unit


def _detect_granularity(question: str, period_unit: str | None) -> str:
    if "季度" in question:
        return "quarter"
    if "周" in question and "周末" not in question:
        return "week"
    if "天" in question or "日" in question:
        return "day"
    if "年" in question and "月份" not in question:
        return "year"
    if period_unit in VALID_GRANULARITIES:
        return period_unit
    return "month"


def _pick_aggregation(metric: str | None, question: str) -> str:
    if not metric:
        return "count"
    lowered = metric.lower()
    if "平均" in question or any(key in lowered for key in ("单价", "均价", "价格", "率", "占比", "评分", "满意度")):
        return "avg"
    return "sum"


def _is_followup(question: str) -> bool:
    """判断是否像追问：短句或带有承接词。"""
    text = question.strip()
    if len(text) <= 10:
        return True
    for hint in ("那", "再", "换成", "改成", "只看", "仅看", "呢", "同样", "继续", "其中", "这个", "它"):
        if hint in text:
            return True
    return False


def _column_by_name(sheet: dict, name: str | None, dtypes: set[str] | None = None) -> dict | None:
    if not name:
        return None
    for column in sheet["columns"]:
        if column["name"] == name and (dtypes is None or column["dtype"] in dtypes):
            return column
    return None


def _extract_filter_from_question(question: str, sheet: dict, group_field: str | None) -> list[dict]:
    """从「只看华东」「仅看线上渠道」这类追问里提取等值筛选。"""
    if not group_field or not any(word in question for word in ("只看", "仅看", "只要", "限定", "其中", "剔除")):
        return []
    column = _column_by_name(sheet, group_field, {"category", "text"})
    if not column:
        return []
    for item in column.get("top_values") or []:
        value = str(item.get("value", ""))
        if len(value) >= 1 and value in question:
            return [{"field": group_field, "op": "=", "value": value}]
    return []


def heuristic_plan(question: str, sheet: dict, context: dict | None = None) -> dict:
    columns = sheet["columns"]
    intent = detect_intent(question)
    metric = _pick_metric(columns, question)
    time_field = _pick_time(columns, question)
    group_field = _pick_group(columns, question, metric)
    period_value, period_unit = extract_period(question)
    granularity = _detect_granularity(question, period_unit)

    if intent == "anomaly" and not period_unit:
        granularity = "month"
    if intent == "query":
        if not group_field and not time_field:
            # 无时间/维度时，退化为记录数汇总
            metric = None

    plan = {
        "intent": intent,
        "sheet_id": sheet["id"],
        "time_field": time_field,
        "metric_field": metric,
        "group_field": group_field,
        "aggregation": _pick_aggregation(metric, question),
        "granularity": granularity,
        "period_value": period_value or (12 if intent == "trend" and time_field else None),
        "period_unit": period_unit or ("month" if intent == "trend" and time_field else None),
        "top_n": 10,
        "filters": [],
        "rationale": "根据字段名称、字段类型与问题关键词生成默认口径。",
        "mode": "rule",
    }

    if context and _is_followup(question):
        cited_metric = _mentioned_in([c for c in columns if c["dtype"] == "number"], question)
        cited_group = _mentioned_in(
            [c for c in columns if c["dtype"] in {"category", "text"}], question
        )
        ctx_intent = context.get("intent")
        if intent == "query" and ctx_intent in VALID_INTENTS and not any(
            word in question for word in ("整体", "概览", "多少行", "概况")
        ):
            plan["intent"] = ctx_intent
            plan["rationale"] = "追问：沿用上一轮的分析类型。"
        if not cited_metric and _column_by_name(sheet, context.get("metric_field"), {"number"}):
            plan["metric_field"] = context["metric_field"]
        if plan["metric_field"]:
            plan["aggregation"] = context.get("aggregation") if context.get("aggregation") in VALID_AGGREGATIONS else plan["aggregation"]
        if plan["intent"] == "compare" and not cited_group and _column_by_name(sheet, context.get("group_field")):
            plan["group_field"] = context["group_field"]
        if plan["intent"] in {"trend", "anomaly"} and _column_by_name(sheet, context.get("time_field"), {"datetime"}):
            if not _mentioned_in([c for c in columns if c["dtype"] == "datetime"], question):
                plan["time_field"] = context["time_field"]
        if not period_unit and not any(word in question for word in ("天", "日", "周", "月", "季度", "年")):
            if context.get("granularity") in VALID_GRANULARITIES:
                plan["granularity"] = context["granularity"]
            if context.get("period_value"):
                plan["period_value"] = context["period_value"]
                plan["period_unit"] = context.get("period_unit")
        inherited_filters = [
            item for item in (context.get("filters") or [])
            if isinstance(item, dict) and _column_by_name(sheet, item.get("field"))
        ]
        if inherited_filters and not plan["filters"]:
            plan["filters"] = inherited_filters[:5]
        focus_filters = _extract_filter_from_question(question, sheet, plan.get("group_field"))
        for item in focus_filters:
            if item not in plan["filters"]:
                plan["filters"].append(item)
        plan["follow_up"] = True
        if not plan["rationale"].startswith("追问"):
            plan["rationale"] = "追问：继承上一轮未改变的口径。" + plan["rationale"]

    return plan


def _sheet_brief(sheets: list[dict]) -> str:
    lines: list[str] = []
    for sheet in sheets[:10]:
        lines.append(f"工作表：{sheet['name']}（{sheet['row_count']:,} 行 × {sheet['col_count']} 列）")
        for column in sheet["columns"][:40]:
            extra = ""
            if column["dtype"] == "number":
                extra = f" min={column.get('min')} max={column.get('max')}"
            elif column["dtype"] == "datetime":
                extra = f" {column.get('min')} → {column.get('max')}"
            elif column.get("top_values"):
                extra = " 示例=" + "、".join(str(item["value"]) for item in column["top_values"][:3])
            elif column.get("sample"):
                extra = " 示例=" + "、".join(str(value) for value in column["sample"][:2])
            note = column.get("note")
            note_text = f" | 备注={note}" if note else ""
            lines.append(
                f"  - {column['name']} | {column['dtype']} | 唯一值 {column.get('unique', 0)}{extra}{note_text}"
            )
        lines.append("")
    return "\n".join(lines).strip()


PLANNER_SYSTEM = """你是严谨的数据分析规划器。你的任务是把用户问题映射到给定工作表的字段上，并选择分析类型。
只输出 JSON 对象，不要输出解释、Markdown 或代码块。
JSON 结构：
{
  "sheet": "工作表名称",
  "intent": "trend | anomaly | compare | query",
  "time_field": "日期字段名或 null",
  "metric_field": "数值字段名或 null",
  "group_field": "分组字段名或 null",
  "aggregation": "sum | avg | count | min | max",
  "granularity": "day | week | month | quarter | year",
  "period_value": 12,
  "period_unit": "day | week | month | quarter | year",
  "top_n": 10,
  "filters": [],
  "rationale": "一句话说明口径"
}
规则：
1. 只能使用清单中真实存在的字段名，不得虚构字段。
2. 趋势、异常必须选择日期字段；对比必须选择分组字段；指标优先选择金额/数量类数值字段。
3. 用户说“近12个月”时 period_value=12、period_unit=month、granularity=month；未指定周期时趋势默认近 12 个月。
4. 百分比、单价、均值类指标用 avg，金额/数量用 sum；无合适指标时用 count。
5. 不确定的字段填 null，不要猜测。最多 5 个过滤条件，op 只能是 = != > >= < <= contains in。
6. 字段后的「备注」是用户写的业务口径或别名：当用户提到备注中的词（如把“毛利”备注在“利润”字段上）时，应选择该字段。
7. 如果用户本轮像追问（如“那利润呢”“只看华东”“再按月看看”），请沿用上一轮未明确改变的口径。"""



def _context_brief(context: dict | None) -> str:
    if not context:
        return ""
    parts: list[str] = []
    labels = {
        "question": "上一轮问题",
        "intent": "分析类型",
        "time_field": "时间字段",
        "metric_field": "指标字段",
        "group_field": "分组字段",
        "aggregation": "聚合方式",
        "granularity": "时间粒度",
    }
    for key, label in labels.items():
        value = context.get(key)
        if value:
            parts.append(f"{label}={value}")
    if context.get("period_value") and context.get("period_unit"):
        parts.append(f"统计周期=近{context['period_value']}{GRANULARITY_LABELS.get(context['period_unit'], context['period_unit'])}")
    if context.get("filters"):
        filter_text = "、".join(
            f"{item.get('field')} {item.get('op')} {item.get('value')}"
            for item in context["filters"]
            if isinstance(item, dict)
        )
        if filter_text:
            parts.append(f"筛选={filter_text}")
    if not parts:
        return ""
    return "上一轮分析口径：" + "；".join(parts) + "。\n如果本轮是追问，请沿用没有明确改变的口径。"


def _llm_plan(question: str, sheets: list[dict], context: dict | None = None) -> tuple[dict | None, str | None]:
    if not llm_configured():
        return None, None
    context_text = _context_brief(context)
    user = f"数据表信息：\n{_sheet_brief(sheets)}\n\n{context_text}\n用户问题：{question}".strip()
    try:
        raw = llm.chat_json(PLANNER_SYSTEM, user, temperature=0.1, max_tokens=600)
        if not isinstance(raw, dict):
            raise llm.LLMError("规划结果不是对象")
        return raw, None
    except llm.LLMError as exc:
        return None, f"模型规划失败，已使用规则口径（{exc}）。"


def _resolve_column(sheet: dict, name: Any, dtype: str | None = None) -> dict | None:
    if not isinstance(name, str) or not name.strip():
        return None
    target = name.strip().lower().replace(" ", "")
    columns = sheet["columns"]
    for column in columns:
        if column["name"].lower().replace(" ", "") == target:
            return column
    for column in columns:
        if _base_name(column["name"]).lower().replace(" ", "") == target:
            return column
    for column in columns:
        if target in column["name"].lower().replace(" ", ""):
            if dtype is None or column["dtype"] == dtype:
                return column
    return None


def _normalize_filters(raw: Any, sheet: dict) -> list[dict]:
    if not isinstance(raw, list):
        return []
    filters: list[dict] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        column = _resolve_column(sheet, item.get("field"))
        op = item.get("op")
        if not column or op not in VALID_OPS or "value" not in item:
            continue
        value = item.get("value")
        if isinstance(value, (dict, list)):
            if op != "in" or not isinstance(value, list):
                continue
            value = value[:50]
        filters.append({"field": column["name"], "op": op, "value": value})
    return filters


def plan_question(
    question: str,
    sheets: list[dict],
    requested_sheet_id: str | None = None,
    context: dict | None = None,
) -> tuple[dict, dict, list[str]]:
    warnings: list[str] = []
    sheet = select_sheet(question, sheets, requested_sheet_id)
    plan = heuristic_plan(question, sheet, context)

    raw, llm_warning = _llm_plan(question, sheets, context)
    if llm_warning:
        warnings.append(llm_warning)
    if not raw:
        return plan, sheet, warnings

    chosen = select_sheet(question, sheets, requested_sheet_id)
    if isinstance(raw.get("sheet"), str):
        target = raw["sheet"].strip().lower().replace(" ", "")
        for candidate in sheets:
            name = candidate["name"].strip().lower().replace(" ", "")
            if name == target or target in name or name in target:
                chosen = candidate
                break
    if chosen["id"] != sheet["id"] and requested_sheet_id is None:
        sheet = chosen
        plan = heuristic_plan(question, sheet, context)

    intent = raw.get("intent")
    if intent in VALID_INTENTS:
        if intent != plan["intent"]:
            plan["rationale"] = "模型判断分析类型：" + INTENT_LABELS[intent] + "。"
        plan["intent"] = intent
    plan["mode"] = "llm"

    time_column = _resolve_column(sheet, raw.get("time_field"), "datetime")
    if time_column and plan["intent"] in {"trend", "anomaly"}:
        plan["time_field"] = time_column["name"]
    metric_column = _resolve_column(sheet, raw.get("metric_field"), "number")
    if metric_column:
        plan["metric_field"] = metric_column["name"]
    group_column = _resolve_column(sheet, raw.get("group_field"))
    if group_column and group_column["dtype"] in {"category", "text"}:
        plan["group_field"] = group_column["name"]
    elif group_column and group_column["dtype"] in {"number", "datetime"}:
        if 2 <= group_column.get("unique", 0) <= 60:
            plan["group_field"] = group_column["name"]
    if raw.get("aggregation") in VALID_AGGREGATIONS:
        plan["aggregation"] = raw["aggregation"]
    if raw.get("granularity") in VALID_GRANULARITIES:
        plan["granularity"] = raw["granularity"]
    if raw.get("period_unit") in VALID_GRANULARITIES:
        try:
            period_value = int(raw.get("period_value"))
        except (TypeError, ValueError):
            period_value = 0
        if 1 <= period_value <= 120:
            plan["period_value"] = period_value
            plan["period_unit"] = raw["period_unit"]
    try:
        top_n = int(raw.get("top_n", 10))
        plan["top_n"] = min(max(top_n, 3), 30)
    except (TypeError, ValueError):
        pass
    filters = _normalize_filters(raw.get("filters"), sheet)
    if filters:
        plan["filters"] = filters
    rationale = raw.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        plan["rationale"] = compact_text(rationale, 160)
    plan["sheet_id"] = sheet["id"]

    # 兜底修正不可能的规划
    if plan["intent"] in {"trend", "anomaly"} and not plan["time_field"]:
        warnings.append("未找到可用的日期字段，已改为常规数据查询。")
        plan["intent"] = "query"
    if plan["intent"] == "compare" and not plan["group_field"]:
        fallback_group = _pick_group(sheet["columns"], question, plan.get("metric_field"))
        if fallback_group:
            plan["group_field"] = fallback_group
            warnings.append("模型未指定有效分组字段，已自动选择：" + fallback_group)
        else:
            warnings.append("未找到适合分组对比的字段，已改为常规数据查询。")
            plan["intent"] = "query"
    if plan["intent"] != "compare":
        plan["group_field"] = plan["group_field"] if plan["intent"] == "query" else None
    if plan["metric_field"]:
        metric_meta = next((c for c in sheet["columns"] if c["name"] == plan["metric_field"]), None)
        if metric_meta and metric_meta["dtype"] != "number":
            plan["metric_field"] = None
            plan["aggregation"] = "count"

    if plan["intent"] == "trend" and not plan.get("period_value") and plan["time_field"]:
        plan["period_value"], plan["period_unit"] = 12, "month"
        plan["granularity"] = "month"
    return plan, sheet, warnings


def plan_summary(plan: dict, sheet: dict) -> str:
    parts = [INTENT_LABELS.get(plan["intent"], "数据分析"), f"工作表「{sheet['name']}」"]
    if plan.get("time_field"):
        parts.append(f"时间字段：{plan['time_field']}（按{GRANULARITY_LABELS.get(plan['granularity'], '月')}）")
    if plan.get("metric_field"):
        parts.append(
            f"指标：{plan['metric_field']}（{AGGREGATION_LABELS.get(plan['aggregation'], '求和')}）"
        )
    if plan.get("group_field"):
        parts.append(f"分组：{plan['group_field']}")
    return "；".join(parts)
