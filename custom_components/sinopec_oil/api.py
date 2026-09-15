"""Sinopec oil price API client.

数据来源：中国石化"今日油价"公开页面
https://cx.sinopecsales.com/yjkqiantai/core/initCpb

接口流程（实测验证）：
1. GET  /yjkqiantai/core/initCpb      —— 建立会话（Cookie）
2. POST /yjkqiantai/data/switchProvince  body={"provinceId": "11"} —— 切换省份
3. GET  /yjkqiantai/data/initMainData    —— 获取当前省份油价数据
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    OIL_TYPE_MAP,
    PAGE_URL,
    PROVINCES,
    USER_AGENT,
)


class SinopecOilApiClientError(Exception):
    """Base API error."""


class SinopecOilCannotConnect(SinopecOilApiClientError):
    """Cannot connect to the API."""


class SinopecOilInvalidData(SinopecOilApiClientError):
    """Invalid data returned from the API."""


@dataclass
class OilPriceData:
    """Parsed oil price data for one province."""

    province_id: str
    province_name: str
    to_day: str | None = None
    update_time: str | None = None
    prices: dict[str, float] = field(default_factory=dict)
    changes: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def price_count(self) -> int:
        return len(self.prices)


class SinopecOilApiClient:
    """Client to fetch oil prices from Sinopec.

    每个 client 实例持有独立的 aiohttp 会话（独立 CookieJar），
    避免多个不同省份的集成实例之间会话数据互相干扰。
    """

    def __init__(self, province_id: str) -> None:
        """Initialize the client."""
        self.province_id = province_id
        self.province_name = PROVINCES.get(province_id, province_id)
        self._session: aiohttp.ClientSession | None = None
        self._request_lock = asyncio.Lock()

    async def async_close(self) -> None:
        """Close the underlying session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create a session with an isolated cookie jar."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": USER_AGENT, "Referer": PAGE_URL},
            )
        return self._session

    async def _request(
        self, method: str, path: str, *, expect_json: bool = True, **kwargs: Any
    ) -> Any:
        """Perform a request and return parsed JSON (or raw text)."""
        session = self._get_session()
        url = f"{BASE_URL}{path}"
        try:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status != 200:
                    raise SinopecOilCannotConnect(
                        f"HTTP {resp.status} for {url}"
                    )
                if not expect_json:
                    # 用于初始化页面的请求（返回 HTML，仅建立会话 Cookie）
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

    async def async_get_oil_prices(self) -> OilPriceData:
        """Fetch oil prices: init session -> switch province -> get data."""
        async with self._request_lock:
            # 1) 初始化会话（返回 HTML 页面，仅获取 Cookie）
            await self._request(
                "GET", "/yjkqiantai/core/initCpb", expect_json=False
            )

            # 2) 切换省份（会话级别生效）
            await self._request(
                "POST",
                "/yjkqiantai/data/switchProvince",
                json={"provinceId": self.province_id},
            )

            # 3) 获取油价数据
            raw = await self._request("GET", "/yjkqiantai/data/initMainData")

        return self._parse(raw)

    def _parse(self, raw: dict[str, Any]) -> OilPriceData:
        """Parse the initMainData payload."""
        if not isinstance(raw, dict):
            raise SinopecOilInvalidData("Response is not a JSON object")

        payload = raw.get("data") or {}
        check: dict[str, Any] = dict(payload.get("provinceCheck") or {})
        pdata: dict[str, Any] = dict(payload.get("provinceData") or {})
        areas = payload.get("area") or []

        # 部分省份省级数据为空，回落到第一个地级市数据
        if not any(_is_valid_price(v) for v in pdata.values()) and areas:
            first = areas[0] or {}
            area_check = first.get("areaCheck") or {}
            area_data = first.get("areaData") or {}
            check = {k: v for k, v in area_check.items() if v is not None} or check
            pdata = area_data or pdata

        prices: dict[str, float] = {}
        changes: dict[str, float] = {}
        labels: dict[str, str] = {}

        for check_key, (data_key, label) in OIL_TYPE_MAP.items():
            if check.get(check_key) != "Y":
                continue
            value = pdata.get(data_key)
            if not _is_valid_price(value):
                continue
            key = data_key  # 传感器使用数据字段名作为稳定 key
            prices[key] = float(value)
            labels[key] = label
            status = pdata.get(f"{data_key}_STATUS")
            if isinstance(status, (int, float)):
                changes[key] = float(status)

        if not prices:
            raise SinopecOilInvalidData(
                "No valid oil price found in the response"
            )

        return OilPriceData(
            province_id=self.province_id,
            province_name=PROVINCES.get(self.province_id, self.province_id),
            to_day=raw.get("toDay"),
            update_time=pdata.get("START_DATE"),
            prices=prices,
            changes=changes,
            labels=labels,
        )


def _is_valid_price(value: Any) -> bool:
    """Check whether a price value is valid (non-zero number)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value != 0.0
