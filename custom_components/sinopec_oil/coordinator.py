"""Data update coordinators for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    OilPriceData,
    SinopecOilApiClient,
    SinopecOilApiClientError,
)
from .const import DOMAIN
from .store import RefuelStore

_LOGGER = logging.getLogger(__name__)


class SinopecOilPriceCoordinator(DataUpdateCoordinator[OilPriceData]):
    """Coordinator that polls oil prices for one province/area."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SinopecOilApiClient,
        scan_interval_seconds: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} oil price ({client.province_name})",
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client

    async def _async_update_data(self) -> OilPriceData:
        """Fetch the latest oil prices."""
        try:
            return await self.client.async_get_oil_prices()
        except SinopecOilApiClientError as err:
            raise UpdateFailed(f"获取油价失败: {err}") from err


class RefuelStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for refuel statistics (not polled; refreshed on demand)."""

    def __init__(self, hass: HomeAssistant, store: RefuelStore) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} refuel stats",
            update_interval=None,  # 不轮询，由服务调用触发刷新
        )
        self.store = store

    async def _async_update_data(self) -> dict[str, Any]:
        """Compute statistics for all vehicles."""
        return {
            vehicle: self.store.get_stats(vehicle)
            for vehicle in self.store.vehicles
        }


@dataclass
class SinopecOilRuntimeData:
    """Runtime data stored on config entry."""

    price_coordinator: SinopecOilPriceCoordinator
    refuel_coordinator: RefuelStatsCoordinator
    store: RefuelStore
