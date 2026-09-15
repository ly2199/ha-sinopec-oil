"""Services for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as dt_date, datetime
from typing import Any

import voluptuous as vol
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

from .api import SinopecOilApiClientError, resolve_fuel_keys
from .const import (
    CONF_INITIAL_ODOMETER,
    DOMAIN,
    OIL_TYPE_LABELS,
    SERVICE_ADD_VEHICLE,
    SERVICE_CLEAR_VEHICLE,
    SERVICE_DELETE_RECORD,
    SERVICE_EDIT_RECORD,
    SERVICE_GET_PRICE_HISTORY,
    SERVICE_IMPORT_RECORDS,
    SERVICE_LIST_RECORDS,
    SERVICE_RECORD_REFUEL,
    SERVICE_REFRESH_OIL_PRICE,
    SERVICE_REMOVE_VEHICLE,
    SIGNAL_VEHICLE_ADDED,
    SIGNAL_VEHICLE_REMOVED,
)
from .coordinator import SinopecOilRuntimeData
from .store import _to_float

_LOGGER = logging.getLogger(__name__)

ATTR_VEHICLE = "vehicle"
ATTR_ODOMETER = "odometer"
ATTR_VOLUME = "volume"
ATTR_TOTAL_COST = "total_cost"
ATTR_PRICE = "price"
ATTR_FUEL_TYPE = "fuel_type"
ATTR_DATE = "date"
ATTR_NOTE = "note"
ATTR_RECORDS = "records"

_RECORD_ITEM_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DATE): cv.datetime,
        vol.Optional(ATTR_ODOMETER): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0.01)
        ),
        vol.Optional(ATTR_TOTAL_COST): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_PRICE): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_FUEL_TYPE): cv.string,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)

RECORD_REFUEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Optional(ATTR_ODOMETER): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0.01)
        ),
        vol.Optional(ATTR_TOTAL_COST): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_PRICE): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_FUEL_TYPE): cv.string,
        vol.Optional(ATTR_DATE): cv.datetime,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)

IMPORT_RECORDS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Required(ATTR_RECORDS): vol.All(
            cv.ensure_list, [vol.All(dict, _RECORD_ITEM_SCHEMA)]
        ),
    }
)

LIST_RECORDS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
    }
)

DELETE_RECORD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Required("index"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
    }
)

EDIT_RECORD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Required("index"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional(ATTR_DATE): cv.datetime,
        vol.Optional(ATTR_ODOMETER): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_VOLUME): vol.All(
            vol.Coerce(float), vol.Range(min=0.01)
        ),
        vol.Optional(ATTR_TOTAL_COST): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_PRICE): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_FUEL_TYPE): cv.string,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)

ADD_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VEHICLE): cv.string,
        vol.Optional(CONF_INITIAL_ODOMETER): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional(ATTR_FUEL_TYPE, default="92"): cv.string,
    }
)

REMOVE_VEHICLE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_VEHICLE): cv.string}
)

CLEAR_VEHICLE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_VEHICLE): cv.string}
)


def _get_store(hass: HomeAssistant):
    """Return the shared refuel store."""
    store = hass.data.get(DOMAIN, {}).get("store")
    if store is None:
        raise HomeAssistantError("集成尚未完成加载")
    return store


MAX_SEGMENT_KM = 900.0  # 每次加油区间的合理里程上限（超限视为里程/时间不符）


@dataclass
class _BuiltRecord:
    """智能计价结果。

    record 为入库内容（字段与存储格式一致）；
    price_source/price_approximate 是本次计算的说明，只用于服务响应，
    不写入存储（避免内部字段污染持久化数据）。
    """

    record: dict[str, Any]
    price_source: str | None = None
    price_approximate: bool = False


def _import_sort_key(item: dict[str, Any], now: datetime) -> str:
    """批量导入的排序键：缺失日期的条目按当前时间参与排序。"""
    value = item.get(ATTR_DATE) or now
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _validate_segment_order(
    store,
    vehicle: str,
    new_odometer: float | None,
    new_date: str,
    exclude_date: str | None = None,
) -> None:
    """校验新记录插入时间序后与相邻记录的里程是否矛盾（矛盾则阻止入库）。

    - 本次没有里程读数：无法校验，直接通过（只算该区间缺口，
      不影响其他区间的油耗统计）。
    - 与时间上最近的一条「有里程读数」的相邻记录比较，要求里程严格递增；
      若两者之间还夹着缺少里程的记录，跨度天然覆盖多个加油区间，
      此时只校验递增、不套用单区间 900 km 上限。

    edit 场景通过 exclude_date 排除被编辑记录本身，只校验与前后邻居的区间。
    """
    if new_odometer is None:
        return

    records = store.get_records_sorted(vehicle)
    if exclude_date is not None:
        records = [
            r for r in records if str(r.get("date", "")) != exclude_date
        ]

    before = [r for r in records if str(r.get("date", "")) <= new_date]
    after = [r for r in records if str(r.get("date", "")) > new_date]

    def _nearest_with_odometer(items):
        """返回 (记录, 中间跳过的无里程记录数)，最近的优先。"""
        skipped = 0
        for rec in items:
            if _to_float(rec.get("odometer")) is not None:
                return rec, skipped
            skipped += 1
        return None, 0

    prev, prev_gap = _nearest_with_odometer(reversed(before))
    nxt, next_gap = _nearest_with_odometer(after)

    if prev is not None:
        prev_odo = _to_float(prev.get("odometer"))
        diff = new_odometer - prev_odo
        if diff <= 0:
            raise HomeAssistantError(
                f"时间顺序与里程不一致：{new_date} 的里程 {new_odometer} "
                f"不大于 {prev.get('date')} 的 {prev_odo}（相邻加油区间"
                "里程必须为正）。请修正里程或时间后重试，本次未保存。"
            )
        if prev_gap == 0 and diff > MAX_SEGMENT_KM:
            raise HomeAssistantError(
                f"区间里程超限：{new_date} 与 {prev.get('date')} 之间"
                f"相差 {round(diff, 1)} km，超过单次加油区间 {MAX_SEGMENT_KM:g} km "
                "上限。请核对里程表读数或加油时间，本次未保存。"
            )
    if nxt is not None:
        nxt_odo = _to_float(nxt.get("odometer"))
        diff = nxt_odo - new_odometer
        if diff <= 0:
            raise HomeAssistantError(
                f"时间顺序与里程不一致：{nxt.get('date')} 的里程 {nxt_odo} "
                f"不大于本次（{new_date}）的 {new_odometer}（历史补录需保持"
                "时间与里程同步递增）。请修正后重试，本次未保存。"
            )
        if next_gap == 0 and diff > MAX_SEGMENT_KM:
            raise HomeAssistantError(
                f"区间里程超限：{nxt.get('date')} 与本次（{new_date}）之间"
                f"相差 {round(diff, 1)} km，超过 {MAX_SEGMENT_KM:g} km 上限。"
                "请核对里程或时间，本次未保存。"
            )


def _get_runtime_datas(hass: HomeAssistant) -> list[SinopecOilRuntimeData]:
    """Return runtime data of all loaded entries."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if hasattr(entry, "runtime_data")
        and isinstance(
            getattr(entry, "runtime_data", None), SinopecOilRuntimeData
        )
    ]


def _resolve_fuel_key(
    vehicle_info: dict[str, Any] | None,
    fuel_input: str | None,
    available_keys: set[str],
) -> tuple[str | None, str | None]:
    """Resolve the fuel data key.

    优先级：用户输入 > 车辆默认油品 > 当前价表中第一个可用油品。
    返回 (data_key, fuel_type_display)。
    """
    candidates: list[tuple[str, ...]] = []
    if fuel_input:
        keys = resolve_fuel_keys(fuel_input)
        if keys:
            candidates.append(keys)
    if vehicle_info and vehicle_info.get("default_fuel_type"):
        keys = resolve_fuel_keys(str(vehicle_info["default_fuel_type"]))
        if keys:
            candidates.append(keys)

    for keys in candidates:
        for key in keys:
            if key in available_keys:
                return key, key
    # 兜底：当前价表中第一个油品
    for key in sorted(available_keys):
        return key, key
    return None, None


async def _async_build_record(
    hass: HomeAssistant,
    data: dict[str, Any],
    vehicle_info: dict[str, Any] | None,
    runtime: SinopecOilRuntimeData | None,
) -> _BuiltRecord:
    """Build a refuel record with smart price/volume/cost calculation.

    智能计算规则：
    - 输入加油量 + 总费用 → 单价 = 费用/加油量（实际成交价）
    - 只输入加油量 → 费用 = 加油量 × 基准油价（当日或历史）
    - 只输入总费用 → 加油量 = 费用 / 基准油价
    - 基准油价：加油日期为今天 → 当前缓存油价；
      历史日期 → 自动查询中石化历史调价周期匹配当日油价。
    """
    volume = data.get(ATTR_VOLUME)
    total_cost = data.get(ATTR_TOTAL_COST)
    price_input = data.get(ATTR_PRICE)
    fuel_input = data.get(ATTR_FUEL_TYPE)

    when: datetime = data.get(ATTR_DATE) or dt_util.now()
    when_date: dt_date = when.date()
    today = dt_util.now().date()

    price_value: float | None = None
    price_source: str | None = None
    price_approx = False
    fuel_key: str | None = None

    if total_cost is not None and volume is not None:
        # 两者齐全，油价仅作展示
        if price_input is not None:
            price_value = float(price_input)
            price_source = "手动输入"
        else:
            price_value = round(float(total_cost) / float(volume), 4)
            price_source = "费用/加油量"
        if runtime is not None and runtime.price_coordinator.data:
            key, _ = _resolve_fuel_key(
                vehicle_info, fuel_input, set(runtime.price_coordinator.data.prices)
            )
            fuel_key = key
    else:
        # 需要基准油价
        ref_price = None
        available: set[str] = set()
        if runtime is not None and runtime.price_coordinator.data:
            oil = runtime.price_coordinator.data
            available = set(oil.prices)
            key, _ = _resolve_fuel_key(
                vehicle_info, fuel_input, available
            )
            fuel_key = key
            if key is not None and when_date >= today:
                ref_price = oil.prices.get(key)
                price_source = f"当前油价（{oil.display_name}）"
        if ref_price is None:
            # 历史日期或当前缓存中没有：查询历史调价周期
            keys = resolve_fuel_keys(fuel_input or "")
            if not keys and vehicle_info and vehicle_info.get("default_fuel_type"):
                keys = resolve_fuel_keys(
                    str(vehicle_info["default_fuel_type"])
                )
            if not keys and runtime is not None and runtime.price_coordinator.data:
                keys = tuple(runtime.price_coordinator.data.prices.keys())
            if not keys:
                raise HomeAssistantError(
                    "无法确定油品类型：请填写 fuel_type（如 92、95、98、0）"
                )
            # 优先使用当前实例的 client（多省份实例时避免跨省查询）；
            # 无 runtime 时退回全局任一实例
            client = None
            if runtime is not None:
                client = runtime.price_coordinator.client
            if client is None:
                for rt in _get_runtime_datas(hass):
                    client = rt.price_coordinator.client
                    break
            if client is None:
                raise HomeAssistantError(
                    "没有已加载的油价实例，无法查询历史油价"
                )
            resolved = await client.async_get_price_on(keys, when_date)
            if resolved is None:
                raise HomeAssistantError(
                    f"无法在历史油价中找到 {when_date.isoformat()} 的价格，"
                    "请手动填写 price（单价）"
                )
            ref_price, price_source, price_approx = resolved

        if volume is not None:
            total_cost = round(float(volume) * ref_price, 2)
            price_value = round(ref_price, 2)
        elif total_cost is not None:
            volume = round(float(total_cost) / ref_price, 2)
            price_value = round(ref_price, 2)
        else:
            raise HomeAssistantError(
                "只填写单价时无法计算加油量/费用："
                "请至少填写 volume（加油量）或 total_cost（总费用）之一"
            )

    odometer = data.get(ATTR_ODOMETER)

    return _BuiltRecord(
        record={
            "date": when.isoformat(timespec="seconds"),
            "odometer": _to_float(odometer),
            "volume": _to_float(volume),
            "total_cost": _to_float(total_cost),
            "price": price_value,
            "fuel_type": fuel_input or "",
            "fuel_key": fuel_key,
            "note": data.get(ATTR_NOTE) or "",
        },
        price_source=price_source,
        price_approximate=price_approx,
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services (once)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    async def async_handle_record_refuel(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Handle the record_refuel service call."""
        store = _get_store(call.hass)
        data = dict(call.data)

        vehicle = str(data[ATTR_VEHICLE]).strip()
        if not vehicle:
            raise HomeAssistantError("vehicle（车辆）不能为空")

        vehicle_info = store.get_vehicle(vehicle)
        if vehicle_info is None:
            # 车辆不存在时自动创建（初始里程取本次里程，默认油品取本次油品）
            await store.async_add_vehicle(
                vehicle,
                initial_odometer=_to_float(data.get(ATTR_ODOMETER)),
                fuel_type=data.get(ATTR_FUEL_TYPE) or "92",
            )
            vehicle_info = store.get_vehicle(vehicle)
            async_dispatcher_send(call.hass, SIGNAL_VEHICLE_ADDED, vehicle)

        runtime = None
        for rt in _get_runtime_datas(call.hass):
            runtime = rt
            break

        built = await _async_build_record(
            call.hass, data, vehicle_info, runtime
        )
        record = built.record
        # 时间-里程矛盾则阻止入库；缺少里程只算缺口，允许写入
        _validate_segment_order(
            store, vehicle, record["odometer"], record["date"]
        )
        result = await store.async_add_record(vehicle, record)

        for rt in _get_runtime_datas(call.hass):
            call.hass.async_create_task(
                rt.refuel_coordinator.async_request_refresh()
            )

        response: dict[str, Any] = {
            ATTR_VEHICLE: vehicle,
            ATTR_DATE: record["date"],
            ATTR_VOLUME: record["volume"],
            ATTR_TOTAL_COST: record["total_cost"],
            ATTR_PRICE: record["price"],
            "price_source": built.price_source,
            "price_approximate": built.price_approximate,
            "distance_since_last": result.get("last_distance"),
            "consumption_last": result.get("last_consumption"),
        }
        _LOGGER.info(
            "已记录加油：%s %sL / %s元 / %s元-L（油价来源：%s）",
            vehicle,
            record["volume"],
            record["total_cost"],
            record["price"],
            built.price_source,
        )
        return response

    async def async_handle_import_records(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Batch-import historical refuel records (smart calculation each)."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        if not vehicle:
            raise HomeAssistantError("vehicle（车辆）不能为空")

        vehicle_info = store.get_vehicle(vehicle)
        if vehicle_info is None:
            await store.async_add_vehicle(vehicle)
            vehicle_info = store.get_vehicle(vehicle)
            async_dispatcher_send(call.hass, SIGNAL_VEHICLE_ADDED, vehicle)

        runtime = None
        for rt in _get_runtime_datas(call.hass):
            runtime = rt
            break

        # 按生效时间排序后再逐条写入：缺省日期的条目按"当前时间"参与排序，
        # 否则空日期会排到最前，导致时间-里程校验用错邻居。
        now = dt_util.now()
        records = sorted(
            call.data[ATTR_RECORDS],
            key=lambda r: _import_sort_key(r, now),
        )
        imported = 0
        rejected: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for item in records:
            built = await _async_build_record(
                call.hass, dict(item), vehicle_info, runtime
            )
            record = built.record
            # 逐行校验，矛盾行拒绝并报告原因（其余行正常导入；缺里程不算矛盾）
            try:
                _validate_segment_order(
                    store, vehicle, record["odometer"], record["date"]
                )
            except HomeAssistantError as err:
                rejected.append(
                    {"date": record["date"], "reason": str(err)}
                )
                continue
            await store.async_add_record(vehicle, record)
            imported += 1
            results.append(
                {
                    ATTR_DATE: record["date"],
                    ATTR_VOLUME: record["volume"],
                    ATTR_TOTAL_COST: record["total_cost"],
                    ATTR_PRICE: record["price"],
                    "price_source": built.price_source,
                }
            )

        for rt in _get_runtime_datas(call.hass):
            call.hass.async_create_task(
                rt.refuel_coordinator.async_request_refresh()
            )
        _LOGGER.info(
            "批量导入加油记录：%s 成功 %d 条，拒绝 %d 条",
            vehicle,
            imported,
            len(rejected),
        )
        return {
            "vehicle": vehicle,
            "imported": imported,
            "rejected": rejected,
            "records": results,
        }

    async def async_handle_add_vehicle(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Add a vehicle."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        if not vehicle:
            raise HomeAssistantError("vehicle（车辆）不能为空")
        created = await store.async_add_vehicle(
            vehicle,
            initial_odometer=_to_float(
                call.data.get(CONF_INITIAL_ODOMETER)
            ),
            fuel_type=call.data.get(ATTR_FUEL_TYPE) or "92",
        )
        if created:
            async_dispatcher_send(
                call.hass, SIGNAL_VEHICLE_ADDED, vehicle
            )
        return {"vehicle": vehicle, "created": created}

    async def async_handle_remove_vehicle(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Remove a vehicle."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        removed = await store.async_remove_vehicle(vehicle)
        if removed:
            async_dispatcher_send(
                call.hass, SIGNAL_VEHICLE_REMOVED, vehicle
            )
        return {"vehicle": vehicle, "removed": removed}

    async def async_handle_clear_vehicle(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Clear records of a vehicle."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        cleared = await store.async_clear_vehicle(vehicle)
        return {"vehicle": vehicle, "cleared": cleared}

    async def async_handle_list_records(
        call: ServiceCall,
    ) -> ServiceResponse:
        """List refuel records of a vehicle (sorted by date, with index)."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        records = store.get_records_sorted(vehicle)
        return {
            "vehicle": vehicle,
            "count": len(records),
            "records": records,
            "stats": store.get_stats(vehicle),
        }

    async def async_handle_delete_record(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Delete one refuel record by sorted index."""
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        index = int(call.data["index"])
        removed = await store.async_delete_record(vehicle, index)
        if removed is None:
            raise HomeAssistantError(
                f"车辆 '{vehicle}' 不存在或序号 {index} 超出范围"
                "（可先调用 list_refuel_records 获取记录与序号）"
            )
        for rt in _get_runtime_datas(call.hass):
            call.hass.async_create_task(
                rt.refuel_coordinator.async_request_refresh()
            )
        return {
            "vehicle": vehicle,
            "deleted_index": index,
            "deleted_record": removed,
            "stats": store.get_stats(vehicle),
        }

    async def async_handle_edit_record(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Edit one refuel record by sorted index (smart recalculation).

        只改加油量或只改费用时，按记录日期对应的油价智能重算另一项；
        量与费同时给出则单价=费用/加油量。
        """
        store = _get_store(call.hass)
        vehicle = str(call.data[ATTR_VEHICLE]).strip()
        index = int(call.data["index"])

        sorted_records = store.get_records_sorted(vehicle)
        if index >= len(sorted_records):
            raise HomeAssistantError(
                f"车辆 '{vehicle}' 不存在或序号 {index} 超出范围"
                "（可先调用 list_refuel_records 获取记录与序号）"
            )
        original = {
            k: v
            for k, v in sorted_records[index].items()
            if k != "index" and not str(k).startswith("_")
        }

        # 合并用户改动（未提供的字段沿用原记录）
        merged: dict[str, Any] = {**original}
        for key in (
            ATTR_DATE,
            ATTR_ODOMETER,
            ATTR_VOLUME,
            ATTR_TOTAL_COST,
            ATTR_PRICE,
            ATTR_FUEL_TYPE,
            ATTR_NOTE,
        ):
            if key in call.data:
                merged[key] = call.data[key]
        if isinstance(merged.get(ATTR_DATE), str):
            merged[ATTR_DATE] = datetime.fromisoformat(merged[ATTR_DATE])

        vehicle_info = store.get_vehicle(vehicle)
        runtime = next(iter(_get_runtime_datas(call.hass)), None)

        new_built = await _async_build_record(
            call.hass, merged, vehicle_info, runtime
        )
        new_record = new_built.record
        # 编辑后的记录与其前后邻居区间校验（排除原记录本身）
        _validate_segment_order(
            store,
            vehicle,
            new_record["odometer"],
            new_record["date"],
            exclude_date=str(original.get(ATTR_DATE, "")),
        )
        updated = await store.async_replace_record(vehicle, index, new_record)
        for rt in _get_runtime_datas(call.hass):
            call.hass.async_create_task(
                rt.refuel_coordinator.async_request_refresh()
            )
        return {
            "vehicle": vehicle,
            "index": index,
            "record": updated,
            "stats": store.get_stats(vehicle),
        }

    async def async_handle_get_price_history(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Return the historical price periods of the configured location."""
        for rt in _get_runtime_datas(call.hass):
            data = rt.price_coordinator.data
            if data is None:
                continue
            history = data.price_history
            if not history:
                try:
                    periods = (
                        await rt.price_coordinator.client.async_get_price_history()
                    )
                    history = rt.price_coordinator.client.history_to_payload(
                        periods
                    )
                except SinopecOilApiClientError as err:
                    raise HomeAssistantError(
                        f"获取历史油价失败: {err}"
                    ) from err
            return {
                "location": data.display_name,
                "current_update_time": data.update_time,
                "period_count": len(history),
                # 数据字段名 → 中文标签（periods[].prices 的 key 用字段名）
                "labels": dict(OIL_TYPE_LABELS),
                "periods": history,
            }
        raise HomeAssistantError("没有已加载的油价实例")

    async def async_handle_refresh_oil_price(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Refresh oil prices of all entries now."""
        updated = []
        for rt in _get_runtime_datas(call.hass):
            await rt.price_coordinator.async_request_refresh()
            oil = rt.price_coordinator.data
            if oil is not None:
                updated.append(
                    {
                        "location": oil.display_name,
                        "updated_at": oil.update_time,
                        "price_count": len(oil.prices),
                    }
                )
        return {"entries": updated}

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECORD_REFUEL,
        async_handle_record_refuel,
        schema=RECORD_REFUEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_RECORDS,
        async_handle_import_records,
        schema=IMPORT_RECORDS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_RECORDS,
        async_handle_list_records,
        schema=LIST_RECORDS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_RECORD,
        async_handle_delete_record,
        schema=DELETE_RECORD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_RECORD,
        async_handle_edit_record,
        schema=EDIT_RECORD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_VEHICLE,
        async_handle_add_vehicle,
        schema=ADD_VEHICLE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_VEHICLE,
        async_handle_remove_vehicle,
        schema=REMOVE_VEHICLE_SCHEMA,
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRICE_HISTORY,
        async_handle_get_price_history,
        supports_response=SupportsResponse.OPTIONAL,
    )
    domain_data["services_registered"] = True


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when the last entry is unloaded."""
    for service in (
        SERVICE_RECORD_REFUEL,
        SERVICE_IMPORT_RECORDS,
        SERVICE_LIST_RECORDS,
        SERVICE_DELETE_RECORD,
        SERVICE_EDIT_RECORD,
        SERVICE_ADD_VEHICLE,
        SERVICE_REMOVE_VEHICLE,
        SERVICE_CLEAR_VEHICLE,
        SERVICE_REFRESH_OIL_PRICE,
        SERVICE_GET_PRICE_HISTORY,
    ):
        hass.services.async_remove(DOMAIN, service)
    hass.data.setdefault(DOMAIN, {})["services_registered"] = False
