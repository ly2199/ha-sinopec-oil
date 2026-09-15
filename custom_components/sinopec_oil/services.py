"""Services for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_DATE
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SERVICE_CLEAR_VEHICLE,
    SERVICE_RECORD_REFUEL,
    SERVICE_REFRESH_OIL_PRICE,
    SIGNAL_VEHICLE_ADDED,
)
from .coordinator import SinopecOilRuntimeData

_LOGGER = logging.getLogger(__name__)

ATTR_VEHICLE = "vehicle"
ATTR_ODOMETER = "odometer"
ATTR_VOLUME = "volume"
ATTR_TOTAL_COST = "total_cost"
ATTR_PRICE = "price"
ATTR_FUEL_TYPE = "fuel_type"
ATTR_NOTE = "note"

RECORD_REFUEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Required(ATTR_ODOMETER): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Required(ATTR_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0.01)
        ),
        vol.Optional(ATTR_TOTAL_COST): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_PRICE): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_FUEL_TYPE, default=""): cv.string,
        vol.Optional(ATTR_DATE): cv.datetime,
        vol.Optional(ATTR_NOTE, default=""): cv.string,
    }
)

CLEAR_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
    }
)


@callback
def _get_runtime_datas(hass: HomeAssistant) -> list[SinopecOilRuntimeData]:
    """Return runtime data of all loaded entries."""
    domain_data = hass.data.get(DOMAIN, {})
    return [
        value
        for key, value in domain_data.items()
        if isinstance(key, str)
        and key != "store"
        and isinstance(value, SinopecOilRuntimeData)
    ]


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services (only once)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    def _get_store(call: ServiceCall):
        store = hass.data.get(DOMAIN, {}).get("store")
        if store is None:
            raise HomeAssistantError("加油记录存储未初始化")
        return store

    async def async_handle_record_refuel(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Handle the record_refuel service call."""
        store = _get_store(call)
        data = call.data

        vehicle = data[ATTR_VEHICLE].strip()
        if not vehicle:
            raise HomeAssistantError("vehicle（车辆）不能为空")

        volume = float(data[ATTR_VOLUME])
        total_cost = data.get(ATTR_TOTAL_COST)
        price = data.get(ATTR_PRICE)

        if total_cost is None and price is None:
            raise HomeAssistantError(
                "total_cost（加油费用）与 price（单价）至少填写一项；"
                "都不填时可使用服务响应中的实时油价"
            )

        if total_cost is None:
            total_cost = round(price * volume, 2)
        if price is None:
            price = round(total_cost / volume, 4) if volume else None

        when: datetime = data.get(ATTR_DATE) or dt_util.now()

        record: dict[str, Any] = {
            "date": when.isoformat(timespec="seconds"),
            "odometer": float(data[ATTR_ODOMETER]),
            "volume": volume,
            "total_cost": float(total_cost),
            "price": price,
            "fuel_type": data.get(ATTR_FUEL_TYPE) or "",
            "note": data.get(ATTR_NOTE) or "",
        }

        result = await store.async_add_record(vehicle, record)

        # 触发统计实体刷新 & 通知新车辆
        for runtime in _get_runtime_datas(hass):
            hass.async_create_task(
                runtime.refuel_coordinator.async_request_refresh()
            )
        if result.get("new_vehicle"):
            async_dispatcher_send(hass, SIGNAL_VEHICLE_ADDED, vehicle)

        _LOGGER.info(
            "已记录加油：车辆=%s 里程=%.1f km 加油量=%.2f L 费用=%.2f 元",
            vehicle,
            record["odometer"],
            volume,
            record["total_cost"],
        )
        return result

    async def async_handle_clear_vehicle(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Handle the clear_vehicle_data service call."""
        store = _get_store(call)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        existed = await store.async_clear_vehicle(vehicle)
        if not existed:
            raise HomeAssistantError(f"车辆 '{vehicle}' 不存在")
        for runtime in _get_runtime_datas(hass):
            hass.async_create_task(
                runtime.refuel_coordinator.async_request_refresh()
            )
        _LOGGER.info("已清除车辆加油记录：%s", vehicle)
        return {"vehicle": vehicle, "cleared": True}

    async def async_handle_refresh_oil_price(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Handle the refresh_oil_price service call."""
        refreshed = 0
        for runtime in _get_runtime_datas(hass):
            await runtime.price_coordinator.async_request_refresh()
            refreshed += 1
        return {"refreshed_entries": refreshed}

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECORD_REFUEL,
        async_handle_record_refuel,
        schema=RECORD_REFUEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_VEHICLE,
        async_handle_clear_vehicle,
        schema=CLEAR_VEHICLE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_OIL_PRICE,
        async_handle_refresh_oil_price,
        supports_response=SupportsResponse.OPTIONAL,
    )
    domain_data["services_registered"] = True


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when the last entry is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_RECORD_REFUEL)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_VEHICLE)
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_OIL_PRICE)
    hass.data.setdefault(DOMAIN, {})["services_registered"] = False
