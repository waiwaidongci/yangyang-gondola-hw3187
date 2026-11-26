"""Prepare flat, export-ready worksheet rows with an explicit column order."""

from datetime import date
from math import ceil

from .backtest import ForecastCheck
from .smoothing import HoltWinters

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def table(key: str, title: str, labels: dict[str, str], rows: list[dict]) -> dict:
    return {
        "key": key, "title": title, "columns": list(labels), "labels": labels,
        "rows": [{column: round(row[column], 6) if isinstance(row[column], float) else row[column]
                  for column in labels} for row in rows],
    }


def handover(dates: list[str], hw: list[float], naive: list[float], limit: int) -> dict:
    rows = []
    for step, (day, forecast, reference) in enumerate(zip(dates, hw, naive), start=1):
        staging = ceil(round(forecast, 6))
        shortfall = max(0, staging - limit)
        rows.append({
            "date": day, "weekday": WEEKDAYS[date.fromisoformat(day).weekday()], "step": step,
            "hw_liters": forecast, "naive_liters": reference, "staging_liters": staging,
            "limit_liters": limit, "shortfall_liters": shortfall, "action": "需协调" if shortfall else "常规备水",
        })
    return table("staging_handover", "七日备水交班单", {
        "date": "值班日期", "weekday": "星期", "step": "预测提前天数", "hw_liters": "季节平滑预测（升）",
        "naive_liters": "上周同日实测（升）", "staging_liters": "备水需求（整升）", "limit_liters": "早班上限（升）",
        "shortfall_liters": "待协调差额（升）", "action": "交班安排",
    }, rows)


def reserve_plan(dates: list[str], forecasts: list[float], plan: dict) -> dict:
    """整周备水方案：每天的模拟需求区间、选定备水量与协调差额。"""
    rows = []
    scenarios = plan["scenarios"]
    for step, (day, forecast) in enumerate(zip(dates, forecasts), start=1):
        day_index = step - 1
        if scenarios:
            needs = [item["needs"][day_index] for item in scenarios]
            min_need, max_need = min(needs), max(needs)
        else:
            min_need = max_need = None
        reserve = plan["plan"][day_index]
        shortfall = max(0, max_need - reserve) if max_need is not None else 0
        cap_shortfall = max(0, reserve - plan["daily_limit"])
        rows.append({
            "date": day, "weekday": WEEKDAYS[date.fromisoformat(day).weekday()], "step": step,
            "hw_liters": forecast, "min_need_liters": min_need, "max_need_liters": max_need,
            "reserve_liters": reserve, "daily_limit_liters": plan["daily_limit"],
            "shortfall_liters": shortfall, "over_limit_liters": cap_shortfall,
            "action": "需协调" if shortfall or cap_shortfall else "常规备水",
        })
    return table("reserve_plan", "整周缺水风险备水方案", {
        "date": "值班日期", "weekday": "星期", "step": "预测提前天数",
        "hw_liters": "季节平滑点预测（升）", "min_need_liters": "情景最低需求（升）",
        "max_need_liters": "情景最高需求（升）", "reserve_liters": "选定备水量（升）",
        "daily_limit_liters": "单日上限（升）", "shortfall_liters": "最高情景待协调差额（升）",
        "over_limit_liters": "超单日上限差额（升）", "action": "交班安排",
    }, rows)


def reserve_summary(plan: dict) -> dict:
    """整周备水方案的覆盖率与上限核对汇总。"""
    ratio = plan["coverage_ratio"]
    row = {
        "estimable": "是" if plan["estimable"] else "否",
        "status": plan["status"],
        "scenario_count": plan["scenario_count"],
        "target_count": plan["target_count"],
        "covered_count": plan["covered_count"],
        "max_covered_count": plan["max_covered_count"],
        "coverage_ratio": round(ratio, 6) if ratio is not None else None,
        "coverage_percent": f"{ratio * 100:.2f}%" if ratio is not None else "无法估算",
        "target_met": "是" if plan["target_met"] else "否",
        "daily_limit_liters": plan["daily_limit"],
        "weekly_limit_liters": plan["weekly_limit"],
        "total_reserve_liters": plan["total_reserve"],
        "uncoverable_count": plan["uncoverable_count"],
    }
    return table("reserve_summary", "整周备水覆盖率与上限核对", {
        "estimable": "是否可估算", "status": "方案状态", "scenario_count": "历史整周情景数",
        "target_count": "九成门槛情景数", "covered_count": "方案覆盖情景数",
        "max_covered_count": "上限内最多可覆盖情景数", "coverage_ratio": "覆盖率",
        "coverage_percent": "覆盖率（百分比）", "target_met": "是否达到九成",
        "daily_limit_liters": "单日上上限（升）", "weekly_limit_liters": "整周上限（升）",
        "total_reserve_liters": "选定方案总备水量（升）", "uncoverable_count": "结构性无法覆盖情景数",
    }, [row])


def reserve_scenarios(plan: dict) -> dict:
    """每个历史整周情景的模拟需求与是否被选定方案七天全覆盖。"""
    rows = []
    for index, item in enumerate(plan["scenarios"], start=1):
        rows.append({
            "scenario_index": index, "origin_date": item["origin"],
            "need_day_1": item["needs"][0], "need_day_2": item["needs"][1],
            "need_day_3": item["needs"][2], "need_day_4": item["needs"][3],
            "need_day_5": item["needs"][4], "need_day_6": item["needs"][5],
            "need_day_7": item["needs"][6],
            "error_day_1": item["errors"][0], "error_day_2": item["errors"][1],
            "error_day_3": item["errors"][2], "error_day_4": item["errors"][3],
            "error_day_5": item["errors"][4], "error_day_6": item["errors"][5],
            "error_day_7": item["errors"][6],
            "covered": "是" if item["covered"] else "否",
        })
    return table("reserve_scenarios", "历史整周情景明细", {
        "scenario_index": "情景序号", "origin_date": "起点（最后一条可见日期）",
        "need_day_1": "第1日模拟需求（升）", "need_day_2": "第2日模拟需求（升）",
        "need_day_3": "第3日模拟需求（升）", "need_day_4": "第4日模拟需求（升）",
        "need_day_5": "第5日模拟需求（升）", "need_day_6": "第6日模拟需求（升）",
        "need_day_7": "第7日模拟需求（升）",
        "error_day_1": "第1日有符号误差（升）", "error_day_2": "第2日有符号误差（升）",
        "error_day_3": "第3日有符号误差（升）", "error_day_4": "第4日有符号误差（升）",
        "error_day_5": "第5日有符号误差（升）", "error_day_6": "第6日有符号误差（升）",
        "error_day_7": "第7日有符号误差（升）", "covered": "是否七天全覆盖",
    }, rows)


def trace(checks: list[ForecastCheck]) -> dict:
    return table("rolling_backtest", "滚动起点逐日回测", {
        "origin_date": "起点（最后一条可见日期）", "target_date": "目标日期", "step": "预测提前天数",
        "actual_liters": "实测（升）", "hw_liters": "季节平滑预测（升）", "naive_liters": "季节朴素预测（升）",
        "hw_error_liters": "季节平滑有符号误差（升）", "naive_error_liters": "季节朴素有符号误差（升）",
    }, [
        {"origin_date": row.origin, "target_date": row.target, "step": row.step, "actual_liters": row.actual,
         "hw_liters": row.holt_winters, "naive_liters": row.seasonal_naive,
         "hw_error_liters": row.holt_winters - row.actual, "naive_error_liters": row.seasonal_naive - row.actual}
        for row in checks
    ])


def accuracy(rows: list[dict]) -> dict:
    return table("backtest_accuracy", "总体与提前天数误差对照", {
        "scope": "比较范围", "samples": "起点与目标配对数", "hw_mae_liters": "季节平滑 MAE（升）",
        "naive_mae_liters": "季节朴素 MAE（升）", "mae_delta_liters": "季节平滑减季节朴素 MAE（升）",
        "hw_rmse_liters": "季节平滑 RMSE（升）", "naive_rmse_liters": "季节朴素 RMSE（升）",
        "hw_bias_liters": "季节平滑平均有符号误差（升）", "naive_bias_liters": "季节朴素平均有符号误差（升）",
    }, rows)


def final_state(model: HoltWinters, first_date: str, last_date: str) -> dict:
    start_phase = date.fromisoformat(first_date).weekday()
    return table("fit_state", "终测截点与周季节分量", {
        "weekday": "星期", "from_date": "首条观测日期", "through_date": "拟合截至日期", "observations": "观测天数",
        "alpha": "水平系数", "beta": "趋势系数", "gamma": "季节系数", "level_liters": "末日水平（升）",
        "trend_liters_per_day": "末日趋势（升/天）", "seasonal_liters": "星期分量（升）",
    }, [
        {"weekday": weekday, "from_date": first_date, "through_date": last_date, "observations": model.observed,
         "alpha": model.alpha, "beta": model.beta, "gamma": model.gamma, "level_liters": model.level,
         "trend_liters_per_day": model.trend, "seasonal_liters": model.seasonal[(phase - start_phase) % len(WEEKDAYS)]}
        for phase, weekday in enumerate(WEEKDAYS)
    ])
