"""Submit button of the built-in refuel form."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SERVICE_RECORD_REFUEL,
    SIGNAL_VEHICLE_ADDED,
    SIGNAL_VEHICLE_REMOVED,
)
from .coordinator import SinopecOilRuntimeData
from .form import build_service_data, form_device, get_form_state

_LOGGER = logging.getLogger(__name__)

SIGNAL_FORM_SUBMITTED = f"{DOMAIN}_form_submitted"


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the submit button (only once across entries)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("form_created"):
        return
    domain_data["form_created"] = True
    runtime: SinopecOilRuntimeData = entry.runtime_data
    async_add_entities([RefuelSubmitButton(hass, runtime)])


class RefuelSubmitButton(CoordinatorEntity, ButtonEntity):
    """提交按钮：读取表单实体当前值，调用智能计价服务并通知结果。"""

    _attr_has_entity_name = True
    _attr_name = "提交加油记录"
    _attr_icon = "mdi:fuel"
    _attr_unique_id = "refuel_form_submit"

    def __init__(self, hass: HomeAssistant, runtime: SinopecOilRuntimeData) -> None:
        """Initialize the button."""
        super().__init__(runtime.refuel_coordinator)
        self.hass = hass
        self._runtime = runtime
        self._attr_device_info = form_device()

    async def async_added_to_hass(self) -> None:
        """Refresh the vehicle dropdown when vehicles change."""
        await super().async_added_to_hass()
        for sig in (SIGNAL_VEHICLE_ADDED, SIGNAL_VEHICLE_REMOVED):
            self.async_on_remove(
                async_dispatcher_connect(self.hass, sig, self._refresh)
            )

    @property
    def available(self) -> bool:
        """Available when at least one vehicle exists."""
        return bool(self._runtime.store.vehicles)

    async def _refresh(self, *_args) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Validate, record via the smart service, notify and reset."""
        state = get_form_state(self.hass)
        store = self._runtime.store

        # 只有一辆车时自动补全并预填里程（不覆盖用户已填的值）
        if not state.vehicle and len(store.vehicles) == 1:
            state.vehicle = next(iter(store.vehicles))
            if state.odometer is None:
                state.odometer = store.get_current_odometer(state.vehicle)

        data = build_service_data(state)
        if not data or (state.vehicle or "") not in store.vehicles:
            if not store.vehicles:
                await self._notify(
                    "⛔ 加油填表", "还没有车辆。请先在集成选项中添加车辆。"
                )
            elif state.volume is None and state.total_cost is None:
                hint = "请至少填写加油量或费用之一（都填则自动算单价）。"
                if state.odometer is not None:
                    hint += "里程表读数已自动带出，无需重复填写。"
                await self._notify("⛔ 加油填表", hint)
            else:
                await self._notify(
                    "⛔ 加油填表",
                    "请先在「加油填表 · 车辆」下拉中选择车辆。",
                )
            return

        try:
            response = await self.hass.services.async_call(
                DOMAIN,
                SERVICE_RECORD_REFUEL,
                service_data=data,
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - 面向用户的统一错误提示
            _LOGGER.exception("加油填表提交失败")
            await self._notify("⛔ 加油记录失败", str(err))
            return

        lines = ["✅ 已记录加油"]
        if response:
            volume = response.get("volume")
            cost = response.get("total_cost")
            price = response.get("price")
            source = response.get("price_source")
            approx = response.get("price_approximate")
            lines.append(
                f"加油量：{volume} L" if volume is not None else "加油量：—"
            )
            lines.append(f"费用：{cost} 元" if cost is not None else "费用：—")
            if price is not None:
                mark = "（约）" if approx else ""
                lines.append(f"单价：{price} 元/L{mark}")
            if source:
                lines.append(f"计价来源：{source}")
            if response.get("distance_since_last") is not None:
                lines.append(
                    f"区间里程：{response['distance_since_last']} km"
                )
            if response.get("consumption_last") is not None:
                lines.append(
                    f"最近油耗：{response['consumption_last']} L/100km"
                )
        await self._notify("⛽ 加油记录", "\n".join(lines))

        # 重置表单（保留车辆选择；里程预填该车当前读数，作为下一箱基线）
        state.reset(
            dt_util.now(),
            odometer=store.get_current_odometer(state.vehicle),
        )
        async_dispatcher_send(self.hass, SIGNAL_FORM_SUBMITTED)

    async def _notify(self, title: str, message: str) -> None:
        """Show a persistent notification."""
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": title, "message": message},
        )
