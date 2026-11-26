"""Validate a continuous daily register before splitting it into time blocks."""

import re
from collections import Counter
from datetime import date

from .settings import COLUMNS, DAYS_PER_WEEK, MAX_LITERS

SPLITS = ("train", "holdout", "pending")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def read_date(value, line: int) -> date:
    if isinstance(value, str):
        value = value.strip()
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.isoformat() == value:
                return parsed
    raise ValueError(f"第 {line} 条日期须为有效的 YYYY-MM-DD。")


def read_liters(value, split: str, line: int) -> float | None:
    if isinstance(value, str):
        value = value.strip()
    if split == "pending":
        if value is None or value == "":
            return None
        raise ValueError(f"第 {line} 条待预测记录的实测补水量须留空。")
    if isinstance(value, str) and DECIMAL.fullmatch(value):
        value = float(value)
    if type(value) not in (int, float) or not 0 <= value <= MAX_LITERS:
        raise ValueError(f"第 {line} 条实测补水量须为 0 至 {MAX_LITERS} 之间的数值。")
    return float(value) if value else 0.0


def normalize_rows(rows: list[dict]) -> list[dict]:
    normalized = {}
    counts = Counter()
    for line, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict) or raw.keys() != set(COLUMNS):
            raise ValueError(f"第 {line} 条的列须与模板一致：{', '.join(COLUMNS)}。")
        day = read_date(raw["date"], line)
        if day in normalized:
            raise ValueError(f"第 {line} 条日期 {day} 重复，每日只允许一条记录。")
        split = raw["split"].strip() if isinstance(raw["split"], str) else None
        if split not in SPLITS:
            raise ValueError(f"第 {line} 条序列用途须为 train、holdout 或 pending。")
        liters = read_liters(raw["liters"], split, line)
        normalized[day] = {"date": day.isoformat(), "split": split, "liters": liters}
        counts[split] += 1

    if counts["train"] < 2 * DAYS_PER_WEEK or counts["holdout"] < DAYS_PER_WEEK:
        raise ValueError("历史至少需要 14 天实测记录，留出至少需要 7 天实测记录。")
    if counts["pending"] != DAYS_PER_WEEK:
        raise ValueError("待预测区必须填写接下来 7 天的日期。")

    days = sorted(normalized)
    for earlier, later in zip(days, days[1:]):
        if (later - earlier).days != 1:
            raise ValueError(f"日期必须逐日连续，{earlier} 与 {later} 之间有漏录。")
    ordered = [normalized[day] for day in days]
    expected_splits = [split for split in SPLITS for _ in range(counts[split])]
    if [row["split"] for row in ordered] != expected_splits:
        raise ValueError("按日期排序后须依次为历史、留出、待预测三个连续区段。")
    return ordered
