"""Persistent storage for vehicles, refuel records and statistics."""
from __future__ import annotations

from datetime import date as dt_date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.refuel_records"


def _to_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> dt_date | None:
    """Parse an ISO datetime/date string to date."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def _actual_payment_of(record: dict[str, Any]) -> float | None:
    """Return the amount actually paid for one record.

    1.0.5 之前的记录只有 total_cost（当时即"实际支付"），
    缺少 actual_payment 时按它回退，保证历史数据金额口径不变。
    """
    payment = _to_float(record.get("actual_payment"))
    if payment is None:
        payment = _to_float(record.get("total_cost"))
    return payment


def _discount_of(record: dict[str, Any]) -> float | None:
    """Return 优惠金额 = 加油费用(total_cost) - 实际支付(actual_payment)。"""
    cost = _to_float(record.get("total_cost"))
    payment = _actual_payment_of(record)
    if cost is None or payment is None:
        return None
    return round(cost - payment, 2)


def compute_stats(
    records: list[dict[str, Any]],
    initial_odometer: float | None = None,
    max_segment_km: float = 900.0,
) -> dict[str, Any]:
    """Compute statistics for a vehicle from its refuel records.

    油耗计算逻辑（假设每次都加满）：
    - 记录按加油时间升序排序（同日按登记先后）
    - 相邻两次加油的里程差 = 该区间行驶里程，有效区间须满足
      0 < 里程差 ≤ max_segment_km（默认 900 km）
    - 该区间油耗 = 本次加油量 / 区间里程 * 100（L/100km）
    - 累计平均油耗 = 有效区间加油量之和 / 有效区间里程之和 * 100
    - 累计行驶里程：若配置了初始里程，则为 最新里程-初始里程；
      否则为有效区间里程差之和。

    金额口径（每条的 total_cost 为加油费用即挂牌价，actual_payment 为实际支付）：
    - 优惠金额 discount = 加油费用 - 实际支付（缺 actual_payment 的旧记录视为无优惠）
    - 累计实付 total_payment、累计优惠 total_discount 为逐条求和
      （每条单独四舍五入，与记录里展示的优惠金额一致）
    - 平均油价仍按「加油费用 ÷ 加油量」计算，与历史统计口径一致；
      avg_discount_rate = 累计优惠 / 累计加油费用 * 100

    每公里油费（1.0.6 修正，见 _odometer_coverage_stats）：
    - 分母 = 里程计费跨度（首条有里程读数 → 最新有里程读数），
      分子 = 跨度内费用（累计费用剔除首箱），保证
      「每公里油费 × 里程计费跨度 = 跨度内费用」这条不变量，
      不会出现"分母只有最近一段、分子却是全部历史费用"的错位；
    - 里程读数覆盖率 < 50% 且存在 > 2000 km 空档时，返回 None 并给出
      per_km_cost_note 说明原因（宁可不显示，也不给出误导性数字）；
    - 附带 odometer_records / odometer_coverage / odometer_max_gap /
      measured_span / in_span_cost 供传感器与卡片展示数据可信度。

    数据完整性分两类，互不阻塞：
    - 缺口（odometer_gaps）：相邻记录缺少里程读数，该区间不参与油耗
      统计，但不影响其他区间，也不算错误；
    - 问题（quality_problems）：两侧都有里程但区间 ≤ 0 或 > 上限，
      属"时间与里程矛盾"，只丢弃该区间，其余区间统计照常。
    """
    stats: dict[str, Any] = {
        "refuel_count": len(records),
        "total_volume": 0.0,
        "total_cost": 0.0,
        "total_payment": 0.0,
        "total_discount": 0.0,
        "avg_discount_rate": None,
        "last_discount": None,
        "odometer": None,
        "total_distance": None,
        "record_distance": 0.0,
        "last_distance": None,
        "last_consumption": None,
        "avg_consumption": None,
        "avg_price": None,
        "per_km_cost": None,
        "per_km_cost_reliable": False,
        "per_km_cost_note": None,
        "measured_span": None,
        "in_span_cost": None,
        "odometer_records": 0,
        "odometer_coverage": 0.0,
        "odometer_max_gap": None,
        "last_record_date": None,
        "quality_problems": [],
        "odometer_gaps": 0,
    }
    if not records:
        # 无记录：里程表回退到配置的初始里程（传感器不再显示"未知"）
        if initial_odometer is not None:
            stats["odometer"] = initial_odometer
            stats["total_distance"] = 0.0
        return stats

    # 稳定排序：日期相同保持登记先后
    sorted_records = sorted(records, key=lambda r: str(r.get("date", "")))

    problems: list[str] = []
    gaps = 0
    total_volume = 0.0
    total_cost = 0.0
    total_payment = 0.0
    total_discount = 0.0
    last_discount = None
    consumption_volumes = 0.0
    record_distance = 0.0
    last_distance = None
    last_consumption = None
    prev = None
    odometer_records = 0
    first_odometer = None
    first_odometer_rec = None

    for idx, rec in enumerate(sorted_records):
        odometer = _to_float(rec.get("odometer"))
        volume = _to_float(rec.get("volume")) or 0.0
        cost = _to_float(rec.get("total_cost")) or 0.0
        # 旧记录缺 actual_payment 时按 total_cost 计（无优惠）
        payment = _actual_payment_of(rec)
        payment = cost if payment is None else payment
        discount = round(cost - payment, 2)
        total_volume += volume
        total_cost += cost
        total_payment += payment
        total_discount += discount
        rec_date = str(rec.get("date", ""))[:16]
        if odometer is not None:
            odometer_records += 1
            if first_odometer is None:
                first_odometer = odometer
                first_odometer_rec = rec

        if prev is not None:
            prev_odo = _to_float(prev.get("odometer"))
            if prev_odo is None or odometer is None:
                # 缺口：该区间不参与油耗统计，但不影响其他区间，也不算错误
                gaps += 1
            else:
                distance = odometer - prev_odo
                if distance <= 0:
                    problems.append(
                        f"第 {idx + 1} 条（{rec_date}，里程 {odometer}）与"
                        f"第 {idx} 条（{str(prev.get('date', ''))[:16]}，"
                        f"里程 {prev_odo}）时间顺序与里程顺序不符"
                        f"（区间里程 {round(distance, 1)} km），该区间不计入统计"
                    )
                elif distance > max_segment_km:
                    problems.append(
                        f"第 {idx + 1} 条（{rec_date}，里程 {odometer}）与"
                        f"第 {idx} 条（{str(prev.get('date', ''))[:16]}，"
                        f"里程 {prev_odo}）区间里程 {round(distance, 1)} km "
                        f"超过 {max_segment_km:g} km 上限，该区间不计入统计，"
                        "请核对里程或时间"
                    )
                else:
                    record_distance += distance
                    last_distance = round(distance, 1)
                    last_consumption = round(volume / distance * 100, 2)
                    consumption_volumes += volume
        prev = rec

    # 最近一次有里程读数的记录（末条可能缺里程）
    last_odometer = None
    for rec in reversed(sorted_records):
        value = _to_float(rec.get("odometer"))
        if value is not None:
            last_odometer = value
            break

    # 累计行驶里程：优先使用初始里程基准
    if last_odometer is not None and initial_odometer is not None:
        total_distance = max(last_odometer - initial_odometer, 0.0)
    elif record_distance > 0:
        # 无初始里程：以有效区间里程和近似（缺里程或异常区间不计入）
        total_distance = record_distance
    else:
        total_distance = None

    avg_consumption = None
    if consumption_volumes > 0 and record_distance > 0:
        avg_consumption = round(consumption_volumes / record_distance * 100, 2)

    # 最近一次加油的优惠金额（与最近加油日期同一口径）
    last_discount = _discount_of(sorted_records[-1])

    total_payment = round(total_payment, 2)
    total_discount = round(total_discount, 2)

    # ------------------------------------------------------------------
    # 每公里油费（1.0.6 修正）
    #
    # 必须满足不变量：每公里油费 × 累计行驶里程 = 对应的加油费用，
    # 否则「只换分子不换分母」会造成分子分母错位（历史 bug：分母只有最近
    # 一段里程，分子却是全部加油费用，算出 128 元/km 这种数字）。
    #
    # 口径：
    # - 分母 = 里程计费跨度 = 最新有里程读数 − 首条有里程读数
    #   （与累计行驶里程的分母一致，只是基准取"首条读数"而非配置的初始里程，
    #   这样即使初始里程配置有误，每公里油费也不会被算爆）
    # - 分子 = 跨度内的加油费用 = 累计加油费用 − 首条有里程记录的加油费用
    #   （首箱油在统计基准之前就已消耗，与平均油耗"首箱不计"同一假设）
    # - 里程读数太稀疏时（覆盖率 < 50% 且存在 > 2000 km 的无读数空档），
    #   这个比值没有足够数据支撑，直接返回 None 并给出说明，
    #   宁可显示"未知"也不给会误导人的数字。
    # ------------------------------------------------------------------
    stats.update(
        {
            "total_volume": round(total_volume, 2),
            "total_cost": round(total_cost, 2),
            "total_payment": total_payment,
            "total_discount": total_discount,
            "avg_discount_rate": (
                round(total_discount / total_cost * 100, 2)
                if total_cost > 0
                else None
            ),
            "last_discount": last_discount,
            "odometer": last_odometer,
            "total_distance": round(total_distance, 1) if total_distance is not None else None,
            "record_distance": round(record_distance, 1),
            "last_distance": last_distance,
            "last_consumption": last_consumption,
            "avg_consumption": avg_consumption,
            "avg_price": round(total_cost / total_volume, 2) if total_volume > 0 else None,
            "last_record_date": sorted_records[-1].get("date"),
            "quality_problems": problems,
            "odometer_gaps": gaps,
        }
    )
    stats.update(
        _odometer_coverage_stats(
            sorted_records,
            total_cost,
            first_odometer,
            first_odometer_rec,
            last_odometer,
            odometer_records,
        )
    )
    return stats


def _odometer_coverage_stats(
    sorted_records: list[dict[str, Any]],
    total_cost: float,
    first_odometer: float | None,
    first_odometer_rec: dict[str, Any] | None,
    last_odometer: float | None,
    odometer_records: int,
) -> dict[str, Any]:
    """里程读数覆盖情况 + 每公里油费口径（见 compute_stats 的说明）。

    判定原则：
    - 跨度太短（< 500 km）时，"跨度内费用 ÷ 跨度"只是几十上百公里的样本，
      噪声大且容易被首箱油影响 → 返回 None；
    - 跨度正常但里程读数稀疏（覆盖率 < 50% 或存在 > 2000 km 空档）时，
      比值本身仍可用（分子分母同跨度），但样本可信度低 →
      正常给出数值，同时置 per_km_cost_reliable=False 并用 note 说明；
    - 里程读数不足 2 条（无法确定跨度）→ 返回 None 并说明如何补填。
    """
    total_records = len(sorted_records)
    coverage = (
        round(odometer_records / total_records * 100, 1) if total_records else 0.0
    )

    # 相邻两条"有里程"记录之间的最大空档（判断里程连续性够不够）
    readings: list[float] = []
    for rec in sorted_records:
        value = _to_float(rec.get("odometer"))
        if value is not None:
            readings.append(value)
    max_gap = max(
        (b - a for a, b in zip(readings, readings[1:])),
        default=0.0,
    )

    measured_span = None
    if first_odometer is not None and last_odometer is not None:
        span = last_odometer - first_odometer
        if span > 0:
            measured_span = round(span, 1)

    sample_ok = bool(measured_span and measured_span >= 500.0)
    gap_ok = max_gap > 0 and max_gap <= 2000.0
    reliable = bool(sample_ok and (coverage >= 50.0 or gap_ok))

    in_span_cost = None
    per_km_cost = None
    note = None
    if measured_span:
        first_cost = (
            _to_float(first_odometer_rec.get("total_cost")) or 0.0
            if first_odometer_rec
            else 0.0
        )
        in_span_cost = round(total_cost - first_cost, 2)
        if sample_ok and in_span_cost > 0:
            # 四舍五入到与展示精度一致，保证
            # 「每公里油费 × 里程计费跨度 = 跨度内费用」这条不变量能对上
            per_km_cost = round(in_span_cost / measured_span, 3)

    if per_km_cost is None:
        if not measured_span:
            note = (
                "里程读数不足 2 条，无法确定计费跨度，每公里油费不可计算；"
                "补填任意两次加油的里程表读数即可"
            )
        else:
            note = (
                f"里程读数仅 {odometer_records}/{total_records} 条"
                f"（{coverage:g}%），计费跨度只有 {measured_span:g} km，"
                "样本太短不足以代表长期油费水平；"
                "补填更多带里程的加油记录后自动恢复"
            )
    elif not reliable:
        if coverage < 50.0:
            note = (
                f"里程读数仅 {odometer_records}/{total_records} 条"
                f"（{coverage:g}%），已按 {measured_span:g} km 跨度"
                f"（费用 {in_span_cost:g} 元，首箱不计）估算；"
                "中间缺少读数，无法交叉核对异常，建议按年补填里程表读数"
            )
        else:
            note = (
                f"相邻里程读数之间存在 {max_gap:g} km 的空档，"
                f"已按 {measured_span:g} km 跨度估算，建议补填中间记录"
            )

    return {
        "per_km_cost": per_km_cost,
        "per_km_cost_reliable": reliable,
        "per_km_cost_note": note,
        "measured_span": measured_span,
        "in_span_cost": in_span_cost,
        "odometer_records": odometer_records,
        "odometer_coverage": coverage,
        "odometer_max_gap": round(max_gap, 1) if max_gap else None,
    }


class RefuelStore:
    """Store vehicles and their refuel records."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage handler."""
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"vehicles": {}}
        self._loaded = False

    async def async_load(self) -> None:
        """Load data from disk."""
        raw = await self._store.async_load() or {}
        self._data = {"vehicles": raw.get("vehicles", {})}
        self._loaded = True

    @property
    def vehicles(self) -> dict[str, Any]:
        """Return all vehicles and their records."""
        return self._data.get("vehicles", {})

    # ------------------------------------------------------------------
    # 车辆管理
    # ------------------------------------------------------------------
    def get_vehicle(self, vehicle: str) -> dict[str, Any] | None:
        """Return one vehicle's info (without records)."""
        info = self.vehicles.get(vehicle)
        if not info:
            return None
        return {k: v for k, v in info.items() if k != "records"}

    def get_current_odometer(self, vehicle: str) -> float | None:
        """当前里程表读数：最近一条有里程的记录，否则回退初始里程。

        供表单预填与服务端"沿用上次读数"使用。
        """
        info = self.vehicles.get(vehicle) or {}
        records = sorted(
            info.get("records", []), key=lambda r: str(r.get("date", ""))
        )
        for rec in reversed(records):
            odo = _to_float(rec.get("odometer"))
            if odo is not None:
                return odo
        return _to_float(info.get("initial_odometer"))

    def get_stats(self, vehicle: str) -> dict[str, Any]:
        """Return computed statistics for one vehicle."""
        info = self.vehicles.get(vehicle) or {}
        return compute_stats(
            info.get("records", []),
            initial_odometer=_to_float(info.get("initial_odometer")),
        )

    async def async_add_vehicle(
        self,
        vehicle: str,
        initial_odometer: float | None = None,
        fuel_type: str | None = None,
    ) -> bool:
        """Add a vehicle. Return True if created, False if already exists."""
        if vehicle in self.vehicles:
            return False
        self.vehicles[vehicle] = {
            "name": vehicle,
            "initial_odometer": initial_odometer,
            "default_fuel_type": fuel_type,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "records": [],
        }
        await self._async_save()
        return True

    async def async_update_vehicle(
        self,
        vehicle: str,
        initial_odometer: float | None = None,
        fuel_type: str | None = None,
    ) -> bool:
        """Update vehicle settings. Return False if vehicle not found."""
        info = self.vehicles.get(vehicle)
        if info is None:
            return False
        if initial_odometer is not None:
            info["initial_odometer"] = initial_odometer
        if fuel_type is not None:
            info["default_fuel_type"] = fuel_type
        await self._async_save()
        return True

    async def async_remove_vehicle(self, vehicle: str) -> bool:
        """Remove a vehicle and all its records. Return True if it existed."""
        if vehicle not in self.vehicles:
            return False
        self.vehicles.pop(vehicle)
        await self._async_save()
        return True

    # ------------------------------------------------------------------
    # 加油记录
    # ------------------------------------------------------------------
    def get_records(self, vehicle: str) -> list[dict[str, Any]]:
        """Return records for one vehicle."""
        return list(self.vehicles.get(vehicle, {}).get("records", []))

    def get_last_record(self, vehicle: str) -> dict[str, Any] | None:
        """Return the latest record of a vehicle."""
        records = self.get_records(vehicle)
        if not records:
            return None
        return sorted(records, key=lambda r: str(r.get("date", "")))[-1]

    async def async_add_record(
        self, vehicle: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Add a refuel record and return the post-add statistics."""
        is_new_vehicle = vehicle not in self.vehicles
        vehicle_data = self.vehicles.setdefault(vehicle, {"records": []})
        vehicle_data.setdefault("records", []).append(record)
        await self._async_save()
        stats = self.get_stats(vehicle)

        last_distance = None
        last_consumption = None
        records = vehicle_data.get("records", [])
        if len(records) >= 2:
            odometer = _to_float(record.get("odometer"))
            volume = _to_float(record.get("volume")) or 0.0
            prev = sorted(
                records, key=lambda r: str(r.get("date", ""))
            )[-2]
            prev_odometer = _to_float(prev.get("odometer"))
            if odometer is not None and prev_odometer is not None:
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

    def get_records_sorted(self, vehicle: str) -> list[dict[str, Any]]:
        """Return records sorted by date (ascending), each tagged with `index`.

        `index` 是排序后的序号，供 delete_refuel_record / edit_refuel_record
        服务按序号定位记录。
        """
        records = sorted(
            self.get_records(vehicle), key=lambda r: str(r.get("date", ""))
        )
        return [{**rec, "index": i} for i, rec in enumerate(records)]

    def _records_by_date(self, vehicle: str) -> list[dict[str, Any]]:
        """Internal: date-sorted references to the actual record dicts."""
        return sorted(
            self.vehicles.get(vehicle, {}).get("records", []),
            key=lambda r: str(r.get("date", "")),
        )

    async def async_delete_record(
        self, vehicle: str, index: int
    ) -> dict[str, Any] | None:
        """Delete the record at sorted `index`. Return the removed record."""
        records_sorted = self._records_by_date(vehicle)
        if index < 0 or index >= len(records_sorted):
            return None
        removed = records_sorted[index]
        stored = self.vehicles.get(vehicle, {}).get("records", [])
        for i, rec in enumerate(stored):
            if rec is removed:
                del stored[i]
                break
        await self._async_save()
        return removed

    async def async_replace_record(
        self, vehicle: str, index: int, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Replace the record at sorted `index` with `updates`.

        `updates` 应为完整的新记录内容（由服务层智能重算后给出）。
        返回替换后的记录；序号越界或未命中返回 None。
        """
        records_sorted = self._records_by_date(vehicle)
        if index < 0 or index >= len(records_sorted):
            return None
        target = records_sorted[index]
        stored = self.vehicles.get(vehicle, {}).get("records", [])
        for i, rec in enumerate(stored):
            if rec is target:
                stored[i] = dict(updates)
                await self._async_save()
                return stored[i]
        return None

    async def async_clear_vehicle(self, vehicle: str) -> bool:
        """Remove all records of a vehicle. Return True if it existed."""
        if vehicle not in self.vehicles:
            return False
        self.vehicles[vehicle]["records"] = []
        await self._async_save()
        return True

    async def _async_save(self) -> None:
        """Persist data to disk."""
        if not self._loaded:
            await self.async_load()
        await self._store.async_save(self._data)
