"""Sensors for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from datetime import date as dt_date, datetime, timedelta
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FUEL_TYPE_ALIASES,
    MANUFACTURER,
    PAGE_URL,
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

# 历史油价派生统计：{stat: (名称后缀, 单位, 图标)}
OIL_STAT_META: Final[dict[str, tuple[str, str | None, str]]] = {
    "max": ("24期最高价", UNIT_YUAN_PER_LITER, "mdi:arrow-up-bold-outline"),
    "min": ("24期最低价", UNIT_YUAN_PER_LITER, "mdi:arrow-down-bold-outline"),
    "avg": ("24期均价", UNIT_YUAN_PER_LITER, "mdi:chart-bell-curve"),
    "deviation": ("偏离均价", PERCENTAGE, "mdi:percent-outline"),
}


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
        OilLocationSensor(price_coordinator, entry.entry_id),
        OilPriceUpdateSensor(price_coordinator, entry.entry_id),
        OilServerTimeSensor(price_coordinator, entry.entry_id),
        OilPricePeriodEndSensor(price_coordinator, entry.entry_id),
        OilPriceNextChangeSensor(price_coordinator, entry.entry_id),
        OilPriceDaysToChangeSensor(price_coordinator, entry.entry_id),
        OilPricePeriodIdSensor(price_coordinator, entry.entry_id),
        OilPriceTrendSensor(price_coordinator, entry.entry_id),
    ]
    if oil is not None:
        for key in oil.prices:
            entities.append(OilPriceSensor(price_coordinator, entry.entry_id, key))
            entities.append(
                OilPriceChangeSensor(price_coordinator, entry.entry_id, key)
            )
            # 历史派生统计默认停用，用户在实体列表按需开启
            entities.extend(
                OilPriceStatSensor(
                    price_coordinator, entry.entry_id, key, stat
                )
                for stat in OIL_STAT_META
            )
        spread = _spread_keys(oil)
        if spread is not None:
            entities.append(
                OilPriceSpreadSensor(price_coordinator, entry.entry_id, spread)
            )
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
                VehicleTotalPaymentSensor,
                VehicleTotalDiscountSensor,
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
            "odometer", "total_volume", "total_cost", "total_payment",
            "total_discount", "total_distance",
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
        configuration_url=PAGE_URL,
    )


def _as_utc_datetime(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp into an aware UTC datetime.

    device_class=TIMESTAMP 的实体必须返回带时区的 datetime，
    返回字符串或 naive datetime 会被 HA 拒绝并记入日志。
    接口与存储中的时间均为本地时间（无时区），按 HA 时区解释。
    """
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(parsed)


def _trend_of(change: float) -> str:
    """涨跌方向。接口 _STATUS 带符号：正=上调，负=下调，0=搁浅。"""
    if change > 0:
        return "上调"
    if change < 0:
        return "下调"
    return "搁浅"


def _current_period(oil: Any) -> dict[str, Any] | None:
    """当前（最新）调价周期，无历史数据时返回 None。"""
    if oil is None or not oil.price_history:
        return None
    return oil.price_history[0]


def _period_end_date(oil: Any) -> dt_date | None:
    """当前调价周期的截止日。"""
    period = _current_period(oil)
    if period is None:
        return None
    try:
        return dt_date.fromisoformat(str(period.get("end")))
    except (TypeError, ValueError):
        return None


def _history_prices(oil: Any, key: str) -> list[float]:
    """某油品在全部历史调价周期中的价格。"""
    values: list[float] = []
    for period in getattr(oil, "price_history", None) or []:
        value = (period.get("prices") or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _spread_keys(oil: Any) -> tuple[str, str] | None:
    """(92号, 95号) 的数据字段名；任一未发布则返回 None。"""

    def pick(candidates: tuple[str, ...]) -> str | None:
        return next((c for c in candidates if c in oil.prices), None)

    low = pick(FUEL_TYPE_ALIASES["92"])
    high = pick(FUEL_TYPE_ALIASES["95"])
    if low is None or high is None or low == high:
        return None
    return (low, high)


class _OilSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for the sensors of one oil-price location."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, suffix: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_oil_{suffix}"
        oil = coordinator.data
        self._attr_device_info = _oil_device(
            entry_id, oil.display_name if oil else "未知"
        )

    @property
    def _oil(self) -> Any:
        """Latest parsed oil price data (None until the first update)."""
        return self.coordinator.data


class OilPriceSensor(_OilSensorBase):
    """Sensor for one oil type price."""

    _attr_icon = "mdi:gas-station"
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry_id: str, key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, key)
        self._key = key

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this key."""
        oil = self._oil
        return super().available and oil is not None and self._key in oil.prices

    @property
    def name(self) -> str | None:
        oil = self._oil
        if oil is None:
            return None
        return oil.labels.get(self._key, self._key)

    @property
    def native_value(self) -> float | None:
        oil = self._oil
        if oil is None:
            return None
        return oil.prices.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        attrs: dict[str, Any] = {
            "sinopec_role": "sinopec_price",
            # 稳定的数据字段名（GAS_92 等），卡片/自动化按此取值
            "fuel_key": self._key,
        }
        if oil:
            attrs["location"] = oil.display_name
            attrs["label"] = oil.labels.get(self._key, self._key)
            attrs["date"] = oil.to_day
            attrs["updated_at"] = oil.update_time
            attrs["period_id"] = oil.period_id
            change = oil.changes.get(self._key)
            if change is not None:
                attrs["price_change"] = change
                attrs["price_trend"] = _trend_of(change)
            history = _history_prices(oil, self._key)
            if history:
                attrs["period_high"] = max(history)
                attrs["period_low"] = min(history)
                attrs["period_avg"] = round(sum(history) / len(history), 2)
                attrs["period_count"] = len(history)
        return attrs


class OilPriceChangeSensor(_OilSensorBase):
    """某油品本期涨跌额（带符号：正=上调，负=下调，0=搁浅）。"""

    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry_id: str, key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, f"{key}_change")
        self._key = key

    @property
    def name(self) -> str | None:
        oil = self._oil
        if oil is None:
            return None
        return f"{oil.labels.get(self._key, self._key)} 涨跌额"

    @property
    def icon(self) -> str:
        change = self.native_value
        if change is None or change == 0:
            return "mdi:minus-circle-outline"
        return "mdi:trending-up" if change > 0 else "mdi:trending-down"

    @property
    def native_value(self) -> float | None:
        oil = self._oil
        if oil is None:
            return None
        return oil.changes.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        change = oil.changes.get(self._key) if oil else None
        attrs: dict[str, Any] = {"fuel_key": self._key}
        if oil:
            attrs["label"] = oil.labels.get(self._key, self._key)
            attrs["price"] = oil.prices.get(self._key)
        if change is not None:
            attrs["trend"] = _trend_of(change)
        return attrs


class OilPriceStatSensor(_OilSensorBase):
    """历史调价周期派生统计（最高/最低/均价/偏离），默认停用。"""

    _attr_entity_registry_enabled_default = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator, entry_id: str, key: str, stat: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, f"{key}_{stat}")
        self._key = key
        self._stat = stat
        suffix, unit, icon = OIL_STAT_META[stat]
        self._suffix = suffix
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def name(self) -> str | None:
        oil = self._oil
        if oil is None:
            return None
        return f"{oil.labels.get(self._key, self._key)} {self._suffix}"

    @property
    def native_value(self) -> float | None:
        oil = self._oil
        if oil is None:
            return None
        history = _history_prices(oil, self._key)
        if not history:
            return None
        if self._stat == "max":
            return max(history)
        if self._stat == "min":
            return min(history)
        avg = sum(history) / len(history)
        if self._stat == "avg":
            return round(avg, 2)
        current = oil.prices.get(self._key)
        if current is None or avg == 0:
            return None
        return round((current - avg) / avg * 100, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        history = _history_prices(oil, self._key) if oil else []
        return {
            "fuel_key": self._key,
            "stat": self._stat,
            "period_count": len(history),
        }


class OilPriceSpreadSensor(_OilSensorBase):
    """92 号与 95 号的价差（元/L）。"""

    _attr_name = "92/95 价差"
    _attr_icon = "mdi:compare-horizontal"
    _attr_native_unit_of_measurement = UNIT_YUAN_PER_LITER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator, entry_id: str, keys: tuple[str, str]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "spread")
        self._low_key, self._high_key = keys

    @property
    def native_value(self) -> float | None:
        oil = self._oil
        if oil is None:
            return None
        low = oil.prices.get(self._low_key)
        high = oil.prices.get(self._high_key)
        if low is None or high is None:
            return None
        return round(high - low, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        if oil is None:
            return {}
        return {
            "low_fuel": oil.labels.get(self._low_key, self._low_key),
            "high_fuel": oil.labels.get(self._high_key, self._high_key),
            "low_price": oil.prices.get(self._low_key),
            "high_price": oil.prices.get(self._high_key),
        }


class OilPriceTrendSensor(_OilSensorBase):
    """本期调价方向（上调/下调/搁浅）。"""

    _attr_name = "本期调价方向"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "trend")

    @property
    def icon(self) -> str:
        value = self.native_value
        if value == "上调":
            return "mdi:trending-up"
        if value == "下调":
            return "mdi:trending-down"
        if value == "搁浅":
            return "mdi:minus-circle-outline"
        return "mdi:trending-neutral"

    @property
    def native_value(self) -> str | None:
        oil = self._oil
        if oil is None or not oil.changes:
            return None
        # 国内成品油同批调价，各油品方向一致；取首个有数据的油品
        return _trend_of(next(iter(oil.changes.values())))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        if oil is None:
            return {}
        return {
            "sinopec_role": "sinopec_trend",
            "period_id": oil.period_id,
            # 各油品涨跌额（数据字段名 → 元/L，带符号）
            "changes": dict(oil.changes),
            "labels": {
                key: oil.labels.get(key, key) for key in oil.changes
            },
        }


class OilPricePeriodIdSensor(_OilSensorBase):
    """本期调价窗口期号（接口 PERIOD_ID）。"""

    _attr_name = "调价期号"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "period_id")

    @property
    def native_value(self) -> int | None:
        oil = self._oil
        return oil.period_id if oil else None


class OilLocationSensor(_OilSensorBase):
    """油价所在位置（省份/价区）及其官方说明。"""

    _attr_name = "油价位置"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "location")

    @property
    def native_value(self) -> str | None:
        oil = self._oil
        return oil.display_name if oil else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        if oil is None:
            return {}
        return {
            "province_id": oil.province_id,
            "province_name": oil.province_name,
            "area_id": oil.area_id,
            "area_name": oil.area_name,
            # 官方价区适用范围说明（如"适用于：昆明"）
            "area_desc": oil.area_desc,
            "date": oil.to_day,
            "fuels": [
                {"key": key, "label": oil.labels.get(key, key)}
                for key in oil.prices
            ],
            "source": PAGE_URL,
        }


class OilServerTimeSensor(_OilSensorBase):
    """接口服务器时间（判断油价数据新鲜度）。"""

    _attr_name = "接口服务器时间"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "server_time")

    @property
    def native_value(self) -> datetime | None:
        oil = self._oil
        return _as_utc_datetime(oil.server_time) if oil else None


class OilPriceUpdateSensor(_OilSensorBase):
    """Sensor for the oil price update time."""

    _attr_name = "油价更新时间"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "updated")

    @property
    def native_value(self) -> datetime | None:
        oil = self._oil
        return _as_utc_datetime(oil.update_time) if oil else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributes incl. recent price-change history."""
        oil = self._oil
        attrs: dict[str, Any] = {
            "date": oil.to_day if oil else None,
            "location": oil.display_name if oil else None,
            "sinopec_role": "sinopec_price_history",
        }
        if oil and oil.price_history:
            # 历史调价周期（按时间倒序，prices/changes 用数据字段名做 key）
            attrs["price_history"] = oil.price_history
            current = oil.price_history[0]
            attrs["current_period"] = (
                f"{current['start']} ~ {current['end']}"
            )
        return attrs


class OilPricePeriodEndSensor(_OilSensorBase):
    """当前调价周期结束日（下次调价参考日）。"""

    _attr_name = "调价周期结束日"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "period_end")

    @property
    def native_value(self) -> dt_date | None:
        return _period_end_date(self._oil)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oil = self._oil
        attrs: dict[str, Any] = {
            "sinopec_role": "sinopec_period_end",
        }
        period = _current_period(oil)
        if period is not None:
            attrs["current_period"] = (
                f"{period.get('start')} ~ {period.get('end')}"
            )
            attrs["period_id"] = period.get("period_id")
            end = _period_end_date(oil)
            if end is not None:
                attrs["days_left"] = (end - dt_util.now().date()).days
        return attrs


class OilPriceNextChangeSensor(_OilSensorBase):
    """下次调价生效日（周期结束日的次日 0 时生效）。"""

    _attr_name = "下次调价生效日"
    _attr_icon = "mdi:calendar-start"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "next_change")

    @property
    def native_value(self) -> dt_date | None:
        end = _period_end_date(self._oil)
        return end + timedelta(days=1) if end else None


class OilPriceDaysToChangeSensor(_OilSensorBase):
    """距下次调价的天数（0 = 今晚 24 时调价）。"""

    _attr_name = "距下次调价天数"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, "days_to_change")

    @property
    def native_value(self) -> int | None:
        end = _period_end_date(self._oil)
        if end is None:
            return None
        return max((end - dt_util.now().date()).days, 0)


def _vehicle_device(vehicle: str) -> DeviceInfo:
    """Return device info for one vehicle."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"vehicle_{vehicle}")},
        name=f"加油记录（{vehicle}）",
        manufacturer=MANUFACTURER,
        model="油耗统计",
    )


def _actual_payment(record: dict[str, Any]) -> float | None:
    """实际支付金额；1.0.5 之前的记录只有 total_cost（当时即实付）。"""
    value = record.get("actual_payment")
    if value is None:
        value = record.get("total_cost")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _discount(record: dict[str, Any]) -> float | None:
    """优惠金额 = 加油费用 - 实际支付（缺任一则为 None）。"""
    cost = record.get("total_cost")
    payment = _actual_payment(record)
    if cost is None or payment is None:
        return None
    try:
        return round(float(cost) - payment, 2)
    except (TypeError, ValueError):
        return None


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
        return {
            "vehicle": self._vehicle,
            "sinopec_role": "sinopec_odometer",
        }


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
    """Total refuel cost（累计加油费用 = 各次挂牌价合计）。"""

    STAT_KEY = "total_cost"
    STAT_NAME = "累计加油费用"
    _attr_icon = "mdi:cash-multiple"
    _attr_native_unit_of_measurement = UNIT_YUAN
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_cost")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = self._stats()
        return {
            "vehicle": self._vehicle,
            "total_payment": stats.get("total_payment"),
            "total_discount": stats.get("total_discount"),
            "avg_discount_rate": stats.get("avg_discount_rate"),
        }


class VehicleTotalPaymentSensor(VehicleStatsSensor):
    """实际支付累计（优惠后真实付款）。"""

    STAT_KEY = "total_payment"
    STAT_NAME = "累计实际支付"
    _attr_icon = "mdi:credit-card-check-outline"
    _attr_native_unit_of_measurement = UNIT_YUAN
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_payment")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = self._stats()
        return {
            "vehicle": self._vehicle,
            "total_cost": stats.get("total_cost"),
            "total_discount": stats.get("total_discount"),
        }


class VehicleTotalDiscountSensor(VehicleStatsSensor):
    """Total discount = 累计加油费用 - 累计实际支付。"""

    STAT_KEY = "total_discount"
    STAT_NAME = "累计优惠"
    _attr_icon = "mdi:sale-outline"
    _attr_native_unit_of_measurement = UNIT_YUAN
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        return self._stats().get("total_discount")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = self._stats()
        return {
            "vehicle": self._vehicle,
            "avg_discount_rate": stats.get("avg_discount_rate"),
            "last_discount": stats.get("last_discount"),
            "total_cost": stats.get("total_cost"),
            "total_payment": stats.get("total_payment"),
        }


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
    def native_value(self) -> datetime | None:
        return _as_utc_datetime(self._stats().get("last_record_date"))


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
        if rec.get("actual_payment") is not None:
            parts.append(f"实付{rec['actual_payment']}元")
        if rec.get("discount"):
            parts.append(f"优惠{rec['discount']}元")
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
                    # 加油费用（挂牌价）、实际支付与优惠金额（= 费用 - 实付）
                    "total_cost": rec.get("total_cost"),
                    "actual_payment": _actual_payment(rec),
                    "discount": _discount(rec),
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
            # 后端权威统计，卡片直接读取（避免前端重复实现计算口径）
            "stats": self._stats(),
        }


class VehicleQualitySensor(VehicleStatsSensor):
    """数据质量：时间-里程一致性。

    需修正 = 时间与里程矛盾（该区间被排除在统计之外）；
    部分缺口 = 有记录缺少里程读数（该区间不参与油耗统计，但不影响其他区间）。
    """

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
        stats = self._stats()
        problems = stats.get("quality_problems") or []
        if problems:
            return f"需修正（{len(problems)} 项）"
        gaps = int(stats.get("odometer_gaps") or 0)
        if gaps:
            return f"部分缺口（{gaps} 处）"
        return "正常"

    @property
    def icon(self) -> str:
        stats = self._stats()
        if stats.get("quality_problems"):
            return "mdi:alert-circle"
        if stats.get("odometer_gaps"):
            return "mdi:alert-outline"
        return "mdi:check-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = self._stats()
        return {
            "vehicle": self._vehicle,
            "sinopec_role": "sinopec_quality",
            "problems": stats.get("quality_problems") or [],
            "odometer_gaps": int(stats.get("odometer_gaps") or 0),
        }
