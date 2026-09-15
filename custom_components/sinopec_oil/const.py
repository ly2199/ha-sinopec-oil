"""Constants for the Sinopec Oil Price integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sinopec_oil"
MANUFACTURER: Final = "Sinopec / 中国石化"

# --- 配置项 ---
CONF_PROVINCE: Final = "province"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_PROVINCE: Final = "11"  # 默认省份：北京（行政区划代码前两位）
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 60  # 默认每 60 分钟刷新一次油价

# --- 单位 ---
UNIT_YUAN_PER_LITER: Final = "元/L"
UNIT_YUAN: Final = "元"
UNIT_LITER: Final = "L"
UNIT_KM: Final = "km"
UNIT_L_PER_100KM: Final = "L/100km"
UNIT_YUAN_PER_KM: Final = "元/km"

# --- 服务 ---
SERVICE_RECORD_REFUEL: Final = "record_refuel"
SERVICE_CLEAR_VEHICLE: Final = "clear_vehicle_data"
SERVICE_REFRESH_OIL_PRICE: Final = "refresh_oil_price"

# --- 事件/信号 ---
SIGNAL_VEHICLE_ADDED: Final = f"{DOMAIN}_vehicle_added"

# --- 数据源 ---
BASE_URL: Final = "https://cx.sinopecsales.com"
PAGE_URL: Final = "https://cx.sinopecsales.com/yjkqiantai/core/initCpb"
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- 省份列表（来自中石化页面，provinceId 为行政区划代码前两位） ---
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
