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
    fuel: str = "自动"
    when: datetime = field(default_factory=dt_util.now)
    note: str = ""

    def reset(self, now: datetime) -> None:
        """Clear inputs after a successful submission (keep the vehicle)."""
        self.odometer = None
        self.volume = None
        self.total_cost = None
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

    返回 None 表示缺少必填信息（车辆为空，或里程/量/费全空）。
    """
    vehicle = (state.vehicle or "").strip()
    if not vehicle:
        return None
    if (
        state.odometer is None
        and state.volume is None
        and state.total_cost is None
    ):
        return None

    data: dict[str, Any] = {"vehicle": vehicle}
    if state.odometer is not None:
        data["odometer"] = state.odometer
    if state.volume is not None:
        data["volume"] = state.volume
    if state.total_cost is not None:
        data["total_cost"] = state.total_cost
    if state.fuel and state.fuel != "自动":
        data["fuel_type"] = state.fuel
    data["date"] = state.when
    if state.note:
        data["note"] = state.note
    return data
