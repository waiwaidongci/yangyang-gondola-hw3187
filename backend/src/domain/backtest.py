"""Paired expanding-window evaluation and horizon diagnostics."""

from dataclasses import dataclass
from math import sqrt
from statistics import fmean

from . import baseline
from .settings import DAYS_PER_WEEK
from .smoothing import HoltWinters


@dataclass(frozen=True)
class ForecastCheck:
    origin: str
    target: str
    step: int
    actual: float
    holt_winters: float
    seasonal_naive: float


def roll_origins(observations: list[dict], train_count: int, model: HoltWinters) -> list[ForecastCheck]:
    """Evaluate only complete holdout weeks and advance state through every known reading."""
    values = [row["liters"] for row in observations]
    checks = []
    for index in range(train_count, len(values)):
        if index + DAYS_PER_WEEK <= len(values):
            origin = observations[index - 1]["date"]
            forecasts = zip(model.week_ahead(), baseline.week_ahead(values, index))
            for offset, (hw, naive) in enumerate(forecasts):
                target = observations[index + offset]
                checks.append(ForecastCheck(origin, target["date"], offset + 1, target["liters"], hw, naive))
        model.update(values[index])
    return checks


def error_summary(rows: list[ForecastCheck]) -> list[dict]:
    scopes = [("all", rows)] + [
        (f"day_{step}", [row for row in rows if row.step == step])
        for step in range(1, DAYS_PER_WEEK + 1)
    ]
    summary = []
    for scope, group in scopes:
        hw = [row.holt_winters - row.actual for row in group]
        naive = [row.seasonal_naive - row.actual for row in group]
        hw_mae = fmean(map(abs, hw))
        naive_mae = fmean(map(abs, naive))
        summary.append({
            "scope": scope,
            "samples": len(group),
            "hw_mae_liters": hw_mae,
            "naive_mae_liters": naive_mae,
            "mae_delta_liters": hw_mae - naive_mae,
            "hw_rmse_liters": sqrt(fmean(error ** 2 for error in hw)),
            "naive_rmse_liters": sqrt(fmean(error ** 2 for error in naive)),
            "hw_bias_liters": fmean(hw),
            "naive_bias_liters": fmean(naive),
        })
    return summary
