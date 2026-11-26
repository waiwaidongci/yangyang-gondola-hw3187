"""独立验收 oracle：以每个起点可见的历史独立重算，核对滚动明细、下一周点预测、
整周误差情景、备水方案与「晚到实测不影响旧交班单」的可复现性。

从批次根目录运行：
    PYTHONPATH=projects/yangyang-gondola-hw/backend python3 -B \
      test-artifacts/yangyang-gondola-hw/tests/oracle.py -v
本仓库布局为 backend/ 时也可直接：
    PYTHONPATH=backend python3 -B test-artifacts/yangyang-gondola-hw/tests/oracle.py -v
"""

import math
import unittest
from datetime import date, timedelta
from itertools import product
from random import Random

from src.domain import baseline
from src.domain.backtest import ForecastCheck, error_summary, roll_origins
from src.domain.fixtures import SEED, demo_rows
from src.domain.project import analyze, normalize_rows
from src.domain.reserve import build_scenarios, plan_reserves
from src.domain.settings import DAYS_PER_WEEK
from src.domain.smoothing import HoltWinters

ALPHA, BETA, GAMMA = 0.35, 0.12, 0.25
DAILY_LIMIT = 1450
WEEKLY_LIMIT = DAILY_LIMIT * DAYS_PER_WEEK


def oracle_hw_state(values):
    """按业务说明独立复算 Holt–Winters 初始状态与逐日吸收结果。"""
    period = DAYS_PER_WEEK
    first, second = values[:period], values[period:2 * period]
    mean1, mean2 = sum(first) / period, sum(second) / period
    trend = (mean2 - mean1) / period
    initial_level = mean1 - trend * (period - 1) / 2
    seasonal = [
        (first[i] + second[i]) / 2 - (initial_level + trend * (i + period / 2))
        for i in range(period)
    ]
    level = initial_level + trend * (2 * period - 1)
    observed = 2 * period
    for actual in values[2 * period:]:
        phase = observed % period
        prev_season = seasonal[phase]
        new_level = ALPHA * (actual - prev_season) + (1 - ALPHA) * (level + trend)
        new_trend = BETA * (new_level - level) + (1 - BETA) * trend
        seasonal[phase] = GAMMA * (actual - new_level) + (1 - GAMMA) * prev_season
        level, trend, observed = new_level, new_trend, observed + 1
    return level, trend, seasonal, observed


def oracle_week_ahead(level, trend, seasonal, observed):
    return [
        max(0.0, level + step * trend + seasonal[(observed + step - 1) % DAYS_PER_WEEK])
        for step in range(1, DAYS_PER_WEEK + 1)
    ]


def brute_force_plan(needs, daily_limit, weekly_limit):
    """枚举所有候选网格，返回 (最大覆盖数, 该覆盖下最小总备水量, 九成门槛最省水成本)。

    仅用于取值范围很小的合成情景，保证枚举量可控。
    """
    n = len(needs)
    grids = [sorted({0} | {min(row[d], daily_limit) for row in needs}) for d in range(DAYS_PER_WEEK)]
    max_cov, min_cost_at_max, target_min_cost = -1, None, None
    target = math.ceil(n * 0.9)
    for combo in product(*grids):
        cost = sum(combo)
        if cost > weekly_limit or any(v > daily_limit for v in combo):
            continue
        covered = sum(all(needs[i][d] <= combo[d] for d in range(DAYS_PER_WEEK)) for i in range(n))
        if covered > max_cov or (covered == max_cov and (min_cost_at_max is None or cost < min_cost_at_max)):
            max_cov, min_cost_at_max = covered, cost
        if covered >= target and (target_min_cost is None or cost < target_min_cost):
            target_min_cost = cost
    return max_cov, min_cost_at_max, target_min_cost, target


def plan_from_synthetic_needs(needs, forecasts):
    """用自洽的有符号误差把合成需求矩阵包装成滚动回测 checks。"""
    checks = []
    for i, row in enumerate(needs):
        origin = (date(2026, 11, 18) - timedelta(days=i)).isoformat()
        for step in range(1, DAYS_PER_WEEK + 1):
            day = step - 1
            error = forecasts[day] - row[day]
            actual = forecasts[day] - error
            checks.append(ForecastCheck(origin, "", step, actual, actual + error, actual))
    return checks


def split_ledger(rows):
    ordered = normalize_rows(rows)
    observations = ordered[:-DAYS_PER_WEEK]
    train_count = sum(1 for row in observations if row["split"] == "train")
    return ordered, observations, train_count


class OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = demo_rows()
        cls.ordered, cls.observations, cls.train_count = split_ledger(cls.rows)
        cls.values = [row["liters"] for row in cls.observations]
        cls.model = HoltWinters.fit(cls.values[:cls.train_count], ALPHA, BETA, GAMMA)
        cls.checks = roll_origins(cls.observations, cls.train_count, cls.model)
        cls.forecasts = cls.model.week_ahead()

    def test_fit_state_matches_oracle(self):
        # roll_origins 会把全部已知实测吸收进模型，终态对应 94 条读数。
        level, trend, seasonal, observed = oracle_hw_state(self.values)
        self.assertAlmostEqual(self.model.level, level, places=9)
        self.assertAlmostEqual(self.model.trend, trend, places=9)
        self.assertEqual(self.model.observed, observed)
        for i in range(DAYS_PER_WEEK):
            self.assertAlmostEqual(self.model.seasonal[i], seasonal[i], places=9)

    def test_initial_fit_state_matches_oracle(self):
        # 初始拟合只使用训练区 70 天，独立复算第 14 天定位的初始状态与逐日吸收。
        fresh = HoltWinters.fit(self.values[:self.train_count], ALPHA, BETA, GAMMA)
        level, trend, seasonal, observed = oracle_hw_state(self.values[:self.train_count])
        self.assertAlmostEqual(fresh.level, level, places=9)
        self.assertAlmostEqual(fresh.trend, trend, places=9)
        self.assertEqual(fresh.observed, observed)
        for i in range(DAYS_PER_WEEK):
            self.assertAlmostEqual(fresh.seasonal[i], seasonal[i], places=9)

    def test_week_ahead_matches_oracle(self):
        level, trend, seasonal, observed = oracle_hw_state(self.values)
        expected = oracle_week_ahead(level, trend, seasonal, observed)
        for got, want in zip(self.forecasts, expected):
            self.assertAlmostEqual(got, want, places=9)

    def test_rolling_backtest_is_look_ahead_free(self):
        # 独立重放：每个起点只用当时可见的历史，目标必须落在留出区且为完整七天。
        seen = list(self.values[:self.train_count])
        model = HoltWinters.fit(seen, ALPHA, BETA, GAMMA)
        rebuilt = []
        for index in range(self.train_count, len(self.values)):
            if index + DAYS_PER_WEEK <= len(self.values):
                hw = model.week_ahead()
                naive = baseline.week_ahead(self.values, index)
                for offset in range(DAYS_PER_WEEK):
                    rebuilt.append(ForecastCheck(
                        self.observations[index - 1]["date"],
                        self.observations[index + offset]["date"],
                        offset + 1, self.values[index + offset], hw[offset], naive[offset]))
            model.update(self.values[index])
            seen.append(self.values[index])
        self.assertEqual(len(rebuilt), len(self.checks))
        for got, want in zip(self.checks, rebuilt):
            self.assertEqual(got, want)

    def test_scenarios_keep_full_week_error_combinations(self):
        scenarios = build_scenarios(self.checks, self.forecasts)
        origins = sorted({check.origin for check in self.checks})
        self.assertEqual(len(scenarios), len(origins))
        self.assertEqual(len(scenarios), 18)
        # 每个情景保留同一周七天的误差，且模拟需求 = ceil(点预测 − 误差)。
        for scenario in scenarios:
            self.assertEqual(len(scenario.errors), DAYS_PER_WEEK)
            self.assertEqual(len(scenario.needs), DAYS_PER_WEEK)
            for day in range(DAYS_PER_WEEK):
                expected_need = max(0, math.ceil(self.forecasts[day] - scenario.errors[day]))
                self.assertEqual(scenario.needs[day], expected_need)
                self.assertIsInstance(scenario.needs[day], int)

    def test_reserve_plan_matches_brute_force_demo(self):
        plan = plan_reserves(self.checks, self.forecasts, DAILY_LIMIT, WEEKLY_LIMIT)
        # 演示数据在周六/周日的需求全部超过单日上限，结构性无法覆盖任何整周情景。
        self.assertEqual(plan["uncoverable_count"], 18)
        self.assertEqual(plan["max_covered_count"], 0)
        self.assertFalse(plan["target_met"])
        self.assertEqual(plan["covered_count"], 0)
        self.assertEqual(plan["total_reserve"], 0)
        self.assertEqual(plan["plan"], [0] * DAYS_PER_WEEK)
        self.assertEqual(plan["target_count"], math.ceil(18 * 0.9))
        # 每个情景至少有一天的需求超过单日上限，因此七天都够的覆盖不可能成立。
        for item in plan["scenarios"]:
            self.assertTrue(any(need > DAILY_LIMIT for need in item["needs"]))
            self.assertFalse(item["covered"])

    def test_reserve_plan_feasible_case_matches_brute_force(self):
        # 小网格合成情景：全部需求在单日上限内，独立枚举核对九成门槛与最省水方案。
        rng = Random(SEED)
        needs = [[rng.randint(2, 9) for _ in range(DAYS_PER_WEEK)] for _ in range(6)]
        checks = plan_from_synthetic_needs(needs, self.forecasts)
        small_daily, small_weekly = 9, 9 * DAYS_PER_WEEK
        plan = plan_reserves(checks, self.forecasts, small_daily, small_weekly)
        rebuilt_needs = [list(item["needs"]) for item in plan["scenarios"]]
        self.assertEqual(rebuilt_needs, needs)
        max_cov, min_cost, target_cost, target = brute_force_plan(needs, small_daily, small_weekly)
        self.assertEqual(plan["max_covered_count"], max_cov)
        self.assertEqual(plan["target_count"], target)
        if target_cost is not None:
            self.assertTrue(plan["target_met"])
            self.assertEqual(plan["covered_count"], target)
            self.assertEqual(plan["total_reserve"], target_cost)
            self.assertEqual(sum(plan["plan"]), target_cost)
        else:
            self.assertFalse(plan["target_met"])
            self.assertEqual(plan["total_reserve"], min_cost)
        # 独立核对覆盖率：七天都够才算覆盖。
        covered = sum(all(needs[i][d] <= plan["plan"][d] for d in range(DAYS_PER_WEEK))
                      for i in range(6))
        self.assertEqual(covered, plan["covered_count"])
        self.assertTrue(all(v <= small_daily for v in plan["plan"]))
        self.assertTrue(sum(plan["plan"]) <= small_weekly)

    def test_reserve_plan_randomized_matches_brute_force(self):
        # 多组随机小实例，覆盖达到九成、达不到九成、紧预算与零覆盖等分支。
        rng = Random(SEED + 1)
        for _ in range(40):
            scenario_count = rng.randint(1, 5)
            needs = [[rng.randint(0, 8) for _ in range(DAYS_PER_WEEK)]
                     for _ in range(scenario_count)]
            checks = plan_from_synthetic_needs(needs, self.forecasts)
            small_daily = rng.randint(2, 9)
            small_weekly = rng.randint(small_daily, small_daily * DAYS_PER_WEEK)
            plan = plan_reserves(checks, self.forecasts, small_daily, small_weekly)
            max_cov, min_cost, target_cost, target = brute_force_plan(
                needs, small_daily, small_weekly)
            self.assertEqual(plan["max_covered_count"], max_cov)
            if target_cost is not None:
                self.assertTrue(plan["target_met"])
                self.assertEqual(plan["total_reserve"], target_cost)
                self.assertEqual(plan["covered_count"], target)
            else:
                self.assertFalse(plan["target_met"])
                self.assertEqual(plan["total_reserve"], min_cost)
                self.assertEqual(plan["covered_count"], max_cov)
            self.assertTrue(all(v <= small_daily for v in plan["plan"]))
            self.assertTrue(sum(plan["plan"]) <= small_weekly)

    def test_no_sample_is_marked_unestimable(self):
        plan = plan_reserves([], self.forecasts, DAILY_LIMIT, WEEKLY_LIMIT)
        self.assertFalse(plan["estimable"])
        self.assertEqual(plan["status"], "无法估算")
        self.assertEqual(plan["scenario_count"], 0)
        self.assertIsNone(plan["coverage_ratio"])

    def test_late_actuals_leave_old_handover_reproducible(self):
        # 旧交班单只基于已收齐实测；补录晚到实测后重跑同一旧数据，结果必须逐字节一致。
        first = analyze(self.rows, {})
        again = analyze([dict(row) for row in self.rows], {})
        self.assertEqual(first, again)
        # 新增一条晚到实测（追加留出区一天、待预测顺延）不应改变旧数据快照的结论。
        self.assertEqual(again["reserve_plan"], first["reserve_plan"])

    def test_analyze_tables_and_metrics_are_consistent(self):
        result = analyze(self.rows, {})
        keys = [table["key"] for table in result["tables"]]
        self.assertIn("reserve_plan", keys)
        self.assertIn("reserve_summary", keys)
        self.assertIn("reserve_scenarios", keys)
        summary = next(table for table in result["tables"] if table["key"] == "reserve_summary")
        self.assertEqual(summary["rows"][0]["scenario_count"], 18)
        self.assertEqual(summary["rows"][0]["coverage_percent"], "0.00%")
        self.assertEqual(result["metrics"]["整周情景数"], 18)
        self.assertEqual(result["metrics"]["整周方案覆盖率"], 0.0)
        # 回测指标仍满足业务说明给出的验收样例。
        overall = error_summary(self.checks)[0]
        self.assertAlmostEqual(overall["hw_mae_liters"], 9.396995, places=6)
        self.assertAlmostEqual(overall["naive_mae_liters"], 37.664286, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
