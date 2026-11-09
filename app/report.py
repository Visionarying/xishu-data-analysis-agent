"""一键分析报告：Markdown（可归档）与可打印 HTML（浏览器另存为 PDF）。"""

from __future__ import annotations

import html
from typing import Any

from .config import APP_VERSION

METHOD_LABELS = {
    "month": "月",
    "quarter": "季度",
    "year": "年",
    "week": "周",
    "day": "日",
}


def _fmt_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(number) >= 1e8:
        return f"{number / 1e8:.2f} 亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:.2f} 万"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _metric_rows(result: dict) -> list[tuple[str, str, str]]:
    return [
        (str(item.get("label", "")), str(item.get("display", "")), str(item.get("hint", "")))
        for item in result.get("metrics") or []
    ]


def _chart_rows(result: dict) -> tuple[list[str], list[list[Any]], str]:
    chart = result.get("chart") or {}
    categories = chart.get("categories") or []
    series = chart.get("series") or []
    values = (series[0] or {}).get("data") if series else []
    return categories, [[categories[index], values[index] if index < len(values) else None] for index in range(len(categories))], str(chart.get("title") or "可视化结果")


def _method_rows(result: dict) -> list[tuple[str, str]]:
    method = result.get("method") or {}
    sheet = result.get("sheet") or {}
    filters = "；".join(
        f"{item.get('field')} {item.get('op')} {item.get('value')}" for item in method.get("filters") or []
    )
    return [
        ("工作表", f"{sheet.get('name', '')} · {method.get('rows', 0)} 行"),
        ("分析类型", str(result.get("intent_label") or "分析")),
        ("指标口径", f"{method.get('metric') or result.get('metric') or '记录数'} · {method.get('aggregation', '')}"),
        (
            "时间口径",
            f"{method.get('time_field')}（按{METHOD_LABELS.get(method.get('granularity', ''), method.get('granularity', ''))}）"
            if method.get("time_field")
            else str(method.get("period") or "全部数据"),
        ),
        ("对比维度", str(method.get("group_field") or "—")),
        ("筛选条件", filters or "无"),
    ]


def _detail_table(result: dict, limit: int = 200) -> tuple[list[str], list[list[str]]]:
    table = result.get("table") or {}
    columns = table.get("columns") or []
    rows = (table.get("rows") or [])[:limit]
    headers = [str(column.get("label", column.get("key", ""))) for column in columns]
    body: list[list[str]] = []
    for row in rows:
        line: list[str] = []
        for column in columns:
            value = row.get(column.get("key"))
            if value is None:
                line.append("—")
            elif column.get("type") == "percent":
                try:
                    line.append(f"{float(value) * 100:.1f}%")
                except (TypeError, ValueError):
                    line.append(str(value))
            elif column.get("type") == "number":
                line.append(_fmt_number(value))
            else:
                line.append(str(value))
        body.append(line)
    return headers, body


def build_markdown(result: dict) -> str:
    meta = result.get("meta") or {}
    detail = result.get("detail") or {}
    method = result.get("method") or {}
    lines: list[str] = [
        "# 数据分析报告",
        "",
        f"> 问题：{result.get('question', '')}",
        f"> 生成时间：{meta.get('created_at', '')} · 析数 v{APP_VERSION}",
        "",
        "## 核心结论",
        "",
        str(result.get("one_liner") or "分析完成"),
        "",
        "## 关键指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "| --- | --- | --- |",
    ]
    for label, display, hint in _metric_rows(result):
        lines.append(f"| {label} | {display} | {hint} |")

    categories, chart_rows, chart_title = _chart_rows(result)
    chart = result.get("chart") or {}
    if categories:
        lines.extend(["", "## 图表数据", "", f"**{chart_title}**", "", f"| 类别 | {chart.get('metric') or '数值'} |", "| --- | --- |"])
        for category, value in chart_rows:
            lines.append(f"| {category} | {_fmt_number(value)} |")

    lines.extend(["", "## 数据事实", ""])
    for item in detail.get("facts") or []:
        lines.append(f"- {item}")

    lines.extend(["", "## 推测与建议", ""])
    for item in detail.get("inferences") or []:
        lines.append(f"- {item}")
    if detail.get("suggestions"):
        lines.extend(["", "### 下一步建议", ""])
        for item in detail["suggestions"]:
            lines.append(f"- {item}")

    lines.extend(["", "## 分析口径", "", "| 项目 | 内容 |", "| --- | --- |"])
    for key, value in _method_rows(result):
        lines.append(f"| {key} | {value} |")
    for note in method.get("notes") or []:
        lines.append(f"- {note}")

    if method.get("sql"):
        lines.extend(["", "```sql", str(method["sql"]), "```"])

    headers, body = _detail_table(result)
    if headers:
        lines.extend(["", "## 数据明细（最多 200 行）", ""])
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in body:
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")

    lines.extend(
        [
            "",
            "---",
            "",
            f"本报告由析数 · 数据分析 Agent v{APP_VERSION} 生成；所有数字来自本地只读查询，可回到应用核对。",
            "",
        ]
    )
    return "\n".join(lines)


def build_html(result: dict) -> str:
    meta = result.get("meta") or {}
    detail = result.get("detail") or {}
    method = result.get("method") or {}
    title = f"数据分析报告 · {result.get('question', '')}"

    def rows_html(rows: list[list[Any]]) -> str:
        return "\n".join(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows
        )

    metrics_html = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td class=\"num\">{html.escape(display)}</td><td>{html.escape(hint)}</td></tr>"
        for label, display, hint in _metric_rows(result)
    )

    categories, chart_rows, chart_title = _chart_rows(result)
    chart = result.get("chart") or {}
    chart_rows_html = ""
    if categories:
        chart_rows_html = f"""
        <h2>{html.escape(chart_title)}</h2>
        <table><thead><tr><th>类别</th><th class="num">{html.escape(str(chart.get('metric') or '数值'))}</th></tr></thead>
        <tbody>{''.join(f"<tr><td>{html.escape(str(c))}</td><td class='num'>{html.escape(_fmt_number(v))}</td></tr>" for c, v in chart_rows)}</tbody></table>
        """

    facts_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in detail.get("facts") or [])
    inferences_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in detail.get("inferences") or [])
    suggestions_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in detail.get("suggestions") or [])
    method_html = "\n".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(value)}</td></tr>" for key, value in _method_rows(result)
    )
    sql_html = f"<pre class='sql'>{html.escape(str(method['sql']))}</pre>" if method.get("sql") else ""
    headers, body = _detail_table(result)
    detail_html = ""
    if headers:
        detail_html = f"""
        <h2>数据明细（最多 200 行）</h2>
        <table><thead><tr>{''.join(f"<th>{html.escape(h)}</th>" for h in headers)}</tr></thead>
        <tbody>{rows_html(body)}</tbody></table>
        """

    metrics_rows = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td class='num'>{html.escape(display)}</td><td>{html.escape(hint)}</td></tr>"
        for label, display, hint in _metric_rows(result)
    )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; color: #1f2937; margin: 0; padding: 34px 40px; background: #fff; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; }}
  h2 {{ font-size: 16px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #eaecf0; }}
  .sub {{ color: #667085; font-size: 12px; margin-bottom: 4px; }}
  .liner {{ background: #f5f4ff; border-radius: 10px; padding: 16px 18px; font-size: 15px; line-height: 1.7; margin: 14px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0 4px; }}
  th, td {{ border: 1px solid #e4e7ec; padding: 7px 9px; text-align: left; vertical-align: top; }}
  th {{ background: #f9fafb; font-weight: 600; }}
  td.num {{ text-align: right; white-space: nowrap; }}
  ul {{ margin: 6px 0; padding-left: 20px; font-size: 13px; line-height: 1.8; }}
  pre.sql {{ background: #111827; color: #e5e7eb; padding: 12px 14px; border-radius: 8px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; }}
  .foot {{ margin-top: 28px; color: #98a2b3; font-size: 11px; border-top: 1px solid #eaecf0; padding-top: 12px; }}
  .hint {{ font-size: 11px; color: #98a2b3; margin-top: 4px; }}
  @media print {{ body {{ padding: 0; }} .hint {{ display: none; }} h2 {{ break-after: avoid; }} tr {{ break-inside: avoid; }} }}
</style></head>
<body>
<h1>数据分析报告</h1>
<div class="sub">问题：{html.escape(result.get('question', ''))}</div>
<div class="sub">生成时间：{html.escape(meta.get('created_at', ''))} · 析数 v{APP_VERSION}</div>
<div class="hint">打印或另存为 PDF：按 Ctrl + P（Mac 为 ⌘ + P）</div>
<div class="liner">{html.escape(str(result.get('one_liner') or '分析完成'))}</div>
<h2>关键指标</h2>
<table><thead><tr><th>指标</th><th class="num">数值</th><th>说明</th></tr></thead><tbody>{metrics_rows}</tbody></table>
{chart_rows_html}
<h2>数据事实</h2><ul>{facts_html}</ul>
<h2>推测与建议</h2><ul>{inferences_html}</ul>
{f'<h2>下一步建议</h2><ul>{suggestions_html}</ul>' if suggestions_html else ''}
<h2>分析口径</h2>
<table><tbody>{method_html}</tbody></table>
{sql_html}
{detail_html}
<div class="foot">本报告由析数 · 数据分析 Agent v{APP_VERSION} 生成；所有数字来自本地只读查询，可回到应用核对。</div>
</body></html>"""
