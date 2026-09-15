"""Sensors for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SIGNAL_VEHICLE_ADDED,
    UNIT_KM,
    UNIT_L_PER_100KM,
    UNIT_LITER,
    UNIT_YUAN,
    UNIT_YUAN_PER_KM,
    UNIT_YUAN_PER_LITER,
)
from .coordinator import RefuelStatsCoordinator, SinopecOilRuntimeData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    runtime: SinopecOilRuntimeData = entry.runtime_data
    price_coordinator = runtime.price_coordinator
    refuel_coordinator = runtime.refuel_coordinator

    entities: list[SensorEntity] = [
        OilPriceUpdateSensor(price_coordinator, entry.entry_id)
    ]
    for key in price_coordinator.data.prices:
        entities.append(OilPriceSensor(price_coordinator, entry.entry_id, key))
    async_add_entities(entities)

    # --- 加油统计实体（支持运行中新增车辆） ---
    registry = er.async_get(hass)

    @callback
    def _add_vehicle_entities(vehicle: Any = None) -> None:
        """Add statistics entities for new vehicles.

        vehicle 为 None 时扫描全部车辆（初始安装）；
        否则仅处理信号传入的单个车辆。
        """
        if vehicle is None:
            vehicles = list((refuel_coordinator.data or {}).keys())
        else:
            vehicles = [vehicle]
        known_vehicles: set[str] = getattr(
            _add_vehicle_entities, "_known", set()
        )
        new_entities: list[SensorEntity] = []
        for vehicle_name in vehicles:
            if vehicle_name in known_vehicles:
                continue
            known_vehicles.add(vehicle_name)
            for cls in (
                VehicleOdometerSensor,
                VehicleTotalVolumeSensor,
                VehicleTotalCostSensor,
                VehicleTotalDistanceSensor,
                VehicleLastConsumptionSensor,
                VehicleAvgConsumptionSensor,
                VehicleAvgPriceSensor,
                VehiclePerKmCostSensor,
                VehicleRefuelCountSensor,
            ):
                unique_id = f"{DOMAIN}_{vehicle_name}_{cls.STAT_KEY}"
                # 全局唯一 ID：仅当未被其他实例注册时创建
                if registry.async_is_registered(unique_id):
                    _LOGGER.debug(
                        "跳过已注册实体 %s（由其他实例管理）", unique_id
                    )
                    continue
                new_entities.append(
                    cls(refuel_coordinator, entry.entry_id, vehicle_name)
                )
        setattr(_add_vehicle_entities, "_known", known_vehicles)
        if new_entities:
            async_add_entities(new_entities)

    _add_vehicle_entities()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_VEHICLE_ADDED, _add_vehicle_entities
        )
    )


def _oil_device(entry_id: str, province_name: str) -> DeviceInfo:
    """Return device info for oil price sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_oil_price")},
        name=f"中石化今日油价（{province_name}）",
        manufacturer=MANUFACTURER,
        model="今日油价查询",
    )


class OilPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for one oil type price."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gas-station"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER

    def __init__(
        self,
        coordinator,
        entry_id: str,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry_id}_oil_{key}"
        self._attr_name = coordinator.data.labels.get(key, key)
        province = coordinator.data.province_name
        self._attr_device_info = _oil_device(entry_id, province)

    @property
    def native_value(self) -> float | None:
        """Return the price."""
        return self.coordinator.data.prices.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            "province": data.province_name,
            "oil_type": self._key,
        }
        if (change := data.changes.get(self._key)) is not None:
            attrs["price_change"] = change
        if data.update_time:
            attrs["updated_at"] = data.update_time
        if data.to_day:
            attrs["date"] = data.to_day
        attrs["source"] = "中国石化 cx.sinopecsales.com"
        return attrs


class OilPriceUpdateSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing when the oil prices were last updated."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_oil_updated"
        self._attr_name = "油价更新时间"
        province = coordinator.data.province_name
        self._attr_device_info = _oil_device(entry_id, province)

    @property
    def native_value(self) -> str | None:
        """Return the update time text."""
        return self.coordinator.data.update_time or self.coordinator.data.to_day

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        data = self.coordinator.data
        return {
            "province": data.province_name,
            "date": data.to_day,
            "updated_at": data.update_time,
            "oil_types": [
                data.labels.get(k, k) for k in data.prices
            ],
        }


class VehicleStatsSensor(CoordinatorEntity, SensorEntity):
    """Base class for per-vehicle statistics sensors."""

    _attr_has_entity_name = True
    STAT_KEY: str = ""
    STAT_NAME: str = ""

    def __init__(
        self,
        coordinator: RefuelStatsCoordinator,
        entry_id: str,
        vehicle: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._vehicle = vehicle
        self._attr_unique_id = f"{DOMAIN}_{vehicle}_{self.STAT_KEY}"
        self._attr_name = self.STAT_NAME
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"refuel_{vehicle}")},
            name=f"加油记录（{vehicle}）",
            manufacturer=MANUFACTURER,
            model="加油记录与油耗统计",
        )

    def _stats(self) -> dict[str, Any]:
        """Return stats for this vehicle."""
        data = self.coordinator.data or {}
        return data.get(self._vehicle, {})

    @property
    def available(self) -> bool:
        """Available if the vehicle has stats."""
        return self.coordinator.last_update_success and bool(
            self._stats().get("refuel_count")
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        stats = self._stats()
        return {
            "vehicle": self._vehicle,
            "refuel_count": stats.get("refuel_count", 0),
            "last_record_date": stats.get("last_record_date"),
        }


class VehicleOdometerSensor(VehicleStatsSensor):
    """Latest odometer reading."""

    STAT_KEY = "odometer"
    STAT_NAME = "当前里程表"
    _attr_icon = "mdi:counter"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UNIT_KM
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        return self._stats().get("odometer")


class VehicleTotalVolumeSensor(VehicleStatsSensor):
    """Total refueled volume."""

    STAT_KEY = "total_volume"
    STAT_NAME = "累计加油量"
    _attr_icon = "mdi:fuel"
    _attr_native_unit_of_measurement = UNIT_LITER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_volume")


class VehicleTotalCostSensor(VehicleStatsSensor):
    """Total refuel cost."""

    STAT_KEY = "total_cost"
    STAT_NAME = "累计加油费用"
    _attr_icon = "mdi:cash-multiple"
    _attr_native_unit_of_measurement = UNIT_YUAN
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_cost")


class VehicleTotalDistanceSensor(VehicleStatsSensor):
    """Total driven distance between refuels."""

    STAT_KEY = "total_distance"
    STAT_NAME = "累计行驶里程"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UNIT_KM
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_distance")


class VehicleLastConsumptionSensor(VehicleStatsSensor):
    """Fuel consumption of the latest refuel interval."""

    STAT_KEY = "last_consumption"
    STAT_NAME = "最近油耗"
    _attr_icon = "mdi:chart-line"
    _attr_native_unit_of_measurement = UNIT_L_PER_100KM
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("last_consumption")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        attrs["last_distance"] = self._stats().get("last_distance")
        return attrs


class VehicleAvgConsumptionSensor(VehicleStatsSensor):
    """Average fuel consumption."""

    STAT_KEY = "avg_consumption"
    STAT_NAME = "平均油耗"
    _attr_icon = "mdi:chart-areaspline"
    _attr_native_unit_of_measurement = UNIT_L_PER_100KM
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("avg_consumption")


class VehicleAvgPriceSensor(VehicleStatsSensor):
    """Average fuel price (total cost / total volume)."""

    STAT_KEY = "avg_price"
    STAT_NAME = "平均油价"
    _attr_icon = "mdi:currency-cny"
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("avg_price")


class VehiclePerKmCostSensor(VehicleStatsSensor):
    """Fuel cost per kilometer."""

    STAT_KEY = "per_km_cost"
    STAT_NAME = "每公里油费"
    _attr_icon = "mdi:cash-check"
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_KM
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        return self._stats().get("per_km_cost")


class VehicleRefuelCountSensor(VehicleStatsSensor):
    """Number of refuel records."""

    STAT_KEY = "refuel_count"
    STAT_NAME = "加油次数"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "次"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> int | None:
        return self._stats().get("refuel_count")
