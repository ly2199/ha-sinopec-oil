"""Sensors for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SIGNAL_VEHICLE_ADDED,
    SIGNAL_VEHICLE_REMOVED,
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
    """Set up Sinopec Oil Price sensors from a config entry."""
    runtime: SinopecOilRuntimeData = entry.runtime_data
    price_coordinator = runtime.price_coordinator
    refuel_coordinator = runtime.refuel_coordinator
    store = runtime.store

    # --- 油价实体 ---
    oil = price_coordinator.data
    entities: list[SensorEntity] = [
        OilPriceUpdateSensor(price_coordinator, entry.entry_id),
        OilPricePeriodEndSensor(price_coordinator, entry.entry_id),
    ]
    if oil is not None:
        for key in oil.prices:
            entities.append(OilPriceSensor(price_coordinator, entry.entry_id, key))
    async_add_entities(entities)

    # --- 加油统计实体（支持运行中新增/删除车辆） ---
    registry = er.async_get(hass)
    known_vehicles: set[str] = set()

    @callback
    def _add_vehicle_entities(vehicle: Any = None) -> None:
        """Add statistics entities for new vehicles.

        vehicle 为 None 时扫描全部车辆（初始安装）；
        否则仅处理信号传入的单个车辆。
        """
        if vehicle is None:
            vehicles = list(store.vehicles.keys())
        else:
            vehicles = [vehicle]
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
                VehicleLastRefuelDateSensor,
                VehicleRecentRecordSensor,
                VehicleQualitySensor,
            ):
                unique_id = f"{DOMAIN}_vehicle_{vehicle_name}_{cls.STAT_KEY}"
                # 全局唯一 ID：仅当未被其他实例注册时创建
                if registry.async_is_registered(unique_id):
                    _LOGGER.debug(
                        "跳过已注册实体 %s（由其他实例管理）", unique_id
                    )
                    continue
                if cls in (VehicleRecentRecordSensor, VehicleQualitySensor):
                    new_entities.append(
                        cls(refuel_coordinator, vehicle_name, store)
                    )
                else:
                    new_entities.append(
                        cls(refuel_coordinator, vehicle_name)
                    )
        if new_entities:
            async_add_entities(new_entities)

    @callback
    def _remove_vehicle_entities(vehicle: str) -> None:
        """Remove statistics entities of a deleted vehicle."""
        known_vehicles.discard(vehicle)
        # 通过 unique_id 找到并删除该车的实体
        for stat_key in (
            "odometer", "total_volume", "total_cost", "total_distance",
            "last_consumption", "avg_consumption", "avg_price",
            "per_km_cost", "refuel_count", "last_record_date",
            "recent_record", "data_quality",
        ):
            uid = f"{DOMAIN}_vehicle_{vehicle}_{stat_key}"
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, uid)
            if entity_id:
                registry.async_remove(entity_id)

    _add_vehicle_entities()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_VEHICLE_ADDED, _add_vehicle_entities
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_VEHICLE_REMOVED, _remove_vehicle_entities
        )
    )


def _oil_device(entry_id: str, location_name: str) -> DeviceInfo:
    """Return device info for oil price sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_oil_price")},
        name=f"中石化今日油价（{location_name}）",
        manufacturer=MANUFACTURER,
        model="今日油价查询",
    )


class OilPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for one oil type price."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gas-station"
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

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
        oil = coordinator.data
        self._attr_device_info = _oil_device(
            entry_id, oil.display_name
        )

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this key."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._key in self.coordinator.data.prices
        )

    @property
    def name(self) -> str | None:
        oil = self.coordinator.data
        if oil is None:
            return None
        return oil.labels.get(self._key, self._key)

    @property
    def native_value(self) -> float | None:
        oil = self.coordinator.data
        if oil is None:
            return None
        return oil.prices.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self.coordinator.data
        attrs: dict[str, Any] = {
            "location": oil.display_name if oil else None,
            "source": "https://cx.sinopecsales.com/yjkqiantai/core/initCpb",
            "sinopec_role": "sinopec_price",
        }
        if oil:
            attrs["label"] = oil.labels.get(self._key, self._key)
            attrs["date"] = oil.to_day
            attrs["updated_at"] = oil.update_time
            change = oil.changes.get(self._key)
            if change is not None:
                attrs["price_change"] = change
        return attrs


class OilPriceUpdateSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the oil price update time."""

    _attr_has_entity_name = True
    _attr_name = "油价更新时间"
    _attr_icon = "mdi:calendar-clock"
    _attr_unique_id_prefix = "oil_updated"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_oil_updated"
        oil = coordinator.data
        location = oil.display_name if oil else "未知"
        self._attr_device_info = _oil_device(entry_id, location)

    @property
    def native_value(self) -> str | None:
        oil = self.coordinator.data
        return oil.update_time if oil else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributes incl. recent price-change history."""
        oil = self.coordinator.data
        attrs: dict[str, Any] = {
            "date": oil.to_day if oil else None,
            "location": oil.display_name if oil else None,
            "sinopec_role": "sinopec_price_history",
        }
        if oil and oil.price_history:
            # 历史调价周期（完整数据，最近 6 期在前的为当前与相邻周期）
            attrs["price_history"] = oil.price_history
            current = oil.price_history[0] if oil.price_history else None
            if current:
                attrs["current_period"] = (
                    f"{current['start']} ~ {current['end']}"
                )
        return attrs


class OilPricePeriodEndSensor(CoordinatorEntity, SensorEntity):
    """当前调价周期结束日（下次调价参考日）。"""

    _attr_has_entity_name = True
    _attr_name = "调价周期结束日"
    _attr_icon = "mdi:calendar-end"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_oil_period_end"
        oil = coordinator.data
        location = oil.display_name if oil else "未知"
        self._attr_device_info = _oil_device(entry_id, location)

    @property
    def available(self) -> bool:
        oil = self.coordinator.data
        return (
            super().available
            and oil is not None
            and bool(oil.price_history)
        )

    @property
    def native_value(self):
        oil = self.coordinator.data
        if oil is None or not oil.price_history:
            return None
        end = str(oil.price_history[0].get("end", ""))
        try:
            return dt_date.fromisoformat(end)
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self.coordinator.data
        attrs: dict[str, Any] = {
            "sinopec_role": "sinopec_period_end",
        }
        if oil is not None and oil.price_history:
            current = oil.price_history[0]
            attrs["current_period"] = (
                f"{current.get('start')} ~ {current.get('end')}"
            )
            try:
                days = (
                    dt_date.fromisoformat(str(current.get("end")))
                    - dt_date.today()
                ).days
                attrs["days_left"] = days
            except (ValueError, TypeError):
                pass
        return attrs


def _vehicle_device(vehicle: str) -> DeviceInfo:
    """Return device info for one vehicle."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"vehicle_{vehicle}")},
        name=f"加油记录（{vehicle}）",
        manufacturer=MANUFACTURER,
        model="油耗统计",
    )


class VehicleStatsSensor(CoordinatorEntity, SensorEntity):
    """Base class for vehicle refuel statistics sensors."""

    _attr_has_entity_name = True
    STAT_KEY: str = ""
    STAT_NAME: str = ""

    def __init__(
        self,
        coordinator: RefuelStatsCoordinator,
        vehicle: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._vehicle = vehicle
        self._attr_unique_id = f"{DOMAIN}_vehicle_{vehicle}_{self.STAT_KEY}"
        self._attr_device_info = _vehicle_device(vehicle)

    @property
    def name(self) -> str:
        return self.STAT_NAME

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self._vehicle in self.coordinator.data
        )

    def _stats(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return data.get(self._vehicle) or {}


class VehicleOdometerSensor(VehicleStatsSensor):
    """Current odometer reading."""

    STAT_KEY = "odometer"
    STAT_NAME = "当前里程表"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = UNIT_KM
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        return self._stats().get("odometer")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"vehicle": self._vehicle}


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
    """Total driving distance."""

    STAT_KEY = "total_distance"
    STAT_NAME = "累计行驶里程"
    _attr_icon = "mdi:map-marker-distance"
    _attr_native_unit_of_measurement = UNIT_KM
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_distance")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "record_period_distance": self._stats().get("record_distance"),
        }


class VehicleLastConsumptionSensor(VehicleStatsSensor):
    """Fuel consumption of the last refuel interval."""

    STAT_KEY = "last_consumption"
    STAT_NAME = "最近油耗"
    _attr_icon = "mdi:gas-pump"
    _attr_native_unit_of_measurement = UNIT_L_PER_100KM
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("last_consumption")


class VehicleAvgConsumptionSensor(VehicleStatsSensor):
    """Average fuel consumption."""

    STAT_KEY = "avg_consumption"
    STAT_NAME = "平均油耗"
    _attr_icon = "mdi:chart-line"
    _attr_native_unit_of_measurement = UNIT_L_PER_100KM
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("avg_consumption")


class VehicleAvgPriceSensor(VehicleStatsSensor):
    """Average fuel price paid."""

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


class VehicleLastRefuelDateSensor(VehicleStatsSensor):
    """Date of the last refuel."""

    STAT_KEY = "last_record_date"
    STAT_NAME = "最近加油日期"
    _attr_icon = "mdi:calendar"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> str | None:
        return self._stats().get("last_record_date")


class VehicleRecentRecordSensor(VehicleStatsSensor):
    """最近一次加油摘要；属性携带该车全部记录（供卡片渲染）。

    记录按时间序排列，index 与 delete/edit 服务的序号一致。
    """

    STAT_KEY = "recent_record"
    STAT_NAME = "最近加油"
    _attr_icon = "mdi:fuel"

    def __init__(
        self,
        coordinator: RefuelStatsCoordinator,
        vehicle: str,
        store,
    ) -> None:
        """Initialize with a store reference for record listing."""
        super().__init__(coordinator, vehicle)
        self._store = store

    @property
    def native_value(self) -> str | None:
        records = self._store.get_records_sorted(self._vehicle)
        if not records:
            return "暂无记录"
        rec = records[-1]
        parts = []
        if rec.get("volume") is not None:
            parts.append(f"{rec['volume']}L")
        if rec.get("total_cost") is not None:
            parts.append(f"{rec['total_cost']}元")
        if rec.get("price") is not None:
            parts.append(f"{rec['price']}元/L")
        return f"{str(rec.get('date', ''))[:10]} · " + (
            " · ".join(parts) if parts else "无明细"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = self._store.get_records_sorted(self._vehicle)
        items: list[dict[str, Any]] = []
        prev_odo = None
        for idx, rec in enumerate(records):
            odo = rec.get("odometer")
            seg_distance = None
            seg_consumption = None
            if odo is not None and prev_odo is not None:
                diff = float(odo) - float(prev_odo)
                if 0 < diff <= 900:
                    seg_distance = round(diff, 1)
                    if rec.get("volume"):
                        seg_consumption = round(
                            float(rec["volume"]) / diff * 100, 2
                        )
            items.append(
                {
                    "index": idx,
                    "date": rec.get("date"),
                    "odometer": odo,
                    "volume": rec.get("volume"),
                    "total_cost": rec.get("total_cost"),
                    "price": rec.get("price"),
                    "fuel_type": rec.get("fuel_type") or "",
                    "note": rec.get("note") or "",
                    "segment_distance": seg_distance,
                    "segment_consumption": seg_consumption,
                }
            )
            if odo is not None:
                prev_odo = float(odo)
        return {
            "vehicle": self._vehicle,
            "sinopec_role": "sinopec_records",
            "count": len(items),
            "records": items,
        }


class VehicleQualitySensor(VehicleStatsSensor):
    """数据质量：时间-里程一致性校验结果（必须修正才能算油耗）。"""

    STAT_KEY = "data_quality"
    STAT_NAME = "数据质量"
    _attr_icon = "mdi:check-circle"

    def __init__(
        self,
        coordinator: RefuelStatsCoordinator,
        vehicle: str,
        store,
    ) -> None:
        """Initialize with a store reference."""
        super().__init__(coordinator, vehicle)
        self._store = store

    @property
    def native_value(self) -> str:
        problems = self._stats().get("quality_problems") or []
        if not problems:
            return "正常"
        return f"需修正（{len(problems)} 项）"

    @property
    def icon(self) -> str:
        problems = self._stats().get("quality_problems") or []
        return "mdi:alert-circle" if problems else "mdi:check-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "vehicle": self._vehicle,
            "sinopec_role": "sinopec_quality",
            "problems": self._stats().get("quality_problems") or [],
        }
