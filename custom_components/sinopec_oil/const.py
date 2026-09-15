"""Constants for the Sinopec Oil Price integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sinopec_oil"
MANUFACTURER: Final = "Sinopec / 中国石化"

# --- 配置项 ---
CONF_PROVINCE: Final = "province"
CONF_AREA: Final = "area"  # 价区（一价区/二价区等）ID
CONF_SCAN_INTERVAL: Final = "scan_interval"

# 车辆配置
CONF_VEHICLE: Final = "vehicle"
CONF_INITIAL_ODOMETER: Final = "initial_odometer"
CONF_FUEL_TYPE: Final = "fuel_type"

DEFAULT_PROVINCE: Final = "11"  # 默认省份：北京
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 60

# --- 单位 ---
UNIT_YUAN_PER_LITER: Final = "元/L"
UNIT_YUAN: Final = "元"
UNIT_LITER: Final = "L"
UNIT_KM: Final = "km"
UNIT_L_PER_100KM: Final = "L/100km"
UNIT_YUAN_PER_KM: Final = "元/km"

# --- 服务 ---
SERVICE_RECORD_REFUEL: Final = "record_refuel"
SERVICE_IMPORT_RECORDS: Final = "import_refuel_records"
SERVICE_LIST_RECORDS: Final = "list_refuel_records"
SERVICE_DELETE_RECORD: Final = "delete_refuel_record"
SERVICE_EDIT_RECORD: Final = "edit_refuel_record"
SERVICE_ADD_VEHICLE: Final = "add_vehicle"
SERVICE_REMOVE_VEHICLE: Final = "remove_vehicle"
SERVICE_CLEAR_VEHICLE: Final = "clear_vehicle_data"
SERVICE_REFRESH_OIL_PRICE: Final = "refresh_oil_price"
SERVICE_GET_PRICE_HISTORY: Final = "get_price_history"

# --- 事件/信号 ---
SIGNAL_VEHICLE_ADDED: Final = f"{DOMAIN}_vehicle_added"
SIGNAL_VEHICLE_REMOVED: Final = f"{DOMAIN}_vehicle_removed"

# --- 数据源 ---
BASE_URL: Final = "https://cx.sinopecsales.com"
PAGE_URL: Final = "https://cx.sinopecsales.com/yjkqiantai/core/initCpb"
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- 省份列表 {provinceId: 名称} ---
PROVINCES: Final[dict[str, str]] = {
    "11": "北京",
    "12": "天津",
    "13": "河北",
    "14": "山西",
    "41": "河南",
    "37": "山东",
    "31": "上海",
    "32": "江苏",
    "33": "浙江",
    "34": "安徽",
    "35": "福建",
    "36": "江西",
    "42": "湖北",
    "43": "湖南",
    "44": "广东",
    "45": "广西",
    "53": "云南",
    "52": "贵州",
    "46": "海南",
    "50": "重庆",
    "51": "四川",
    "65": "新疆",
    "15": "内蒙古",
    "21": "辽宁",
    "22": "吉林",
    "64": "宁夏",
    "61": "陕西",
    "23": "黑龙江",
    "54": "西藏",
    "63": "青海",
    "62": "甘肃",
}

# --- 油品映射：{开关键(check): (数据字段(data), 显示名称)} ---
OIL_TYPE_MAP: Final[dict[str, tuple[str, str]]] = {
    "GAS_89": ("GAS_89", "89号汽油"),
    "GAS_92": ("GAS_92", "92号汽油"),
    "GAS_95": ("GAS_95", "95号汽油"),
    "GAS_98": ("GAS_98", "98号汽油"),
    "E92": ("E92", "92号乙醇汽油"),
    "E95": ("E95", "95号乙醇汽油"),
    "E98": ("E98", "98号乙醇汽油"),
    "AIPAO92": ("AIPAO_GAS_92", "爱跑92号汽油"),
    "AIPAO95": ("AIPAO_GAS_95", "爱跑95号汽油"),
    "AIPAO98": ("AIPAO_GAS_98", "爱跑98号汽油"),
    "AIPAOE92": ("AIPAO_GAS_E92", "爱跑92号乙醇汽油"),
    "AIPAOE95": ("AIPAO_GAS_E95", "爱跑95号乙醇汽油"),
    "AIPAOE98": ("AIPAO_GAS_E98", "爱跑98号乙醇汽油"),
    "CHAI_0": ("CHECHAI_0", "0号柴油"),
    "CHAI_10": ("CHECHAI_10", "-10号柴油"),
    "CHAI_20": ("CHAI_20", "-20号柴油"),
    "CHAI_35": ("CHAI_35", "-35号柴油"),
    "CHAI_ZYK": ("CHAI_ZYK", "专用柴油"),
    "LNG": ("LNG", "LNG天然气"),
    "CNG": ("CNG", "CNG天然气"),
    "L_CNG": ("L_CNG", "L-CNG天然气"),
}

# --- 数据字段名 → 中文标签（OIL_TYPE_MAP 的反向映射） ---
# 历史油价等结构化数据一律使用数据字段名（GAS_92 等）作为 key，
# 保证前端/自动化取值稳定；展示时再用本表转成中文。
OIL_TYPE_LABELS: Final[dict[str, str]] = {
    data_key: label for _, (data_key, label) in OIL_TYPE_MAP.items()
}

# --- 全部数据字段名集合（用于从接口原始行中挑出油价字段） ---
OIL_DATA_KEYS: Final[frozenset[str]] = frozenset(OIL_TYPE_LABELS)

# --- 常用油品别名 → 候选数据字段（按优先级） ---
# 用于把用户输入的 "92"/"95"/"0#"/"柴油" 等映射到实际数据字段
FUEL_TYPE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "89": ("GAS_89",),
    "92": ("GAS_92", "AIPAO_GAS_92", "E92", "AIPAO_GAS_E92"),
    "95": ("GAS_95", "AIPAO_GAS_95", "E95", "AIPAO_GAS_E95"),
    "98": ("GAS_98", "AIPAO_GAS_98", "E98", "AIPAO_GAS_E98"),
    "0": ("CHECHAI_0",),
    "0号": ("CHECHAI_0",),
    "柴油": ("CHECHAI_0",),
    "-10": ("CHECHAI_10",),
    "-20": ("CHAI_20",),
    "-35": ("CHAI_35",),
    "lng": ("LNG",),
    "cng": ("CNG",),
    "l-cng": ("L_CNG",),
}
