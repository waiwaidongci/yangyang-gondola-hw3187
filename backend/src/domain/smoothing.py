"""Additive Holt–Winters with a seven-day season and explicit initialization."""

from dataclasses import dataclass
from statistics import fmean

from .settings import DAYS_PER_WEEK


@dataclass
class HoltWinters:
    alpha: float
    beta: float
    gamma: float
    level: float
    trend: float
    seasonal: list[float]
    observed: int

    @classmethod
    def fit(cls, values: list[float], alpha: float, beta: float, gamma: float) -> "HoltWinters":
        period = DAYS_PER_WEEK
        first, second = values[:period], values[period:2 * period]
        trend = (fmean(second) - fmean(first)) / period
        initial_level = fmean(first) - trend * (period - 1) / 2
        seasonal = [
            (earlier + later) / 2 - (initial_level + trend * (index + period / 2))
            for index, (earlier, later) in enumerate(zip(first, second))
        ]
        level = initial_level + trend * (2 * period - 1)
        model = cls(alpha, beta, gamma, level, trend, seasonal, 2 * period)
        for actual in values[2 * period:]:
            model.update(actual)
        return model

    def update(self, actual: float) -> None:
        phase = self.observed % DAYS_PER_WEEK
        previous_level = self.level
        previous_season = self.seasonal[phase]
        self.level = self.alpha * (actual - previous_season) + (1 - self.alpha) * (self.level + self.trend)
        self.trend = self.beta * (self.level - previous_level) + (1 - self.beta) * self.trend
        self.seasonal[phase] = self.gamma * (actual - self.level) + (1 - self.gamma) * previous_season
        self.observed += 1

    def week_ahead(self) -> list[float]:
        return [
            max(0.0, self.level + step * self.trend + self.seasonal[(self.observed + step - 1) % DAYS_PER_WEEK])
            for step in range(1, DAYS_PER_WEEK + 1)
        ]
