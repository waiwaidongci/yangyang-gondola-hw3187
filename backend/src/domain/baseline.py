"""Seasonal naïve is the previous observed week in calendar order."""

from .settings import DAYS_PER_WEEK


def week_ahead(values: list[float], observed_count: int) -> list[float]:
    return values[observed_count - DAYS_PER_WEEK:observed_count]
