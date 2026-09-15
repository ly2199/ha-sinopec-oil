"""The Sinopec Oil Price integration.

功能：
- 查询中石化"今日油价"（按省份配置）
- 记录加油量、行驶里程（服务调用）
- 自动计算加油费用、平均油耗、每公里费用等统计
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import SinopecOilApiClient
from .const import (
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

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sinopec Oil Price from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    # 全局共享的加油记录存储（仅初始化一次）
    store: RefuelStore | None = domain_data.get("store")
    if store is None:
        store = RefuelStore(hass)
        await store.async_load()
        domain_data["store"] = store

    # 油价客户端与协调器（options 中修改过的省份优先）
    province = (
        entry.options.get(CONF_PROVINCE)
        or entry.data.get(CONF_PROVINCE, DEFAULT_PROVINCE)
    )
    scan_minutes = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
    )
    client = SinopecOilApiClient(province)
    price_coordinator = SinopecOilPriceCoordinator(
        hass, client, scan_minutes * 60
    )
    await price_coordinator.async_config_entry_first_refresh()

    # 加油统计协调器（服务调用时刷新）
    refuel_coordinator = RefuelStatsCoordinator(hass, store)
    await refuel_coordinator.async_refresh()

    entry.runtime_data = SinopecOilRuntimeData(
        price_coordinator=price_coordinator,
        refuel_coordinator=refuel_coordinator,
        store=store,
    )

    # 注册服务（全局仅一次）
    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 选项（省份/刷新间隔）变化后自动重载
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

    return True
