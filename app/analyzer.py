"""本地分析引擎：由 DuckDB 在只读查询中完成聚合，不依赖模型生成数字。"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .planner import AGGREGATION_LABELS, GRANULARITY_LABELS, INTENT_LABELS
from .utils import fmt_number, fmt_percent, json_safe, quote_ident, quote_literal, safe_float

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    pass


PERCENT_HINTS = ("率", "占比", "percent", "ratio", "同比", "环比")
MONEY_HINTS = ("销售额", "金额", "收入", "营收", "利润", "毛利", "成本", "价格", "单价", "费", "额", "gmv")
COUNT_HINTS = ("销量", "数量", "件数", "订单量", "人数", "次数", "库存")


def _source(path: str) -> str:
    safe_path = Path(path).as_posix().replace("'", "''")
    return f"read_parquet('{safe_path}')"


def _run(sql: str) -> pd.DataFrame:
    statement = sql.lstrip()
    if not statement.lower().startswith("select") or ";" in statement:
        raise AnalysisError("仅允许执行单条只读查询。")
    con = duckdb.connect()
    try:
        return con.execute(sql).fetchdf()
    except Exception as exc:  # DuckDB 的错误信息可能包含路径，仅记录服务端日志
        logger.warning("DuckDB query failed: %s", exc)
        raise AnalysisError("本地查询执行失败，请检查字段口径后重试。") from exc
    finally:
        con.close()


def infer_unit(metric: str | None, is_percent: bool = False) -> str:
    if metric is None:
        return "条"
    if is_percent or any(hint in metric for hint in PERCENT_HINTS):
        return "%"
    if any(hint in metric for hint in MONEY_HINTS):
        return "元"
    if any(hint in metric for hint in COUNT_HINTS):
        return "件"
    return ""


def _agg_label(aggregation: str) -> str:
    return AGGREGATION_LABELS.get(aggregation, "汇总")


def _display_value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return fmt_percent(value)
    return f"{fmt_number(value)}{unit}"


def _metric_expr(metric: str | None, aggregation: str) -> str:
    if aggregation == "count" or not metric:
        return "count(*)"
    column = quote_ident(metric)
    if aggregation == "avg":
        return f"avg({column})"
    if aggregation == "min":
        return f"min({column})"
    if aggregation == "max":
        return f"max({column})"
    return f"sum({column})"


def _bucket_expr(column: str, granularity: str) -> str:
    quoted = quote_ident(column)
    if granularity == "day":
        return f"CAST({quoted} AS DATE)"
    if granularity == "week":
        return f"CAST(date_trunc('week', {quoted}) AS DATE)"
    if granularity == "quarter":
        return f"CAST(date_trunc('quarter', {quoted}) AS DATE)"
    if granularity == "year":
        return f"CAST(date_trunc('year', {quoted}) AS DATE)"
    return f"CAST(date_trunc('month', {quoted}) AS DATE)"


def _bucket_label(value: Any, granularity: str) -> str:
    timestamp = pd.Timestamp(value)
    if granularity == "month":
        return f"{timestamp.year}-{timestamp.month:02d}"
    if granularity == "quarter":
        return f"{timestamp.year}-Q{(timestamp.month - 1) // 3 + 1}"
    if granularity == "year":
        return str(timestamp.year)
    return timestamp.strftime("%Y-%m-%d")


def _filters_sql(filters: list[dict], columns: dict[str, dict]) -> list[str]:
    parts: list[str] = []
    for item in filters:
        name = item.get("field")
        op = item.get("op")
        value = item.get("value")
        column = columns.get(name)
        if not column or not op:
            continue
        quoted = quote_ident(name)
        if column["dtype"] == "number":
            if op == "contains":
                parts.append(f"CAST({quoted} AS VARCHAR) LIKE {quote_literal('%' + str(value) + '%')}")
                continue
            if op == "in":
                if not isinstance(value, list):
                    continue
                numbers = [safe_float(v) for v in value]
                numbers = [number for number in numbers if number is not None]
                if numbers:
                    parts.append(f"{quoted} IN ({', '.join(str(number) for number in numbers)})")
                continue
            number = safe_float(value)
            if number is None:
                continue
            parts.append(f"{quoted} {op} {number}")
        elif column["dtype"] == "datetime":
            try:
                moment = pd.Timestamp(value)
            except (ValueError, TypeError):
                continue
            literal = moment.strftime("%Y-%m-%d %H:%M:%S")
            if op == "in" and isinstance(value, list):
                literals = []
                for entry in value[:50]:
                    try:
                        literals.append(f"TIMESTAMP '{pd.Timestamp(entry).strftime('%Y-%m-%d %H:%M:%S')}'")
                    except (ValueError, TypeError):
                        continue
                if literals:
                    parts.append(f"{quoted} IN ({', '.join(literals)})")
                continue
            parts.append(f"{quoted} {op if op != '=' else '='} TIMESTAMP '{literal}'")
        else:
            if op == "contains":
                escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                parts.append(f"CAST({quoted} AS VARCHAR) LIKE {quote_literal('%' + escaped + '%')} ESCAPE '\\'")
            elif op == "in" and isinstance(value, list):
                values = [quote_literal(str(entry)) for entry in value[:50]]
                if values:
                    parts.append(f"CAST({quoted} AS VARCHAR) IN ({', '.join(values)})")
            else:
                parts.append(f"CAST({quoted} AS VARCHAR) {op} {quote_literal(str(value))}")
    return parts


def _period_start(max_date: pd.Timestamp, value: int, unit: str) -> pd.Timestamp:
    max_date = pd.Timestamp(max_date)
    if unit == "day":
        return (max_date.normalize() - pd.Timedelta(days=value - 1)).normalize()
    if unit == "week":
        return (max_date.normalize() - pd.Timedelta(weeks=value - 1)).normalize()
    if unit == "quarter":
        quarter_start = pd.Timestamp(max_date.year, ((max_date.month - 1) // 3) * 3 + 1, 1)
        return quarter_start - pd.DateOffset(months=3 * (value - 1))
    if unit == "year":
        return pd.Timestamp(max_date.year, 1, 1) - pd.DateOffset(years=value - 1)
    month_start = pd.Timestamp(max_date.year, max_date.month, 1)
    return month_start - pd.DateOffset(months=value - 1)


def _bounds(source: str, time_column: str, where: list[str]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    condition = " AND ".join([f"{quote_ident(time_column)} IS NOT NULL", *where])
    frame = _run(
        f"SELECT min({quote_ident(time_column)}) AS min_d, max({quote_ident(time_column)}) AS max_d "
        f"FROM {source} WHERE {condition}"
    )
    if frame.empty or pd.isna(frame.iloc[0]["min_d"]):
        return None, None
    return pd.Timestamp(frame.iloc[0]["min_d"]), pd.Timestamp(frame.iloc[0]["max_d"])


def _time_filter(
    time_column: str,
    plan: dict,
    to_max: pd.Timestamp | None,
) -> tuple[str | None, str | None]:
    value = plan.get("period_value")
    unit = plan.get("period_unit")
    if not value or not unit or to_max is None:
        return None, None
    start = _period_start(to_max, int(value), str(unit))
    quoted = quote_ident(time_column)
    clause = (
        f"{quoted} >= TIMESTAMP '{start.strftime('%Y-%m-%d %H:%M:%S')}' "
        f"AND {quoted} <= TIMESTAMP '{to_max.strftime('%Y-%m-%d %H:%M:%S')}'"
    )
    return clause, start.strftime("%Y-%m-%d")


def _metrics_from_trend(
    labels: list[str],
    values: np.ndarray,
    metric: str,
    unit: str,
    aggregation: str,
    granularity: str,
    is_percent: bool,
) -> tuple[list[dict], dict]:
    total = float(values.sum())
    average = float(values.mean())
    peak_index = int(np.argmax(values))
    low_index = int(np.argmin(values))
    last = float(values[-1])
    previous = float(values[-2]) if len(values) > 1 else None
    change = (last - previous) / abs(previous) if previous not in (None, 0) else None

    agg_word = _agg_label(aggregation)
    first_label = f"{_agg_label(aggregation)}{metric}" if aggregation != "count" else "记录数"
    metric_cards: list[dict] = []

    def display(value: float | None) -> str:
        if value is None:
            return "—"
        return fmt_percent(value) if unit == "%" else f"{fmt_number(value)}{unit}"

    metric_cards.append(
        {
            "label": f"累计{metric}" if aggregation == "sum" else (f"平均{metric}" if aggregation == "avg" else first_label),
            "display": display(total if aggregation != "avg" else average),
            "raw": safe_float(total if aggregation != "avg" else average),
            "hint": f"{len(values)} 个{GRANULARITY_LABELS.get(granularity, '周期')}周期",
            "tone": "default",
        }
    )
    metric_cards.append(
        {
            "label": "期间均值",
            "display": display(average),
            "raw": safe_float(average),
            "hint": f"按{GRANULARITY_LABELS.get(granularity, '周期')}平均",
            "tone": "default",
        }
    )
    metric_cards.append(
        {
            "label": "峰值",
            "display": display(float(values[peak_index])),
            "raw": safe_float(values[peak_index]),
            "hint": labels[peak_index],
            "tone": "positive",
        }
    )
    if change is not None:
        signed = f"{change * 100:+.1f}%"
        metric_cards.append(
            {
                "label": "最新环比",
                "display": signed,
                "raw": round(change, 6),
                "hint": f"{labels[-1]} vs {labels[-2]}",
                "tone": "positive" if change > 0 else ("negative" if change < 0 else "default"),
            }
        )
    else:
        metric_cards.append(
            {
                "label": "最新值",
                "display": display(last),
                "raw": safe_float(last),
                "hint": labels[-1] if labels else "",
                "tone": "default",
            }
        )

    stats = {
        "total": total,
        "average": average,
        "peak": float(values[peak_index]),
        "peak_label": labels[peak_index],
        "low": float(values[low_index]),
        "low_label": labels[low_index],
        "last": last,
        "last_label": labels[-1],
        "previous": previous,
        "change": change,
    }
    return metric_cards, stats


def _trend_direction(values: np.ndarray) -> tuple[str, float]:
    """用首尾窗口中位数对比判断方向，避免单一尖峰拉偏整体判断。"""
    if len(values) < 2:
        return "平稳", 0.0
    window = max(1, len(values) // 4)
    start = float(np.median(values[:window]))
    end = float(np.median(values[-window:]))
    if start == 0:
        return "平稳", 0.0
    normalized = (end - start) / abs(start)
    if normalized > 0.03:
        return "上升", normalized
    if normalized < -0.03:
        return "下降", normalized
    return "平稳", normalized


def _summary_label(metric: str | None, aggregation: str) -> str:
    name = metric or "记录数"
    if aggregation == "sum":
        return f"{name}合计"
    if aggregation == "avg":
        return f"{name}平均"
    if aggregation == "count":
        return name
    return f"{name}{_agg_label(aggregation)}"


def _table_from_rows(columns: list[dict], rows: list[dict], total: int | None = None) -> dict:
    return {
        "columns": columns,
        "rows": [{key: json_safe(value) for key, value in row.items()} for row in rows],
        "total_rows": total if total is not None else len(rows),
        "truncated": bool(total is not None and total > len(rows)),
    }


def _chart_base(kind: str, title: str, metric: str, unit: str, is_percent: bool) -> dict:
    return {
        "type": kind,
        "title": title,
        "metric": metric,
        "unit": unit,
        "value_format": "percent" if is_percent or unit == "%" else "number",
        "categories": [],
        "series": [],
        "anomalies": [],
        "horizontal": False,
    }


def _compare(
    source: str,
    plan: dict,
    sheet: dict,
    columns: dict[str, dict],
    filters: list[str],
    metric: str | None,
    unit: str,
    is_percent: bool,
    aggregation: str,
) -> dict:
    group = plan["group_field"]
    metric_expr = _metric_expr(metric, aggregation)
    conditions = [f"{quote_ident(group)} IS NOT NULL", *filters]
    if metric and aggregation != "count":
        conditions.append(f"{quote_ident(metric)} IS NOT NULL")
    period_text = "全部数据"
    time_column = plan.get("time_field")
    if time_column in columns:
        _, max_date = _bounds(source, time_column, filters)
        date_clause, _ = _time_filter(time_column, plan, max_date)
        if date_clause:
            conditions.append(date_clause)
            period_unit = GRANULARITY_LABELS.get(str(plan.get("period_unit")), "月")
            period_text = f"近 {plan.get('period_value')} {period_unit}（截至 {max_date:%Y-%m-%d}）"
    condition = " AND ".join(conditions)
    sql = (
        f"SELECT CAST({quote_ident(group)} AS VARCHAR) AS label, {metric_expr} AS value, count(*) AS records "
        f"FROM {source} WHERE {condition} GROUP BY 1 ORDER BY value DESC LIMIT 500"
    )
    frame = _run(sql)
    if frame.empty:
        raise AnalysisError("当前筛选条件下没有可对比的分组数据，请检查分组字段是否为空。")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["label"])
    if frame.empty:
        raise AnalysisError("分组字段没有有效取值。")

    values = frame["value"].to_numpy(dtype=float)
    labels = [str(value) for value in frame["label"].tolist()]
    records = frame["records"].astype(int).tolist()
    total = float(values.sum())
    share_allowed = aggregation in {"sum", "count"} and total > 0
    n_groups = len(values)
    top_index = int(np.argmax(values))
    low_index = int(np.argmin(values))
    top_value = float(values[top_index])
    low_value = float(values[low_index])
    gap = top_value - low_value
    runner_up = sorted(values, reverse=True)[1] if n_groups > 1 else None
    lead = (top_value - runner_up) if runner_up is not None else None
    lead_pct = (lead / abs(runner_up)) if lead is not None and runner_up else None
    top3_share = float(values[np.argsort(values)[-3:]].sum() / total) if share_allowed else None
    top_share = top_value / total if share_allowed else None

    def display(value: float | None) -> str:
        if value is None:
            return "—"
        return fmt_percent(value) if unit == "%" else f"{fmt_number(value)}{unit}"

    agg_word = _agg_label(aggregation)
    if aggregation == "sum":
        first_label = f"{metric}合计" if metric else "合计记录数"
        first_value = total
    elif aggregation == "avg":
        first_label = f"{metric}组均值" if metric else "组均值"
        first_value = float(values.mean())
    else:
        first_label = "记录数"
        first_value = float(frame["records"].sum())
    cards = [
        {
            "label": first_label,
            "display": display(first_value),
            "raw": safe_float(first_value),
            "hint": f"{n_groups} 个{group}分组 · {period_text}",
            "tone": "default",
        },
        {
            "label": "排名第一",
            "display": display(top_value),
            "raw": safe_float(top_value),
            "hint": f"{labels[top_index]} · 占比 {fmt_percent(top_share)}" if top_share is not None else labels[top_index],
            "tone": "positive",
        },
        {
            "label": "前三占比" if share_allowed else "有效分组",
            "display": fmt_percent(top3_share) if share_allowed else f"{n_groups} 个",
            "raw": round(top3_share, 6) if top3_share is not None else n_groups,
            "hint": "前三名合计 / 总量" if share_allowed else f"按{group}去重",
            "tone": "default",
        },
        {
            "label": "首尾差距",
            "display": display(gap),
            "raw": safe_float(gap),
            "hint": f"{labels[top_index]} vs {labels[low_index]}",
            "tone": "warning",
        },
    ]

    show = min(int(plan.get("top_n") or 10), 15)
    chart_rows = list(zip(labels[:show], values[:show], records[:show]))
    chart = _chart_base(
        "bar",
        f"各{group}{metric or '记录数'}对比",
        metric or "记录数",
        unit,
        is_percent,
    )
    chart.update(
        {
            "horizontal": True,
            "categories": [label for label, _, _ in chart_rows],
            "series": [{"name": metric or "记录数", "data": [safe_float(value) for _, value, _ in chart_rows]}],
            "max_groups": n_groups,
            "shown_groups": show,
        }
    )

    table_rows = []
    for index, (label, value, record_count) in enumerate(zip(labels[:50], values[:50], records[:50]), start=1):
        share = float(value) / total if share_allowed else None
        table_rows.append(
            {
                "rank": index,
                "label": label,
                "value": safe_float(value),
                "share": round(share, 6) if share is not None else None,
                "records": int(record_count),
            }
        )
    value_label = (
        f"{metric}（{'合计' if aggregation == 'sum' else '组均值'}）"
        if metric
        else "记录数"
    )
    table_columns = [
        {"key": "rank", "label": "排名", "type": "rank"},
        {"key": "label", "label": group, "type": "text"},
        {"key": "value", "label": value_label, "type": "percent" if unit == "%" else "number"},
    ]
    if share_allowed:
        table_columns.append({"key": "share", "label": "占比", "type": "percent"})
    table_columns.append({"key": "records", "label": "记录数", "type": "number"})
    table = _table_from_rows(table_columns, table_rows, total=n_groups)

    facts = [
        f"共 {n_groups} 个{group}分组，统计范围为{period_text}，"
        f"{('组均值' if aggregation == 'avg' else '合计')}为 {display(first_value)}。",
        f"{labels[top_index]} 排名第一，{metric or '记录数'}为 {display(top_value)}"
        + (f"，占总量 {fmt_percent(top_share)}" if top_share is not None else "")
        + "。",
        f"末位是 {labels[low_index]}（{display(low_value)}），首尾相差 {display(gap)}。"
        + (f"前三名合计占比 {fmt_percent(top3_share)}。" if top3_share is not None else ""),
    ]
    if lead is not None and lead_pct is not None:
        facts.append(f"第一名领先第二名 {display(lead)}（{lead_pct * 100:.1f}%）。")

    inferences = [
        "排名反映当前数据口径下的规模差异，未控制规模、地区、渠道等混杂因素，不能直接解释为经营能力差异。",
        (
            "排名基于各分组的平均值，分组内样本量不同可能带来波动，建议结合记录数一起解读。"
            if aggregation == "avg"
            else "占比基于当前筛选范围计算；若数据存在缺失或分类口径不一致，排名可能随之变化。"
        ),
    ]
    suggestions = [
        f"可进一步查看 {labels[top_index]} 与 {labels[low_index]} 的明细差异，核实是真实业务差异还是数据口径问题。",
        "如需更公平的对比，可改用平均值、转化率等归一化指标。",
        "可在问题中补充时间范围或筛选条件，例如“近 6 个月各区域的利润排名”。",
    ]

    return {
        "intent": "compare",
        "intent_label": INTENT_LABELS["compare"],
        "metric": metric or "记录数",
        "unit": unit,
        "aggregation": aggregation,
        "metrics": cards,
        "chart": chart,
        "table": table,
        "facts": facts,
        "inferences": inferences,
        "suggestions": suggestions,
        "stats": {
            "n_groups": n_groups,
            "total": total,
            "top_label": labels[top_index],
            "top_value": top_value,
            "top_share": top_share,
            "low_label": labels[low_index],
            "low_value": low_value,
            "gap": gap,
            "top3_share": top3_share,
        },
        "method": {
            "group_field": group,
            "aggregation": agg_word,
            "period": period_text,
            "offsets": "按分组聚合，降序排名",
            "sql": sql,
        },
    }


def _trend(
    source: str,
    plan: dict,
    sheet: dict,
    columns: dict[str, dict],
    filters: list[str],
    metric: str | None,
    unit: str,
    is_percent: bool,
    aggregation: str,
) -> dict:
    time_column = plan["time_field"]
    granularity = plan.get("granularity") or "month"
    # 周期起点依赖筛选后的最大日期，先取边界再拼接
    _, max_date = _bounds(source, time_column, filters)
    if max_date is None:
        raise AnalysisError("日期字段没有有效值，无法进行趋势分析。")
    date_clause, start_label = _time_filter(time_column, plan, max_date)

    def build(gran: str) -> str:
        conditions = [f"{quote_ident(time_column)} IS NOT NULL", *filters]
        if metric and aggregation != "count":
            conditions.append(f"{quote_ident(metric)} IS NOT NULL")
        if date_clause:
            conditions.append(date_clause)
        bucket = _bucket_expr(time_column, gran)
        metric_expr = _metric_expr(metric, aggregation)
        return (
            f"SELECT {bucket} AS period, {metric_expr} AS value, count(*) AS records "
            f"FROM {source} WHERE {' AND '.join(conditions)} GROUP BY 1 ORDER BY 1"
        )

    sql = build(granularity)
    frame = _run(sql)
    if frame.empty:
        raise AnalysisError("当前筛选条件下没有可分析的数据，请检查日期与指标字段是否有效。")
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame.dropna(subset=["period"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["value"])
    if frame.empty:
        raise AnalysisError("聚合结果为空，请检查指标字段。")

    if granularity in {"day", "week"} and len(frame) > 400:
        granularity = "month"
        sql = build(granularity)
        frame = _run(sql)
        frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.dropna(subset=["period", "value"])
        plan = {**plan, "granularity": granularity}

    periods = [pd.Timestamp(value) for value in frame["period"].tolist()]
    labels = [_bucket_label(value, granularity) for value in periods]
    values = frame["value"].to_numpy(dtype=float)
    records = frame["records"].astype(int).tolist()
    metric_cards, stats = _metrics_from_trend(
        labels, values, metric or "记录数", unit, aggregation, granularity, is_percent
    )
    direction, normalized = _trend_direction(values)
    actual_start = labels[0] if labels else start_label
    actual_end = labels[-1] if labels else None

    chart = _chart_base(
        "line",
        f"{ {'day': '每日', 'week': '每周', 'month': '每月', 'quarter': '每季度', 'year': '每年'}.get(granularity, '分期')}{metric or '记录数'}趋势",
        metric or "记录数",
        unit,
        is_percent,
    )
    chart.update(
        {
            "categories": labels,
            "series": [{"name": metric or "记录数", "data": [safe_float(value) for value in values]}],
            "granularity": granularity,
        }
    )

    table_rows = [
        {
            "period": label,
            "value": safe_float(value),
            "records": int(record_count),
            "change": round((value - values[index - 1]) / abs(values[index - 1]), 6)
            if index > 0 and values[index - 1] != 0
            else None,
        }
        for index, (label, value, record_count) in enumerate(zip(labels, values, records))
    ]
    table = _table_from_rows(
        [
            {"key": "period", "label": GRANULARITY_LABELS.get(granularity, "周期"), "type": "text"},
            {"key": "value", "label": f"{metric or '记录数'}（{_agg_label(aggregation)}）", "type": "percent" if unit == "%" else "number"},
            {"key": "change", "label": "环比", "type": "percent"},
            {"key": "records", "label": "记录数", "type": "number"},
        ],
        table_rows,
    )

    facts = [
        f"统计区间为 {actual_start} 至 {actual_end}，共 {len(values)} 个{GRANULARITY_LABELS.get(granularity, '周期')}数据点。",
        f"{_summary_label(metric, aggregation)}为 "
        f"{_display_value(stats['average'] if aggregation == 'avg' else stats['total'], unit)}，"
        f"期间均值为 {_display_value(stats['average'], unit)}。",
        f"峰值出现在 {stats['peak_label']}（{_display_value(stats['peak'], unit)}），谷值出现在 {stats['low_label']}（{_display_value(stats['low'], unit)}）。",
    ]
    if stats["change"] is not None:
        facts.append(
            f"最新一期 {stats['last_label']} 为 {_display_value(stats['last'], unit)}，较上一期"
            f"{'上升' if stats['change'] > 0 else ('下降' if stats['change'] < 0 else '持平')} "
            f"{abs(stats['change']) * 100:.1f}%。"
        )
    facts.append(f"以首尾窗口中位数对比衡量，区间整体呈{direction}趋势（变化 {normalized * 100:+.1f}%）。")

    inferences = [
        f"从历史数据看，指标整体呈{direction}态势；该判断仅描述当前区间，不构成对未来走势的预测。",
        "峰值与谷值可能受促销、季节性或一次性大额订单影响，需结合业务事件核实。",
    ]
    suggestions = [
        "可继续追问“近 6 个月按区域拆分的趋势”，定位增长或下滑的主要来源。",
        "补充同比数据或关键活动日历，有助于区分季节性波动与结构性变化。",
        "若需要更平滑的趋势，可要求按季度聚合或使用移动平均。",
    ]

    return {
        "intent": "trend",
        "intent_label": INTENT_LABELS["trend"],
        "metric": metric or "记录数",
        "unit": unit,
        "aggregation": aggregation,
        "granularity": granularity,
        "metrics": metric_cards,
        "chart": chart,
        "table": table,
        "facts": facts,
        "inferences": inferences,
        "suggestions": suggestions,
        "stats": {**stats, "direction": direction, "normalized_slope": normalized},
        "dates": {"start": actual_start, "end": actual_end},
        "method": {
            "time_field": time_column,
            "granularity": GRANULARITY_LABELS.get(granularity, "月"),
            "aggregation": _agg_label(aggregation),
            "period": f"近 {plan.get('period_value')}{GRANULARITY_LABELS.get(str(plan.get('period_unit')), '月')}"
            if plan.get("period_value")
            else "全部数据",
            "sql": sql,
        },
    }


def _robust_scores(values: np.ndarray) -> tuple[np.ndarray, str, float, float]:
    """返回 (Z 分数数组, 判定方法, 阈值, 中位数)。MAD 为 0 时回退 IQR。"""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad > 1e-12:
        return 0.6745 * (values - median) / mad, "MAD", 3.5, median
    q1, q3 = np.percentile(values, [25, 75])
    iqr = float(q3 - q1)
    if iqr <= 1e-12:
        return np.zeros(len(values)), "FLAT", 0.0, median
    # (value - median) / IQR 的绝对值 ≥ 2 等价于越过 Q1−1.5×IQR 或 Q3+1.5×IQR
    return (values - median) / iqr, "IQR", 2.0, median


def _detect_anomalies(values: np.ndarray, labels: list[str], granularity: str = "month") -> dict:
    """双重口径异常检测：原始序列 + 去趋势残差，任一口径越阈值即为异常。

    1. 整体水平：直接对聚合序列计算稳健 Z 分数，适合平稳序列的单点尖峰。
    2. 去趋势残差：对线性拟合后的残差计算稳健 Z 分数，避免增长/下滑趋势
       抬高整体离散度、把季节性极值"洗白"的问题。
    3. 月度序列累计 ≥ 36 个月（每年同月 ≥ 3 个样本）时，在残差口径上
       叠加月度季节修正。
    """
    count = len(values)
    if count < 4 or float(np.nanstd(values)) == 0:
        return {
            "anomalies": [],
            "method": "样本不足或数值无波动，未执行异常检测",
            "threshold": 0.0,
            "scores": np.zeros(count),
            "passes": [],
        }

    overall_median = float(np.median(values))
    passes: list[dict] = []

    raw_scores, raw_kind, raw_threshold, _ = _robust_scores(values)
    if raw_kind != "FLAT":
        passes.append(
            {
                "name": "原始序列（整体水平）",
                "short": "原始序列",
                "kind": raw_kind,
                "threshold": raw_threshold,
                "scores": raw_scores,
                "baseline": np.full(count, overall_median),
            }
        )

    if count >= 8:
        x = np.arange(count, dtype=float)
        try:
            slope, intercept = np.polyfit(x, values, 1)
            fitted = slope * x + intercept
        except Exception:  # pragma: no cover - 奇异输入兜底
            fitted = np.full(count, overall_median)
        residual = values - fitted
        seasonal_note = ""
        if granularity == "month" and count >= 36:
            months: list[int | None] = []
            for label in labels:
                try:
                    months.append(int(str(label).split("-")[1]))
                except (ValueError, IndexError, TypeError):
                    months.append(None)
            if None not in months and len(set(months)) == 12:
                offsets = residual.copy()
                seasonal = np.zeros(count)
                for month in range(1, 13):
                    idx = np.array([i for i, m in enumerate(months) if m == month])
                    if len(idx) >= 3:
                        seasonal[idx] = float(np.median(offsets[idx]))
                if np.any(np.abs(seasonal) > 0):
                    fitted = fitted + seasonal
                    residual = values - fitted
                    seasonal_note = "，已叠加月度季节修正"
        res_scores, res_kind, res_threshold, _ = _robust_scores(residual)
        if res_kind not in {"FLAT"} and float(np.nanstd(residual)) > 0:
            passes.append(
                {
                    "name": f"去趋势残差（线性拟合{seasonal_note}）",
                    "short": "去趋势残差",
                    "kind": res_kind,
                    "threshold": res_threshold,
                    "scores": res_scores,
                    "baseline": fitted,
                }
            )

    if not passes:
        return {
            "anomalies": [],
            "method": "数据波动过小，未发现异常",
            "threshold": 0.0,
            "scores": np.zeros(count),
            "passes": [],
        }

    flags = np.zeros(count, dtype=bool)
    for item in passes:
        flags |= np.abs(item["scores"]) >= item["threshold"]

    signed_scores = np.zeros(count)
    for index in range(count):
        best = max(passes, key=lambda p: abs(float(p["scores"][index])))
        signed_scores[index] = float(best["scores"][index])

    threshold = max(item["threshold"] for item in passes)
    if any(item["kind"] == "MAD" for item in passes) and any(item["kind"] == "IQR" for item in passes):
        method_text = (
            "双重口径（原始序列 + 去趋势残差，含 IQR 兜底），任一口径超出阈值即判定为异常"
        )
    elif len(passes) > 1:
        method_text = (
            "双重口径：原始序列与去趋势残差"
            + ("已叠加月度季节修正" if seasonal_note else "")
            + "分别计算稳健 Z 分数，任一 |Z| ≥ 3.5 即判定为异常"
        )
    else:
        only = passes[0]
        if only["kind"] == "MAD":
            method_text = f"稳健 Z 分数（基于中位数与 MAD，适用于{only['short']}），|Z| ≥ 3.5 判定为异常"
        else:
            method_text = "IQR 箱线图法（MAD 为 0 时兜底），超出 Q1−1.5×IQR ~ Q3+1.5×IQR（|Z| ≥ 2）判定为异常"

    anomalies: list[dict] = []
    for index in np.where(flags)[0]:
        index_int = int(index)
        best = max(passes, key=lambda p: abs(float(p["scores"][index_int])))
        value = float(values[index_int])
        deviation = (value - overall_median) / abs(overall_median) if overall_median != 0 else None
        baseline_value = float(best["baseline"][index_int])
        anomalies.append(
            {
                "index": index_int,
                "label": labels[index_int],
                "value": safe_float(value),
                "score": round(float(best["scores"][index_int]), 3),
                "raw_z": round(float(raw_scores[index_int]), 3) if raw_kind != "FLAT" else None,
                "residual_z": (
                    round(float(passes[-1]["scores"][index_int]), 3) if len(passes) > 1 else None
                ),
                "basis": best["short"],
                "baseline": safe_float(baseline_value),
                "deviation": round(deviation, 6) if deviation is not None else None,
                "direction": "高于" if value >= baseline_value else "低于",
                "median": overall_median,
            }
        )
    anomalies.sort(key=lambda item: abs(item["score"]), reverse=True)
    return {
        "anomalies": anomalies,
        "method": method_text,
        "threshold": threshold,
        "scores": signed_scores,
        "passes": [{k: v for k, v in item.items() if k not in {"scores", "baseline", "kind"}} for item in passes],
    }


def _anomaly(
    source: str,
    plan: dict,
    sheet: dict,
    columns: dict[str, dict],
    filters: list[str],
    metric: str | None,
    unit: str,
    is_percent: bool,
    aggregation: str,
) -> dict:
    trend = _trend(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
    labels = trend["chart"]["categories"]
    values = np.array(trend["chart"]["series"][0]["data"], dtype=float)
    detection = _detect_anomalies(values, labels, trend.get("granularity", "month"))
    anomalies = detection["anomalies"]
    method_text = detection["method"]
    threshold = detection["threshold"]
    scores = detection["scores"]

    trend["intent"] = "anomaly"
    trend["intent_label"] = INTENT_LABELS["anomaly"]
    trend["chart"]["type"] = "line_anomaly"
    trend["chart"]["anomalies"] = [
        {
            "index": item["index"],
            "label": item["label"],
            "value": item["value"],
            "score": item["score"],
            "direction": item["direction"],
        }
        for item in anomalies
    ]
    trend["chart"]["threshold"] = threshold
    trend["chart"]["method"] = method_text

    flags = np.zeros(len(values), dtype=bool)
    for item in anomalies:
        flags[item["index"]] = True
    table_rows = []
    for index, (label, value) in enumerate(zip(labels, values)):
        table_rows.append(
            {
                "period": label,
                "value": safe_float(value),
                "zscore": round(float(scores[index]), 3),
                "deviation": round(float((value - np.median(values)) / abs(np.median(values))), 6)
                if np.median(values) != 0
                else None,
                "status": "异常" if flags[index] else "正常",
            }
        )
    trend["table"] = _table_from_rows(
        [
            {"key": "period", "label": trend["method"]["granularity"], "type": "text"},
            {"key": "value", "label": f"{metric or '记录数'}（{_agg_label(aggregation)}）", "type": "percent" if unit == "%" else "number"},
            {"key": "zscore", "label": "稳健 Z 分数", "type": "number"},
            {"key": "deviation", "label": "偏离中位数", "type": "percent"},
            {"key": "status", "label": "判定", "type": "badge"},
        ],
        table_rows,
    )

    n_anomalies = len(anomalies)
    average = float(values.mean())
    span = (float(values.max()) - float(values.min())) / abs(average) if average != 0 else None
    cards = [
        {
            "label": "识别异常点",
            "display": f"{n_anomalies} 个",
            "raw": n_anomalies,
            "hint": f"|Z| ≥ {threshold:g} · {len(values)} 个周期",
            "tone": "warning" if n_anomalies else "default",
        },
        {
            "label": "最大偏离",
            "display": _display_value(anomalies[0]["value"], unit) if anomalies else "—",
            "raw": anomalies[0]["value"] if anomalies else None,
            "hint": (
                f"{anomalies[0]['label']} · {anomalies[0]['basis']} Z={anomalies[0]['score']:+.2f}"
                if anomalies
                else "未发现显著异常"
            ),
            "tone": "warning" if anomalies else "default",
        },
        {
            "label": "期间均值",
            "display": _display_value(average, unit),
            "raw": safe_float(average),
            "hint": f"{len(values)} 个周期",
            "tone": "default",
        },
        {
            "label": "波动幅度",
            "display": fmt_percent(span) if span is not None else "—",
            "raw": round(span, 6) if span is not None else None,
            "hint": "（最大值 − 最小值）/ 均值",
            "tone": "default",
        },
    ]

    facts = [
        f"判定方法：{method_text}。",
        f"统计区间为 {labels[0]} 至 {labels[-1]}，共 {len(values)} 个周期。",
    ]
    if anomalies:
        strongest = anomalies[0]
        basis_label = "拟合基准" if strongest.get("basis") == "去趋势残差" else "整体中位数"
        facts.append(
            f"共识别 {n_anomalies} 个异常点，偏离最大的是 {strongest['label']}："
            f"值 {_display_value(strongest['value'], unit)}，{strongest['direction']}{basis_label} {_display_value(strongest['baseline'], unit)}"
            + (f"，偏离 {abs(strongest['deviation']) * 100:.1f}%" if strongest["deviation"] is not None else "")
            + f"，{strongest['basis']}口径 Z={strongest['score']:+.2f}。"
        )
        if n_anomalies > 1:
            others = "、".join(item["label"] for item in anomalies[1:4])
            facts.append(f"其余异常点：{others}。")
    else:
        facts.append("按当前口径未发现单点显著异常。")
        if span is not None and span >= 0.5:
            facts.append(f"区间最大值与最小值差异为 {fmt_percent(span)}（相对均值），波动较大但未被判定为单点离群。")

    inferences = [
        "异常可能来自大额订单、促销活动、口径变更或数据录入问题；本系统只做统计识别，不判断因果。",
        "单一口径的 Z 分数对极端值不敏感；双重口径下若仍无异常，说明当前波动更像趋势或季节形态变化，而不是个别离群周期。",
    ]
    if not anomalies and span is not None and span >= 0.5:
        inferences.append(
            f"波动幅度达 {fmt_percent(span)}，但未检出单点离群，说明波动更可能来自整体趋势或季节形态，而非个别异常周期。"
        )
    if anomalies and all(item["basis"] == "去趋势残差" for item in anomalies):
        inferences.append("本次异常点均来自去趋势残差口径，说明它们偏离的是趋势形态，而不只是整段数据的高波动。")
    trend["metrics"] = cards
    trend["facts"] = facts
    trend["inferences"] = inferences
    trend["suggestions"] = [
        "建议核查异常周期内的订单明细、退款与促销记录，确认异常是否为真实业务事件。",
        "如已知活动日期，可在问题中限定范围后重新分析，比较活动前后变化。",
        "若数据存在缺失值或口径调整，建议先补齐数据再判断异常。",
    ]
    trend["anomalies"] = [
        {
            "label": item["label"],
            "value": item["value"],
            "score": item["score"],
            "deviation": item["deviation"],
            "direction": item["direction"],
        }
        for item in anomalies
    ]
    trend["method"]["detection"] = method_text
    trend["method"]["threshold"] = threshold
    return trend


def _frequency_summary(
    source: str,
    sheet: dict,
    columns: dict[str, dict],
    filters: list[str],
    plan: dict,
) -> dict:
    candidates = [
        column
        for column in sheet["columns"]
        if column["dtype"] in {"category", "text"}
        and column.get("role") != "id"
        and 2 <= column.get("unique", 0) <= 60
    ]
    conditions = [*filters]
    condition = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    total_frame = _run(f"SELECT count(*) AS n FROM {source}{condition}")
    total_records = int(total_frame.iloc[0]["n"]) if not total_frame.empty else 0
    if total_records == 0:
        raise AnalysisError("当前工作表没有数据。")

    chart = _chart_base("bar", "分类记录数分布", "记录数", "条", False)
    table = _table_from_rows([], [])
    group = candidates[0]["name"] if candidates else None
    top_label = "—"
    top_count = None
    if group:
        sql = (
            f"SELECT CAST({quote_ident(group)} AS VARCHAR) AS label, count(*) AS value "
            f"FROM {source}{condition} GROUP BY 1 ORDER BY value DESC LIMIT 15"
        )
        frame = _run(sql)
        frame = frame.dropna(subset=["label"])
        labels = [str(value) for value in frame["label"].tolist()]
        values = [int(value) for value in frame["value"].tolist()]
        total = sum(values) or 1
        chart.update(
            {
                "horizontal": True,
                "categories": labels,
                "series": [{"name": "记录数", "data": values}],
                "max_groups": len(labels),
            }
        )
        table = _table_from_rows(
            [
                {"key": "label", "label": group, "type": "text"},
                {"key": "value", "label": "记录数", "type": "number"},
                {"key": "share", "label": "占比", "type": "percent"},
            ],
            [
                {"label": label, "value": value, "share": round(value / total, 6)}
                for label, value in zip(labels, values)
            ],
        )
        if labels:
            top_label = labels[0]
            top_count = values[0]

    cards = [
        {"label": "记录数", "display": f"{total_records:,} 条", "raw": total_records, "hint": f"{sheet['name']}", "tone": "default"},
        {"label": "字段数", "display": f"{len(columns)} 个", "raw": len(columns), "hint": "已识别字段", "tone": "default"},
        {
            "label": "分类字段",
            "display": group or "—",
            "raw": None,
            "hint": f"{columns[group]['unique']} 个取值" if group else "无适合分类的字段",
            "tone": "default",
        },
        {
            "label": "最多分类",
            "display": top_label,
            "raw": top_count,
            "hint": f"{top_count:,} 条记录" if top_count is not None else "—",
            "tone": "default",
        },
    ]
    facts = [f"当前筛选范围内共 {total_records:,} 条记录、{len(columns)} 个字段。"]
    if group and top_count is not None:
        facts.append(f"分类字段「{group}」中，「{top_label}」记录数最多，为 {top_count:,} 条。")
    facts.append("本次为常规数据查询，未执行趋势或异常检测。")

    return {
        "intent": "query",
        "intent_label": INTENT_LABELS["query"],
        "metric": "记录数",
        "unit": "条",
        "aggregation": "count",
        "metrics": cards,
        "chart": chart,
        "table": table,
        "facts": facts,
        "inferences": ["查询结果只反映已上传数据的当前范围，缺失或重复数据会影响统计结果。"],
        "suggestions": [
            "可进一步指定时间范围、指标或分组字段，例如“各区域的销售额排名”。",
            "如需趋势或异常识别，请在问题中明确时间字段与指标。",
        ],
        "stats": {"records": total_records, "groups": len(columns)},
        "method": {
            "aggregation": "计数",
            "group_field": group,
            "sql": (
                f"SELECT CAST({quote_ident(group)} AS VARCHAR) AS label, count(*) AS value "
                f"FROM {source}{condition} GROUP BY 1 ORDER BY value DESC LIMIT 15"
                if group
                else f"SELECT count(*) AS n FROM {source}{condition}"
            ),
        },
    }


def compute(question: str, plan: dict, sheet: dict) -> dict:
    """执行分析并返回所有由真实数据计算出的结果。"""
    if not sheet.get("parquet_path"):
        raise AnalysisError("该工作表尚未完成解析，请重新上传文件。")
    source = _source(sheet["parquet_path"])
    columns = {column["name"]: column for column in sheet["columns"]}

    metric = plan.get("metric_field")
    if metric and metric not in columns:
        metric = None
        plan = {**plan, "metric_field": None, "aggregation": "count"}
    aggregation = plan.get("aggregation") or "sum"
    if aggregation != "count" and not metric:
        aggregation = "count"
    if metric:
        meta = columns[metric]
        if meta["dtype"] != "number":
            metric = None
            aggregation = "count"
        if meta.get("is_percent") and aggregation == "sum":
            aggregation = "avg"

    unit = infer_unit(metric, bool(metric and columns[metric].get("is_percent")))
    is_percent = unit == "%"
    filters = _filters_sql(plan.get("filters") or [], columns)
    intent = plan.get("intent", "query")
    warnings: list[str] = []
    if plan.get("aggregation") == "sum" and aggregation == "avg" and metric:
        warnings.append(f"「{metric}」为比例字段，已自动改用平均值聚合。")
    if not metric and aggregation == "count":
        warnings.append("未选择数值指标，本次按记录数统计。")

    if intent == "compare" and plan.get("group_field") in columns:
        result = _compare(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
    elif intent == "anomaly" and plan.get("time_field") in columns:
        result = _anomaly(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
    elif intent == "trend" and plan.get("time_field") in columns:
        result = _trend(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
    elif intent == "query":
        if plan.get("group_field") in columns and metric:
            result = _compare(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
            result["intent"] = "query"
            result["intent_label"] = INTENT_LABELS["query"]
        elif plan.get("time_field") in columns and metric:
            result = _trend(source, plan, sheet, columns, filters, metric, unit, is_percent, aggregation)
            result["intent"] = "query"
            result["intent_label"] = INTENT_LABELS["query"]
        else:
            result = _frequency_summary(source, sheet, columns, filters, plan)
    else:
        result = _frequency_summary(source, sheet, columns, filters, plan)
        result["intent"] = "query"
        result["intent_label"] = INTENT_LABELS["query"]

    if plan.get("group_field") in columns and intent == "compare":
        result["method"]["group_field"] = plan["group_field"]

    result["warnings"] = warnings
    result["plan"] = plan
    result["sheet"] = {"id": sheet["id"], "name": sheet["name"], "row_count": sheet["row_count"]}
    result["metric"] = result.get("metric") or metric or "记录数"
    result["unit"] = result.get("unit", unit)
    return result


def build_methodology(result: dict, sheet: dict, plan: dict) -> dict:
    method = dict(result.get("method") or {})
    metric = result.get("metric") or "记录数"
    aggregation = _agg_label(plan.get("aggregation") or "sum")
    notes: list[str] = [
        "所有指标、图表与数据明细均由本地 DuckDB 对上传文件执行只读聚合得出，模型不直接生成数字。",
        "仅访问当前上传工作表的本地 Parquet 数据，不执行写入、删除或系统命令。",
        "结论区分“数据事实”与“推测/建议”，不包含预测或因果判断。",
    ]
    if plan.get("filters"):
        notes.append("已应用用户/模型识别的筛选条件，筛选值会写入 SQL 并在下方展示。")
    if plan.get("period_value"):
        notes.append("时间范围为相对数据中最新日期的滚动窗口，而非自然日历的当前日期。")
    method.update(
        {
            "engine": "DuckDB 只读查询 · 本地 Parquet",
            "sheet": sheet["name"],
            "rows": sheet["row_count"],
            "metric": metric,
            "aggregation": aggregation,
            "filters": plan.get("filters") or [],
            "notes": notes,
        }
    )
    return method
