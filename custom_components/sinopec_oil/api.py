"""Sinopec oil price API client.

数据来源：中国石化"今日油价"公开页面
https://cx.sinopecsales.com/yjkqiantai/core/initCpb

接口流程（实测验证）：
1. GET  /yjkqiantai/core/initCpb      —— 建立会话（Cookie）
2. POST /yjkqiantai/data/switchProvince  body={"provinceId": "11"} —— 切换省份（会话级）
3. GET  /yjkqiantai/data/initMainData    —— 当日油价（含价区 area 列表）
4. GET  /yjkqiantai/data/initOilPrice    —— 历史调价周期列表（约 24 期）

价区说明：
- 部分省份（如云南 53、四川 51）按价区（一价区/二价区…）发布价格，
  省级 provinceData 为空，必须从 area[] 中按 AREA_ID 选择；
- 部分省份（如北京、广东、湖北）全省一价，area 为空。
- 历史接口同样遵循该结构：无价区省 provinceData 为周期列表，
  有价区省 area[].areaData 为周期列表。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date as dt_date, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    OIL_DATA_KEYS,
    OIL_TYPE_MAP,
    PAGE_URL,
    PROVINCES,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

HISTORY_CACHE_TTL = timedelta(minutes=10)


class SinopecOilApiClientError(Exception):
    """Base API error."""


class SinopecOilCannotConnect(SinopecOilApiClientError):
    """Cannot connect to the API."""


class SinopecOilInvalidData(SinopecOilApiClientError):
    """Invalid data returned from the API."""


@dataclass
class OilPriceData:
    """Parsed current oil price data for one province/area."""

    province_id: str
    province_name: str
    area_id: str | None = None
    area_name: str | None = None
    area_desc: str | None = None
    to_day: str | None = None
    update_time: str | None = None
    server_time: str | None = None
    period_id: int | None = None
    prices: dict[str, float] = field(default_factory=dict)
    # 相对上一期的涨跌额（接口 _STATUS，带符号：正=上调，负=下调，0=搁浅）
    changes: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    # 历史调价周期（由 coordinator 附加填充）：
    # [{start, end, period_id, prices, changes}, ...]，按时间倒序
    price_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Province + area display name."""
        if self.area_name:
            return f"{self.province_name}·{self.area_name}"
        return self.province_name

    def price_for(self, keys: tuple[str, ...]) -> float | None:
        """Return the first available price for candidate data keys."""
        for key in keys:
            if key in self.prices:
                return self.prices[key]
        return None


@dataclass
class HistoryPeriod:
    """One price adjustment period (生效周期)."""

    start: dt_date
    end: dt_date
    period_id: int | None = None
    prices: dict[str, float] = field(default_factory=dict)
    changes: dict[str, float] = field(default_factory=dict)


class SinopecOilApiClient:
    """Client to fetch oil prices from Sinopec.

    每个 client 实例持有独立的 aiohttp 会话（独立 CookieJar），
    避免多个不同省份的集成实例之间会话数据互相干扰。
    """

    def __init__(self, province_id: str, area_id: str | None = None) -> None:
        """Initialize the client."""
        self.province_id = province_id
        self.area_id = str(area_id) if area_id else None
        self.province_name = PROVINCES.get(province_id, province_id)
        self._session: aiohttp.ClientSession | None = None
        self._request_lock = asyncio.Lock()
        self._history_cache: tuple[datetime, list[HistoryPeriod]] | None = None

    # ------------------------------------------------------------------
    # HTTP 基础
    # ------------------------------------------------------------------
    def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create a dedicated session (own cookie jar)."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": USER_AGENT, "Referer": PAGE_URL},
            )
        return self._session

    async def async_close(self) -> None:
        """Close the underlying session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _request(
        self, method: str, path: str, *, expect_json: bool = True, **kwargs: Any
    ) -> Any:
        """Perform a request and return parsed JSON (or raw text)."""
        session = self._get_session()
        url = f"{BASE_URL}{path}"
        try:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status != 200:
                    raise SinopecOilCannotConnect(f"HTTP {resp.status} for {url}")
                if not expect_json:
                    # 初始化页面请求返回 HTML，仅用于建立会话 Cookie
                    return await resp.text()
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise SinopecOilInvalidData(
                        f"Invalid JSON response from {url}"
                    ) from err
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise SinopecOilCannotConnect(f"Timeout requesting {url}") from err
        except aiohttp.ClientError as err:
            raise SinopecOilCannotConnect(f"Client error for {url}: {err}") from err

    async def _init_session_and_switch(self) -> None:
        """Init session cookie and switch to the configured province."""
        # 1) 初始化会话（返回 HTML 页面，仅获取 Cookie）
        await self._request("GET", "/yjkqiantai/core/initCpb", expect_json=False)
        # 2) 切换省份（会话级别生效）
        await self._request(
            "POST",
            "/yjkqiantai/data/switchProvince",
            json={"provinceId": self.province_id},
        )

    # ------------------------------------------------------------------
    # 当日油价
    # ------------------------------------------------------------------
    async def async_get_oil_prices(self) -> OilPriceData:
        """Fetch current oil prices for the configured province/area."""
        async with self._request_lock:
            await self._init_session_and_switch()
            raw = await self._request("GET", "/yjkqiantai/data/initMainData")
        return self._parse_main(raw)

    def _parse_main(self, raw: dict[str, Any]) -> OilPriceData:
        """Parse the initMainData payload."""
        payload = raw.get("data") or {}
        check: dict[str, Any] = dict(payload.get("provinceCheck") or {})
        pdata: dict[str, Any] = dict(payload.get("provinceData") or {})
        areas = payload.get("area") or []

        area_name: str | None = None

        # 价区选择：指定 AREA_ID 优先，其次默认第一个价区，
        # 仅当无价区时才使用省级数据
        if areas:
            matched = None
            if self.area_id is not None:
                matched = next(
                    (
                        a
                        for a in areas
                        if str((a.get("areaCheck") or {}).get("AREA_ID"))
                        == str(self.area_id)
                    ),
                    None,
                )
            if matched is None:
                matched = areas[0]
            area_check = matched.get("areaCheck") or {}
            area_name = area_check.get("AREA_NAME")
            self.area_id = str(area_check.get("AREA_ID") or self.area_id)
            pdata = dict(matched.get("areaData") or {})
            if area_check:
                check = {k: v for k, v in area_check.items() if v is not None}

        prices: dict[str, float] = {}
        changes: dict[str, float] = {}
        labels: dict[str, str] = {}

        for check_key, (data_key, label) in OIL_TYPE_MAP.items():
            if check.get(check_key) != "Y":
                continue
            value = pdata.get(data_key)
            if not _is_valid_price(value):
                continue
            prices[data_key] = float(value)
            labels[data_key] = label
            status = pdata.get(f"{data_key}_STATUS")
            if isinstance(status, (int, float)) and not isinstance(status, bool):
                changes[data_key] = float(status)

        if not prices:
            raise SinopecOilInvalidData("No valid oil price found in the response")

        area_desc = str(check.get("AREA_DESC") or "").strip() or None
        period_id = pdata.get("PERIOD_ID")

        return OilPriceData(
            province_id=self.province_id,
            # 接口返回的名称优先（可能与内置省份表措辞不同）
            province_name=str(check.get("PROVINCE_NAME") or self.province_name),
            area_id=self.area_id,
            area_name=area_name,
            area_desc=area_desc,
            to_day=raw.get("toDay"),
            update_time=pdata.get("START_DATE"),
            server_time=raw.get("nowTime"),
            period_id=int(period_id) if isinstance(period_id, (int, float))
            and not isinstance(period_id, bool) else None,
            prices=prices,
            changes=changes,
            labels=labels,
        )

    # ------------------------------------------------------------------
    # 历史油价（按调价周期）
    # ------------------------------------------------------------------
    async def async_get_price_history(
        self, force_refresh: bool = False
    ) -> list[HistoryPeriod]:
        """Fetch the list of historical price periods (cached)."""
        now = datetime.now()
        if (
            not force_refresh
            and self._history_cache is not None
            and now - self._history_cache[0] < HISTORY_CACHE_TTL
        ):
            return self._history_cache[1]

        async with self._request_lock:
            await self._init_session_and_switch()
            raw = await self._request("GET", "/yjkqiantai/data/initOilPrice")

        periods = self._parse_history(raw)
        self._history_cache = (now, periods)
        return periods

    def _parse_history(self, raw: dict[str, Any]) -> list[HistoryPeriod]:
        """Parse the initOilPrice payload into sorted periods (newest first)."""
        payload = raw.get("data") or {}
        rows: list[dict[str, Any]] | None = payload.get("provinceData")
        if rows is None:
            areas = payload.get("area") or []
            matched = None
            if areas:
                if self.area_id is not None:
                    matched = next(
                        (
                            a
                            for a in areas
                            if str((a.get("areaCheck") or {}).get("AREA_ID"))
                            == str(self.area_id)
                        ),
                        None,
                    )
                if matched is None:
                    matched = areas[0]
            rows = (matched or {}).get("areaData") if matched else None

        if not isinstance(rows, list) or not rows:
            raise SinopecOilInvalidData("No historical price periods found")

        periods: list[HistoryPeriod] = []
        for row in rows:
            start = _parse_date_str(row.get("START_TIME") or row.get("STR_START_DATE"))
            end = _parse_date_str(row.get("END_TIME"))
            if start is None or end is None:
                continue
            prices: dict[str, float] = {}
            changes: dict[str, float] = {}
            for key in OIL_DATA_KEYS:
                value = row.get(key)
                if not _is_valid_price(value):
                    continue
                prices[key] = float(value)
                status = row.get(f"{key}_STATUS")
                if isinstance(status, (int, float)) and not isinstance(
                    status, bool
                ):
                    changes[key] = float(status)
            if not prices:
                continue
            period_id = row.get("PERIOD_ID")
            periods.append(
                HistoryPeriod(
                    start=start,
                    end=end,
                    period_id=(
                        int(period_id)
                        if isinstance(period_id, (int, float))
                        and not isinstance(period_id, bool)
                        else None
                    ),
                    prices=prices,
                    changes=changes,
                )
            )

        if not periods:
            raise SinopecOilInvalidData("No valid historical price periods")

        periods.sort(key=lambda p: p.start, reverse=True)
        return periods

    async def async_get_price_on(
        self, data_keys: tuple[str, ...], when: dt_date
    ) -> tuple[float, str, bool] | None:
        """Return (price, period_label, approximate) for a given date.

        - 日期落在某个调价周期内 → 该周期价格；
        - 日期晚于最新周期 → 最新周期价格；
        - 日期早于最早周期（超出历史范围）→ 最早周期价格（近似值）。
        找不到任何候选油品价格时返回 None。
        """
        periods = await self.async_get_price_history()

        def _first_price(period: HistoryPeriod) -> float | None:
            for key in data_keys:
                if key in period.prices:
                    return period.prices[key]
            return None

        # 晚于最新周期：用最新价格
        latest = periods[0]
        if when > latest.end:
            price = _first_price(latest)
            if price is not None:
                return (
                    price,
                    f"{latest.start.isoformat()} 起价格",
                    True,
                )

        for period in periods:
            if period.start <= when <= period.end:
                price = _first_price(period)
                if price is not None:
                    return (
                        price,
                        f"{period.start.isoformat()}~{period.end.isoformat()} 调价周期",
                        False,
                    )

        # 早于最早周期：用最早价格（近似）
        oldest = periods[-1]
        price = _first_price(oldest)
        if price is not None:
            return (
                price,
                f"{oldest.start.isoformat()} 起价格（超出历史范围，近似）",
                True,
            )
        return None

    @staticmethod
    def history_to_payload(
        periods: list[HistoryPeriod],
    ) -> list[dict[str, Any]]:
        """Convert history periods to a JSON-friendly list.

        输出：[{start: "2026-09-12", end: "2026-09-24", period_id: 146,
                prices: {"GAS_92": 8.29, ...},
                changes: {"GAS_92": 0.2, ...}}, ...]（按时间倒序）。

        prices/changes 一律使用稳定的数据字段名（非中文标签），
        前端与自动化取值不会因文案调整而失效；
        展示用中文标签见 const.OIL_TYPE_LABELS。
        """
        return [
            {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "period_id": period.period_id,
                "prices": dict(period.prices),
                "changes": dict(period.changes),
            }
            for period in periods
        ]

    # ------------------------------------------------------------------
    # 价区列表（供配置流选择）
    # ------------------------------------------------------------------
    async def async_list_areas(self) -> list[dict[str, Any]]:
        """Return the area list for the province.

        每项：{id, name, desc(官方适用州市说明), sample_label, sample_price,
        prices(中文油品名 → 参考价)}。
        AREA_DESC 来自中石化接口（如 "适用于：昆明"），用于价区选择时
        告知用户该价区覆盖哪些州市。
        """
        async with self._request_lock:
            await self._init_session_and_switch()
            raw = await self._request("GET", "/yjkqiantai/data/initMainData")

        payload = raw.get("data") or {}
        areas = payload.get("area") or []
        result: list[dict[str, Any]] = []
        for area in areas:
            check = area.get("areaCheck") or {}
            pdata = area.get("areaData") or {}
            sample_key, sample_price = None, None
            prices: dict[str, float] = {}
            for _, (data_key, label) in OIL_TYPE_MAP.items():
                if _is_valid_price(pdata.get(data_key)):
                    prices[label] = float(pdata[data_key])
                    if sample_key is None:
                        sample_key, sample_price = label, pdata[data_key]
            desc = str(check.get("AREA_DESC") or "").strip() or None
            result.append(
                {
                    "id": str(check.get("AREA_ID")),
                    "name": check.get("AREA_NAME") or str(check.get("AREA_ID")),
                    "desc": desc,
                    "sample_label": sample_key,
                    "sample_price": sample_price,
                    "prices": prices,
                }
            )
        return result


def resolve_fuel_keys(fuel_type: str) -> tuple[str, ...]:
    """Resolve a user fuel type (e.g. "92", "0", "GAS_92") to data keys."""
    from .const import FUEL_TYPE_ALIASES  # 局部导入避免循环

    normalized = (fuel_type or "").strip().lower()
    if normalized in FUEL_TYPE_ALIASES:
        return FUEL_TYPE_ALIASES[normalized]
    upper = (fuel_type or "").strip().upper()
    if upper in OIL_DATA_KEYS:
        return (upper,)
    # 模糊匹配：输入包含别名键（如 "92号"、"0#柴油"）
    for alias, keys in FUEL_TYPE_ALIASES.items():
        if alias in normalized:
            return keys
    return ()


def _parse_date_str(value: Any) -> dt_date | None:
    """Parse '2026-09-12 00:00:00' / '2026-09-12' to date."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_valid_price(value: Any) -> bool:
    """Check whether a price value is valid (non-zero number)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value != 0.0
