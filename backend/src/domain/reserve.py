"""整周缺水风险下的备水方案推演。

输入是滚动回测中每个完整七日起点的「同一周七天」误差组合（有符号误差 = 预测 − 实测）。
对每个历史情景，把下一周点预测按该周误差组合还原为模拟实测需求（向上取整到整升），
再在单日与整周上限内选择备水方案：

- 一个情景只有在七天的备水量都不小于当天模拟需求时才算覆盖；
- 优先选择能覆盖至少九成情景的最省水方案；达不到九成时选择覆盖情景最多且最省水的方案；
- 没有任何完整七日误差组合时标明无法估算。

结果只依赖传入的已收齐实测，因此晚到的实测在被接收前不会影响结果，重跑历史交班单可复现。
"""

from dataclasses import dataclass
from math import ceil

from .backtest import ForecastCheck
from .settings import DAYS_PER_WEEK

DAYS = DAYS_PER_WEEK
TARGET_RATIO = 0.9
# 整周上限的兜底值：七个单日上限之和，可由运行参数覆盖。
DEFAULT_WEEKLY_LIMIT = 1450 * DAYS


@dataclass(frozen=True)
class ReserveScenario:
    """一个历史起点对应的整周情景。"""

    origin: str
    errors: tuple[float, ...]          # 七天有符号误差（预测 − 实测），按提前天数 1..7
    needs: tuple[int, ...]             # 还原后的整升模拟需求，按天排列


def build_scenarios(checks: list[ForecastCheck], forecasts: list[float]) -> list[ReserveScenario]:
    """把滚动回测的配对误差按起点聚合成整周情景，保留同一周七天的误差组合。

    仅当某个起点的七天目标都存在（完整一周）时才计入，与回测的完整起点口径一致。
    """
    grouped: dict[str, dict[int, float]] = {}
    order: list[str] = []
    for check in checks:
        if check.origin not in grouped:
            grouped[check.origin] = {}
            order.append(check.origin)
        grouped[check.origin][check.step] = check.holt_winters - check.actual

    scenarios: list[ReserveScenario] = []
    for origin in order:
        week = grouped[origin]
        if len(week) != DAYS:
            continue
        errors = tuple(week[step] for step in range(1, DAYS + 1))
        needs = tuple(max(0, ceil(forecasts[day] - errors[day])) for day in range(DAYS))
        scenarios.append(ReserveScenario(origin, errors, needs))
    return scenarios


def _day_options(needs_rows: list[tuple[int, ...]], coverable: list[int],
                 daily_limit: int) -> list[list[tuple[int, int]]]:
    """每个备水日的候选 (备水量, 未覆盖位掩码)，掩码按 coverable 的情景下标编号。"""
    options: list[list[tuple[int, int]]] = []
    for day in range(DAYS):
        values = sorted({0} | {min(row[day], daily_limit) for row in needs_rows})
        day_opts: list[tuple[int, int]] = []
        last_fail = None
        for reserve in values:
            fail = 0
            for bit, scenario_index in enumerate(coverable):
                if needs_rows[scenario_index][day] > reserve:
                    fail |= 1 << bit
            if last_fail is not None and fail == last_fail:
                continue  # 覆盖情景相同，保留更小的备水量
            day_opts.append((reserve, fail))
            last_fail = fail
        options.append(day_opts)
    return options


def _solve(needs_rows: list[tuple[int, ...]], daily_limit: int, weekly_limit: int) -> dict:
    """精确分支限界：先最大化覆盖情景数，再在该覆盖水平下最小化总备水量。"""
    total = len(needs_rows)
    uncoverable_mask = 0
    for index, row in enumerate(needs_rows):
        if any(need > daily_limit for need in row):
            uncoverable_mask |= 1 << index
    coverable = [index for index in range(total) if not ((uncoverable_mask >> index) & 1)]
    coverable_count = len(coverable)
    target_count = ceil(total * TARGET_RATIO)

    if coverable_count == 0:
        return {
            "plan": [0] * DAYS, "covered": 0, "max_covered": 0, "cost": 0,
            "target_count": target_count, "uncoverable": total, "states": 0,
        }

    options = _day_options(needs_rows, coverable, daily_limit)
    min_cost = [day_opts[0][0] for day_opts in options]
    strongest_fail = [min(fail for _, fail in day_opts) for day_opts in options]
    suffix_min = [0] * (DAYS + 1)
    suffix_fail = [0] * (DAYS + 1)
    for day in range(DAYS - 1, -1, -1):
        suffix_min[day] = suffix_min[day + 1] + min_cost[day]
        suffix_fail[day] = suffix_fail[day + 1] | strongest_fail[day]

    def greedy_seed() -> tuple[list[int], int, int]:
        failed, cost, plan = 0, 0, [0] * DAYS
        for day in range(DAYS):
            room = weekly_limit - cost - suffix_min[day + 1]
            reserve, fail = options[day][0]
            best_survivors = coverable_count - (failed | fail).bit_count()
            for candidate_reserve, candidate_fail in options[day]:
                if candidate_reserve > room:
                    break
                survivors = coverable_count - (failed | candidate_fail).bit_count()
                if survivors > best_survivors:
                    best_survivors = survivors
                    reserve, fail = candidate_reserve, candidate_fail
            plan[day] = reserve
            cost += reserve
            failed |= fail
        return plan, cost, coverable_count - failed.bit_count()

    seed_plan, seed_cost, seed_coverage = greedy_seed()
    states = 0

    def search(required: int | None, seed=None) -> dict:
        if required is None and seed is not None:
            incumbent = {"coverage": seed[2], "cost": seed[1], "plan": seed[0].copy()}
        else:
            incumbent = {"coverage": required if required is not None else -1,
                         "cost": None, "plan": None}
        memo = [dict() for _ in range(DAYS + 1)]

        def dfs(day: int, failed: int, cost: int, plan: list[int]) -> None:
            nonlocal states
            states += 1
            coverage = coverable_count - failed.bit_count()
            if cost + suffix_min[day] > weekly_limit:
                return
            if required is not None and coverage < required:
                return
            floor = required if required is not None else max(incumbent["coverage"], 0)
            if coverable_count - (failed | suffix_fail[day]).bit_count() < floor:
                return
            if incumbent["cost"] is not None:
                if required is not None:
                    if cost + suffix_min[day] >= incumbent["cost"]:
                        return
                else:
                    if coverage < incumbent["coverage"]:
                        return
                    if (coverage == incumbent["coverage"]
                            and cost + suffix_min[day] >= incumbent["cost"]):
                        return
            if day == DAYS:
                if required is not None:
                    if incumbent["cost"] is None or cost < incumbent["cost"]:
                        incumbent.update(cost=cost, plan=plan.copy())
                elif (coverage > incumbent["coverage"]
                      or (coverage == incumbent["coverage"]
                          and (incumbent["cost"] is None or cost < incumbent["cost"]))):
                    incumbent.update(coverage=coverage, cost=cost, plan=plan.copy())
                return
            prior = memo[day].get(failed)
            if prior is not None and prior <= cost:
                return
            memo[day][failed] = cost
            room = weekly_limit - cost - suffix_min[day + 1]
            for reserve, fail in options[day]:
                if reserve > room:
                    break
                plan.append(reserve)
                dfs(day + 1, failed | fail, cost + reserve, plan)
                plan.pop()

        dfs(0, 0, 0, [])
        return incumbent

    # 第一遍：覆盖最多、其次最省水的全局最优。
    first = search(None, seed=(seed_plan, seed_cost, seed_coverage))
    max_covered, max_cost, max_plan = first["coverage"], first["cost"], first["plan"]

    if max_covered >= target_count:
        # 第二遍：在达到九成门槛的前提下取最省水方案。
        second = search(target_count)
        return {
            "plan": second["plan"], "covered": target_count, "max_covered": max_covered,
            "cost": second["cost"], "target_count": target_count,
            "uncoverable": total - coverable_count, "states": states,
        }
    return {
        "plan": max_plan, "covered": max_covered, "max_covered": max_covered,
        "cost": max_cost, "target_count": target_count,
        "uncoverable": total - coverable_count, "states": states,
    }


def plan_reserves(checks: list[ForecastCheck], forecasts: list[float],
                  daily_limit: int, weekly_limit: int | None = None) -> dict:
    """对外入口：从回测误差与下周点预测生成整周备水方案。

    返回结构化字典，交由 reports 层渲染为交班单表格。
    """
    if weekly_limit is None:
        weekly_limit = daily_limit * DAYS
    scenarios = build_scenarios(checks, forecasts)
    if not scenarios:
        return {
            "estimable": False, "status": "无法估算", "scenario_count": 0,
            "target_count": 0, "covered_count": 0, "max_covered_count": 0,
            "coverage_ratio": None, "target_met": False, "daily_limit": daily_limit,
            "weekly_limit": weekly_limit, "total_reserve": 0,
            "uncoverable_count": 0, "plan": [0] * DAYS, "scenarios": [],
        }

    needs_rows = [list(scenario.needs) for scenario in scenarios]
    result = _solve(needs_rows, daily_limit, weekly_limit)
    covered = result["covered"]
    return {
        "estimable": True,
        "status": "达到九成覆盖" if result["max_covered"] >= result["target_count"] else "未达九成覆盖",
        "scenario_count": len(scenarios),
        "target_count": result["target_count"],
        "covered_count": covered,
        "max_covered_count": result["max_covered"],
        "coverage_ratio": covered / len(scenarios),
        "target_met": result["max_covered"] >= result["target_count"],
        "daily_limit": daily_limit,
        "weekly_limit": weekly_limit,
        "total_reserve": result["cost"],
        "uncoverable_count": result["uncoverable"],
        "plan": result["plan"],
        "scenarios": [
            {
                "origin": scenario.origin,
                "needs": list(scenario.needs),
                "errors": list(scenario.errors),
                "covered": all(
                    scenario.needs[day] <= result["plan"][day] for day in range(DAYS)
                ),
            }
            for scenario in scenarios
        ],
    }
