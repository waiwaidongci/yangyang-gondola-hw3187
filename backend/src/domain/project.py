"""Business entry points consumed by the catalog, seed and calculation worker."""

from . import baseline, reports
from .backtest import error_summary, roll_origins
from .fixtures import demo_rows
from .records import normalize_rows
from .settings import DAYS_PER_WEEK, SPEC, parse_settings
from .smoothing import HoltWinters

__all__ = ["SPEC", "demo_rows", "normalize_rows", "analyze"]


def analyze(rows: list[dict], settings: dict) -> dict:
    options = parse_settings(settings)
    ordered = normalize_rows(rows)
    observations, pending = ordered[:-DAYS_PER_WEEK], ordered[-DAYS_PER_WEEK:]
    train = [row["liters"] for row in observations if row["split"] == "train"]
    values = [row["liters"] for row in observations]
    model = HoltWinters.fit(train, options["alpha"], options["beta"], options["gamma"])
    checks = roll_origins(observations, len(train), model)
    accuracy = error_summary(checks)
    forecasts = model.week_ahead()
    handover = reports.handover([row["date"] for row in pending], forecasts,
                                baseline.week_ahead(values, len(values)), options["staging_limit_liters"])
    origins = len(checks) // DAYS_PER_WEEK
    short_days = sum(row["shortfall_liters"] > 0 for row in handover["rows"])
    overall = accuracy[0]
    warnings = []
    if overall["mae_delta_liters"] > 0:
        warnings.append("本次留出区季节平滑 MAE 高于季节朴素，请在签核前查阅分步误差。")
    if origins == 1:
        warnings.append("留出区仅覆盖一个七日起点，误差对照的时间覆盖有限。")
    if short_days:
        warnings.append(f"有 {short_days} 天备水需求超过早班上限，请在交班前协调水源。")
    last_date = observations[-1]["date"]
    return {
        "summary": (f"使用 {len(train)} 天历史初始化运行，在留出区逐日滚动核对 {origins} 个完整七日起点。"
                    f"已吸收截至 {last_date} 的 {len(observations)} 条实测读数，生成下一周的备水交班单。"),
        "metrics": {
            "已知实测天数": len(values), "完整滚动起点数": origins, "可比较预测数": len(checks),
            "季节平滑 MAE（升）": round(overall["hw_mae_liters"], 6),
            "季节朴素 MAE（升）": round(overall["naive_mae_liters"], 6),
            "下一周点预测合计（升）": round(sum(forecasts), 6), "需协调天数": short_days,
        },
        "tables": [handover, reports.accuracy(accuracy), reports.trace(checks),
                   reports.final_state(model, observations[0]["date"], last_date)],
        "warnings": warnings,
    }
