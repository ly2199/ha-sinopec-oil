"""Config flow for the Sinopec Oil Price integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SinopecOilApiClient, SinopecOilApiClientError
from .const import (
    CONF_PROVINCE,
    CONF_SCAN_INTERVAL,
    DEFAULT_PROVINCE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    PROVINCES,
)

PROVINCE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            {"value": pid, "label": name}
            for pid, name in PROVINCES.items()
        ],
        mode=SelectSelectorMode.DROPDOWN,
    )
)

SCAN_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=10,
        max=720,
        step=1,
        unit_of_measurement="分钟",
        mode=NumberSelectorMode.BOX,
    )
)


class SinopecOilConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Sinopec Oil Price."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: choose province."""
        errors: dict[str, str] = {}

        if user_input is not None:
            province = user_input[CONF_PROVINCE]
            await self.async_set_unique_id(f"{DOMAIN}_{province}")
            self._abort_if_unique_id_configured()

            # 连接性测试：实际请求一次油价接口
            client = SinopecOilApiClient(province)
            try:
                await client.async_get_oil_prices()
            except SinopecOilApiClientError:
                errors["base"] = "cannot_connect"
            finally:
                await client.async_close()

            if not errors:
                name = PROVINCES.get(province, province)
                return self.async_create_entry(
                    title=f"中石化油价（{name}）", data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PROVINCE, default=DEFAULT_PROVINCE): PROVINCE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SinopecOilOptionsFlow:
        """Create the options flow handler."""
        return SinopecOilOptionsFlow()


class SinopecOilOptionsFlow(OptionsFlow):
    """Handle options: change province and scan interval."""

    @property
    def _entry(self) -> ConfigEntry:
        """Return the config entry (compatible with old and new HA versions).

        HA 2025.3+ 在框架层自动提供 self.config_entry；
        旧版本需要读取 self._config_entry。
        """
        entry = getattr(self, "config_entry", None)
        if entry is not None:
            return entry
        return self._config_entry  # type: ignore[attr-defined]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            province = user_input[CONF_PROVINCE]
            # 若省份变化，检查该省份是否已被另一个实例使用
            if province != self._current_province():
                await self.async_set_unique_id(f"{DOMAIN}_{province}")
                self._abort_if_unique_id_configured(
                    existing_entry=self._entry
                )

            client = SinopecOilApiClient(province)
            try:
                await client.async_get_oil_prices()
            except SinopecOilApiClientError:
                errors["base"] = "cannot_connect"
            finally:
                await client.async_close()

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current_province = self._current_province()
        current_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_PROVINCE, default=current_province): PROVINCE_SELECTOR,
                vol.Required(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): SCAN_INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )

    def _current_province(self) -> str:
        """Return the currently configured province."""
        return (
            self._entry.options.get(CONF_PROVINCE)
            or self._entry.data.get(CONF_PROVINCE, DEFAULT_PROVINCE)
        )
