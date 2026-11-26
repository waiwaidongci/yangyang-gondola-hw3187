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
