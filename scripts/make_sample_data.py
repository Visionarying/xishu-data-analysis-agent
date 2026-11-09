"""生成用于演示和验收的多工作表 Excel 示例数据。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT = BASE_DIR / "samples" / "示例销售数据.xlsx"

REGIONS = {
    "华东": ["上海", "江苏", "浙江", "安徽"],
    "华南": ["广东", "福建", "广西"],
    "华北": ["北京", "天津", "河北"],
    "西南": ["四川", "重庆", "云南"],
    "华中": ["湖北", "湖南", "河南"],
    "东北": ["辽宁", "吉林", "黑龙江"],
}
REGION_WEIGHTS = {"华东": 0.30, "华南": 0.22, "华北": 0.18, "西南": 0.12, "华中": 0.11, "东北": 0.07}

PRODUCTS = {
    "软件订阅": [("企业版年费", 6800), ("专业版年费", 3200), ("基础版年费", 1200)],
    "硬件设备": [("智能终端 Pro", 4500), ("智能终端 Lite", 2200), ("边缘网关", 8600)],
    "咨询服务": [("数据治理咨询", 32000), ("流程优化咨询", 26000), ("架构设计咨询", 38000)],
    "培训服务": [("数据分析训练营", 5800), ("管理驾驶舱工作坊", 4200), ("BI 认证课程", 2600)],
}
CHANNELS = ["直销", "渠道", "线上"]
CHANNEL_WEIGHTS = [0.48, 0.34, 0.18]


def build_sales() -> pd.DataFrame:
    rng = np.random.default_rng(20261031)
    rows: list[dict] = []
    start = date(2024, 10, 1)
    end = date(2026, 9, 30)

    month_index = 0
    cursor = start
    while cursor <= end:
        month_start = cursor
        next_month = (pd.Timestamp(month_start) + pd.offsets.MonthBegin(1)).date()
        month_days = (next_month - month_start).days
        month_key = month_start.strftime("%Y-%m")
        growth = 1 + 0.012 * month_index
        season = 1.0
        if month_start.month in (11, 12):
            season = 1.22
        elif month_start.month in (1, 2):
            season = 0.82
        elif month_start.month in (6, 7):
            season = 1.08

        # 构造可被异常检测识别的业务事件
        event = 1.0
        if month_key == "2025-11":
            event = 2.15
        elif month_key == "2026-04":
            event = 0.48
        elif month_key == "2025-03":
            event = 1.62

        for region, weight in REGION_WEIGHTS.items():
            transaction_count = max(5, int(round(month_days * 1.45 * weight)))
            for _ in range(transaction_count):
                category = rng.choice(list(PRODUCTS.keys()), p=[0.38, 0.27, 0.16, 0.19])
                product, price = PRODUCTS[category][rng.integers(0, len(PRODUCTS[category]))]
                day_offset = int(rng.integers(0, min(month_days, 28)))
                order_date = pd.Timestamp(month_start) + pd.Timedelta(days=day_offset)
                quantity = int(rng.integers(1, 9))
                if category == "咨询服务":
                    quantity = int(rng.integers(1, 3))
                discount = float(rng.choice([1.0, 1.0, 1.0, 0.95, 0.9]))
                amount = price * quantity * discount * growth * season * event
                amount *= float(rng.normal(1.0, 0.05))
                margin = float(rng.normal(0.31 if category != "硬件设备" else 0.18, 0.035))
                profit = amount * margin
                channel = str(rng.choice(CHANNELS, p=CHANNEL_WEIGHTS))
                rows.append(
                    {
                        "订单日期": order_date,
                        "区域": region,
                        "省份": REGIONS[region][int(rng.integers(0, len(REGIONS[region])))],
                        "产品类别": category,
                        "产品名称": product,
                        "销售渠道": channel,
                        "销量": quantity,
                        "销售额": round(amount, 2),
                        "利润": round(profit, 2),
                    }
                )
        cursor = next_month
        month_index += 1

    frame = pd.DataFrame(rows)
    frame = frame.sort_values("订单日期").reset_index(drop=True)

    # 引入少量缺失值与重复行，用于展示数据质量提示
    missing_indices = rng.choice(frame.index.to_numpy(), size=6, replace=False)
    frame.loc[missing_indices, "利润"] = np.nan
    channel_missing = rng.choice(frame.index.to_numpy(), size=3, replace=False)
    frame.loc[channel_missing, "销售渠道"] = None
    duplicates = frame.sample(4, random_state=7)
    frame = pd.concat([frame, duplicates], ignore_index=True).sort_values("订单日期").reset_index(drop=True)
    return frame


def build_targets() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "区域": list(REGION_WEIGHTS.keys()),
            "年度目标": [860, 630, 520, 340, 310, 200],
            "已达成": [792, 548, 471, 286, 259, 152],
            "负责人": ["李宁", "王珂", "赵敏", "陈涛", "周悦", "孙浩"],
        }
    )


def build_dict() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "字段": ["订单日期", "区域", "省份", "产品类别", "产品名称", "销售渠道", "销量", "销售额", "利润"],
            "类型": ["日期", "文本", "文本", "文本", "文本", "文本", "整数", "数值", "数值"],
            "说明": [
                "订单发生的日期",
                "销售大区，共 6 个",
                "订单所属省份",
                "产品一级分类",
                "具体产品名称",
                "获客渠道",
                "订单商品件数",
                "订单含税销售额，单位：元",
                "订单毛利，单位：元",
            ],
        }
    )


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sales = build_sales()
    targets = build_targets()
    dictionary = build_dict()
    with pd.ExcelWriter(OUTPUT, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        sales.to_excel(writer, sheet_name="销售明细", index=False)
        targets.to_excel(writer, sheet_name="区域目标", index=False, startrow=2)
        dictionary.to_excel(writer, sheet_name="字段说明", index=False)
        target_sheet = writer.sheets["区域目标"]
        target_sheet["A1"] = "2026 年区域目标（金额单位：万元）"
        for sheet in writer.sheets.values():
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                width = max(10, min(24, max(len(str(cell.value or "")) for cell in column_cells) + 3))
                sheet.column_dimensions[column_cells[0].column_letter].width = width
    print(f"generated: {OUTPUT} ({len(sales):,} rows, {OUTPUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
