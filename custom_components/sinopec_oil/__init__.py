"""The Sinopec Oil Price integration.

功能：
- 查询中石化"今日油价"（省份 + 价区两级配置）
- 车辆管理：初始里程、常用油品、多车独立维护
- 记录加油量、行驶里程，按当日/历史油价智能计算加油量与费用
- 自动计算加油费用、平均油耗、每公里费用等统计
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import SinopecOilApiClient
from .const import (
    CONF_AREA,
    CONF_PROVINCE,
    CONF_SCAN_INTERVAL,
    DEFAULT_PROVINCE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .coordinator import (
    RefuelStatsCoordinator,
    SinopecOilPriceCoordinator,
    SinopecOilRuntimeData,
)
from .services import async_setup_services, async_unload_services
from .store import RefuelStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
    Platform.DATETIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sinopec Oil Price from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    # 全局共享的加油记录存储（仅初始化一次）
    store: RefuelStore | None = domain_data.get("store")
    if store is None:
        store = RefuelStore(hass)
        await store.async_load()
        domain_data["store"] = store

    # 油价客户端与协调器（options 中修改过的省份/价区优先）
    province = (
        entry.options.get(CONF_PROVINCE)
        or entry.data.get(CONF_PROVINCE, DEFAULT_PROVINCE)
    )
    area_id = (
        entry.options.get(CONF_AREA)
        or entry.data.get(CONF_AREA)
    )
    scan_minutes = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
    )
    client = SinopecOilApiClient(province, area_id=area_id)
    price_coordinator = SinopecOilPriceCoordinator(
        hass, client, scan_minutes * 60
    )
    # 获取初始数据，失败则稍后重试
    await price_coordinator.async_config_entry_first_refresh()

    refuel_coordinator = RefuelStatsCoordinator(hass, store)
    await refuel_coordinator.async_refresh()

    entry.runtime_data = SinopecOilRuntimeData(
        price_coordinator=price_coordinator,
        refuel_coordinator=refuel_coordinator,
        store=store,
    )
    domain_data[entry.entry_id] = entry

    await async_setup_services(hass)

    # 处理初始配置时创建的第一辆车（config flow 暂存）
    pending_vehicle = domain_data.pop("pending_vehicle", None)
    if pending_vehicle:
        created = await store.async_add_vehicle(
            pending_vehicle["name"],
            initial_odometer=pending_vehicle.get("initial_odometer"),
            fuel_type=pending_vehicle.get("fuel_type") or "92",
        )
        if created:
            from homeassistant.helpers.dispatcher import (
                async_dispatcher_send,
            )

            from .const import SIGNAL_VEHICLE_ADDED

            async_dispatcher_send(
                hass, SIGNAL_VEHICLE_ADDED, pending_vehicle["name"]
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)

    runtime = entry.runtime_data
    if isinstance(runtime, SinopecOilRuntimeData):
        await runtime.price_coordinator.client.async_close()

    # 若没有其他已加载实例，注销服务并清理共享存储引用
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        async_unload_services(hass)
        domain_data.pop("store", None)
        domain_data.pop("form_created", None)
        domain_data.pop("form_state", None)

    return True
