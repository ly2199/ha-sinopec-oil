"""Persistent storage for refuel records and fuel consumption statistics."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.refuel_records"


def compute_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute statistics for a vehicle from its refuel records.

    油耗计算逻辑（假设每次都加满）：
    - 相邻两次加油的里程差 = 该区间行驶里程
    - 该区间油耗 = 本次加油量 / 区间里程 * 100（L/100km）
    - 累计平均油耗 = (首条记录之外的所有加油量之和) / 总里程 * 100
      （首箱油对应的是首条记录之前的消耗，无法统计，故不计入）
    """
    stats: dict[str, Any] = {
        "refuel_count": len(records),
        "total_volume": 0.0,
        "total_cost": 0.0,
        "odometer": None,
        "total_distance": 0.0,
        "last_distance": None,
        "last_consumption": None,
        "avg_consumption": None,
        "avg_price": None,
        "per_km_cost": None,
        "last_record_date": None,
    }
    if not records:
        return stats

    sorted_records = sorted(records, key=lambda r: r.get("date") or "")
    total_volume = 0.0
    total_cost = 0.0
    total_distance = 0.0
    consumption_volumes = 0.0  # 可与里程对应起来的加油量（第 2 条起）
    last_distance: float | None = None
    last_consumption: float | None = None
    prev: dict[str, Any] | None = None

    for rec in sorted_records:
        odometer = _to_float(rec.get("odometer"))
        volume = _to_float(rec.get("volume")) or 0.0
        cost = _to_float(rec.get("total_cost")) or 0.0
        total_volume += volume
        total_cost += cost

        if prev is not None and odometer is not None:
            prev_odometer = _to_float(prev.get("odometer"))
            if prev_odometer is not None:
                distance = odometer - prev_odometer
                if distance > 0:
                    total_distance += distance
                    last_distance = distance
                    last_consumption = round(volume / distance * 100, 2)
                    consumption_volumes += volume
        prev = rec

    odometer_last = _to_float(sorted_records[-1].get("odometer"))

    stats.update(
        {
            "total_volume": round(total_volume, 2),
            "total_cost": round(total_cost, 2),
            "odometer": odometer_last,
            "total_distance": round(total_distance, 1),
            "last_distance": round(last_distance, 1) if last_distance else None,
            "last_consumption": last_consumption,
            "avg_consumption": (
                round(consumption_volumes / total_distance * 100, 2)
                if total_distance > 0 and consumption_volumes > 0
                else None
            ),
            "avg_price": (
                round(total_cost / total_volume, 2)
                if total_volume > 0
                else None
            ),
            "per_km_cost": (
                round(total_cost / total_distance, 3)
                if total_distance > 0
                else None
            ),
            "last_record_date": sorted_records[-1].get("date"),
        }
    )
    return stats


def _to_float(value: Any) -> float | None:
    """Convert a value to float safely."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class RefuelStore:
    """Store refuel records persistently.

    数据结构：
    {
      "vehicles": {
        "<vehicle>": {
          "records": [
            {"date": "...", "odometer": ..., "volume": ..., "total_cost": ...,
             "price": ..., "fuel_type": "92", "note": ""}
          ]
        }
      }
    }
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"vehicles": {}}
        self._loaded = False

    async def async_load(self) -> None:
        """Load data from disk."""
        if (data := await self._store.async_load()) is not None:
            self._data = data
        self._data.setdefault("vehicles", {})
        self._loaded = True

    @property
    def vehicles(self) -> dict[str, Any]:
        """Return all vehicles and their records."""
        return self._data.get("vehicles", {})

    def get_records(self, vehicle: str) -> list[dict[str, Any]]:
        """Return records for one vehicle."""
        return list(self.vehicles.get(vehicle, {}).get("records", []))

    def get_stats(self, vehicle: str) -> dict[str, Any]:
        """Return computed statistics for one vehicle."""
        return compute_stats(self.get_records(vehicle))

    async def async_add_record(
        self, vehicle: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Add a refuel record and return the post-add statistics."""
        is_new_vehicle = vehicle not in self.vehicles
        vehicle_data = self.vehicles.setdefault(vehicle, {"records": []})
        vehicle_data["records"].append(record)
        await self._async_save()
        stats = self.get_stats(vehicle)

        last_distance = None
        last_consumption = None
        records = sorted(vehicle_data["records"], key=lambda r: r.get("date") or "")
        if len(records) >= 2:
            prev_odometer = _to_float(records[-2].get("odometer"))
            odometer = _to_float(records[-1].get("odometer"))
            volume = _to_float(records[-1].get("volume")) or 0.0
            if prev_odometer is not None and odometer is not None:
                distance = odometer - prev_odometer
                if distance > 0:
                    last_distance = round(distance, 1)
                    last_consumption = round(volume / distance * 100, 2)

        return {
            "vehicle": vehicle,
            "new_vehicle": is_new_vehicle,
            "last_distance": last_distance,
            "last_consumption": last_consumption,
            "stats": stats,
        }

    async def async_clear_vehicle(self, vehicle: str) -> bool:
        """Remove all records of a vehicle. Return True if it existed."""
        if vehicle not in self.vehicles:
            return False
        self.vehicles.pop(vehicle)
        await self._async_save()
        return True

    async def _async_save(self) -> None:
        """Persist data to disk."""
        if not self._loaded:
            await self.async_load()
        await self._store.async_save(self._data)
