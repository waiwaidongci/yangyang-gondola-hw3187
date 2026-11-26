"""A deterministic single-pool ledger and its usable UTF-8 CSV template."""

import csv
from datetime import date, timedelta
from io import StringIO
from random import Random

from .settings import COLUMNS, DAYS_PER_WEEK

SEED = 26112595
START = date(2026, 8, 17)
TRAIN_DAYS = 70
HOLDOUT_DAYS = 24
# Monday through Sunday, centered around a typical weekday allocation.
WEEKLY_LITERS = (-122, -155, -113, -22, 30, 180, 202)


def demo_rows() -> list[dict]:
    rng = Random(SEED)
    rows = []
    observed_days = TRAIN_DAYS + HOLDOUT_DAYS
    for index in range(observed_days + DAYS_PER_WEEK):
        day = START + timedelta(days=index)
        if index < observed_days:
            split = "train" if index < TRAIN_DAYS else "holdout"
            liters = round(910 + 5.4 * index + WEEKLY_LITERS[day.weekday()] + rng.uniform(-13, 13), 1)
        else:
            split, liters = "pending", None
        rows.append({"date": day.isoformat(), "split": split, "liters": liters})
    return rows


def demo_csv() -> str:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(demo_rows())
    return buffer.getvalue()
