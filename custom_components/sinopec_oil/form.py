"""Shared state and helpers for the built-in refuel form entities.

集成自带的"加油填表"设备：无需创建任何 helper 或自动化，仪表盘即可填表。
本模块只承载共享状态与设备信息，各平台实体见 button/number/select/text/datetime.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER

FORM_STATE_KEY = "form_state"
FORM_PLATFORMS_KEY = "form_platforms"
FORM_OWNER_KEY = "form_owner"

# 常用油品选项（"自动"= 使用车辆默认油品）
FUEL_OPTIONS: list[str] = [
    "自动",
    "92",
    "95",
    "98",
    "89",
    "0#",
    "-10",
    "-20",
    "-35",
    "LNG",
]


@dataclass
class FormState:
    """In-memory state of the refuel form (reset after each submission)."""

    vehicle: str | None = None
    odometer: float | None = None
    volume: float | None = None
    total_cost: float | None = None
    actual_payment: float | None = None
    fuel: str = "自动"
    when: datetime = field(default_factory=dt_util.now)
    note: str = ""

    def reset(self, now: datetime, odometer: float | None = None) -> None:
        """Clear inputs after a successful submission (keep the vehicle).

        `odometer` 为提交后预填的下一箱基线里程（当前读数）。
        """
        self.odometer = odometer
        self.volume = None
        self.total_cost = None
        self.actual_payment = None
        self.fuel = "自动"
        self.when = now
        self.note = ""


def get_form_state(hass: HomeAssistant) -> FormState:
    """Return (and lazily create) the global form state."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    state = domain_data.get(FORM_STATE_KEY)
    if state is None:
        state = FormState()
        domain_data[FORM_STATE_KEY] = state
    return state


def claim_form_platform(
    hass: HomeAssistant, entry_id: str, platform: str
) -> bool:
    """Claim the right to create one platform's form entities.

    填表是跨配置项的单例（共享 FormState 与「加油填表」设备），每个平台
    只应创建一次。返回 False 表示该平台已由其他配置项创建，本次跳过。
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    claimed: set[str] = domain_data.setdefault(FORM_PLATFORMS_KEY, set())
    if platform in claimed:
        return False
    claimed.add(platform)
    domain_data[FORM_OWNER_KEY] = entry_id
    return True


def release_form_platforms(hass: HomeAssistant, entry_id: str) -> bool:
    """Drop form ownership when the owning entry unloads.

    返回 True 表示卸载的正是表单所有者，调用方需让其他实例接管重建。
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(FORM_OWNER_KEY) != entry_id:
        return False
    domain_data.pop(FORM_OWNER_KEY, None)
    domain_data.pop(FORM_PLATFORMS_KEY, None)
    return True


def form_device() -> DeviceInfo:
    """Device info for the refuel form entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, "refuel_form")},
        name="加油填表",
        manufacturer=MANUFACTURER,
        model="加油记录表单",
    )


def build_service_data(state: FormState) -> dict[str, Any] | None:
    """Assemble record_refuel service data from the form state.

    返回 None 表示缺少必填信息（车辆为空，或加油量/加油费用/实际支付均未填写；
    里程表读数可选——表单会自动预填当前读数，服务端也支持沿用上次）。

    加油费用与实际支付分列两个输入：只填其中一个时，服务端按"无优惠"处理；
    两个都填则自动计算优惠 = 加油费用 - 实际支付。
    """
    vehicle = (state.vehicle or "").strip()
    if not vehicle:
        return None
    if (
        state.volume is None
        and state.total_cost is None
        and state.actual_payment is None
    ):
        return None

    data: dict[str, Any] = {"vehicle": vehicle}
    if state.odometer is not None:
        data["odometer"] = state.odometer
    if state.volume is not None:
        data["volume"] = state.volume
    if state.total_cost is not None:
        data["total_cost"] = state.total_cost
    if state.actual_payment is not None:
        data["actual_payment"] = state.actual_payment
    if state.fuel and state.fuel != "自动":
        data["fuel_type"] = state.fuel
    data["date"] = state.when
    if state.note:
        data["note"] = state.note
    return data
