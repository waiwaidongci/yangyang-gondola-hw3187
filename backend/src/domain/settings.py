"""CSV fields and run settings exposed by the shared API."""

DAYS_PER_WEEK = 7
MAX_LITERS = 1_000_000
COLUMNS = ("date", "split", "liters")
FIELDS = {"date": "晨间值班日期", "split": "序列用途", "liters": "实测补水量（升）"}
SETTINGS = [
    {"key": "alpha", "label": "水平平滑系数", "default": 0.35, "min": 0, "max": 1, "step": 0.01},
    {"key": "beta", "label": "趋势平滑系数", "default": 0.12, "min": 0, "max": 1, "step": 0.01},
    {"key": "gamma", "label": "周季节平滑系数", "default": 0.25, "min": 0, "max": 1, "step": 0.01},
    {"key": "staging_limit_liters", "label": "早班备水上限（升）", "default": 1450,
     "min": 1, "max": MAX_LITERS, "step": 1},
]

SPEC = {
    "columns": list(COLUMNS),
    "fields": FIELDS,
    "settings": SETTINGS,
    "modules": {
        "datasets": "晨间补水台账",
        "runs": "季节平滑配置",
        "results": "七日备水交班单",
        "reviews": "早班交班复核",
    },
    "limitation": "输出为单池七日点预测。降雨、回水设备检修、临时活动及读数漏录需由值班人员单独核查。",
    "dataset_name": "20261125-洗窗回水池晨间补水.csv",
    "recommendation": "按值班日期备水，优先复核标为需协调的日期与差额。",
}


def parse_settings(settings: dict) -> dict[str, float]:
    if not isinstance(settings, dict) or settings.keys() - {item["key"] for item in SETTINGS}:
        raise ValueError("存在本项目未定义的运行参数。")
    parsed = {}
    for item in SETTINGS:
        key = item["key"]
        value = settings.get(key, item["default"])
        if type(value) not in (int, float) or not item["min"] <= value <= item["max"]:
            raise ValueError(f'{item["label"]}须为 {item["min"]} 至 {item["max"]} 之间的数值。')
        if item["step"] == 1:
            if value != int(value):
                raise ValueError(f'{item["label"]}须为整数。')
            value = int(value)
        parsed[key] = value
    return parsed
