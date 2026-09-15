"""Config flow for the Sinopec Oil Price integration."""
from __future__ import annotations

import logging
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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SinopecOilApiClient, SinopecOilApiClientError
from .const import (
    CONF_AREA,
    CONF_FUEL_TYPE,
    CONF_INITIAL_ODOMETER,
    CONF_PROVINCE,
    CONF_SCAN_INTERVAL,
    CONF_VEHICLE,
    DEFAULT_PROVINCE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_VEHICLE_NAME,
    DOMAIN,
    PROVINCES,
    SIGNAL_VEHICLE_ADDED,
    SIGNAL_VEHICLE_REMOVED,
    UNIT_KM,
)

_LOGGER = logging.getLogger(__name__)

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
        min=5,
        max=1440,
        step=1,
        unit_of_measurement="分钟",
        mode=NumberSelectorMode.BOX,
    )
)

ODOMETER_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0,
        max=10000000,
        step=0.1,
        unit_of_measurement=UNIT_KM,
        mode=NumberSelectorMode.BOX,
    )
)

FUEL_TYPE_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.TEXT)
)


def _area_selector(areas: list[dict[str, Any]]) -> SelectSelector:
    """Build an area selector showing official coverage + reference price.

    例："一价区 · 适用于：昆明（92号 8.44 元/L）"
    适用州市说明（AREA_DESC）来自中石化接口，帮助用户判断该价区是否覆盖所在地。
    """
    options = []
    for area in areas:
        label = area["name"]
        desc = (area.get("desc") or "").strip()
        if desc:
            label += f" · {desc}"
        if area.get("sample_price") is not None:
            label += f"（{area.get('sample_label', '')} {area['sample_price']} 元/L）"
        options.append({"value": area["id"], "label": label})
    return SelectSelector(
        SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.DROPDOWN
        )
    )


async def _fetch_areas(province: str) -> list[dict[str, Any]]:
    """Fetch the area list of a province (empty when the province has none)."""
    client = SinopecOilApiClient(province)
    try:
        return await client.async_list_areas()
    finally:
        await client.async_close()


class SinopecOilConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow: province -> area -> first vehicle."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._province: str = DEFAULT_PROVINCE
        self._area_id: str | None = None
        self._area_name: str | None = None
        self._areas: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: choose province."""
        errors: dict[str, str] = {}
        if user_input is not None:
            province = user_input[CONF_PROVINCE]
            await self.async_set_unique_id(f"{DOMAIN}_{province}")
            self._abort_if_unique_id_configured()
            try:
                self._areas = await _fetch_areas(province)
            except SinopecOilApiClientError:
                errors["base"] = "cannot_connect"
            else:
                self._province = province
                if self._areas:
                    return await self.async_step_area()
                return await self.async_step_vehicle()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PROVINCE, default=self._province
                ): PROVINCE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_area(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 2: choose price area (only for provinces with areas)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            area_id = user_input[CONF_AREA]
            self._area_id = str(area_id)
            self._area_name = next(
                (
                    a["name"]
                    for a in self._areas
                    if a["id"] == str(area_id)
                ),
                None,
            )
            return await self.async_step_vehicle()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AREA,
                    default=(self._areas[0]["id"] if self._areas else None),
                ): _area_selector(self._areas),
            }
        )
        return self.async_show_form(
            step_id="area", data_schema=schema, errors=errors
        )

    async def async_step_vehicle(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 3 (optional): configure the first vehicle."""
        if user_input is not None:
            data: dict[str, Any] = {CONF_PROVINCE: self._province}
            if self._area_id:
                data[CONF_AREA] = self._area_id

            vehicle_name = (user_input.get(CONF_VEHICLE) or "").strip()
            if vehicle_name:
                # 车辆信息保存到全局 store，安装后由 __init__ 处理
                self.hass.data.setdefault(DOMAIN, {}).setdefault(
                    "pending_vehicle", {}
                )
                self.hass.data[DOMAIN]["pending_vehicle"] = {
                    "name": vehicle_name,
                    "initial_odometer": user_input.get(CONF_INITIAL_ODOMETER),
                    "fuel_type": user_input.get(CONF_FUEL_TYPE) or "92",
                }

            province_name = PROVINCES.get(self._province, self._province)
            title = f"中石化油价（{province_name}"
            if self._area_name:
                title += f"·{self._area_name}"
            title += "）"
            return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_VEHICLE): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(CONF_INITIAL_ODOMETER): ODOMETER_SELECTOR,
                vol.Optional(CONF_FUEL_TYPE, default="92"): FUEL_TYPE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="vehicle",
            data_schema=schema,
            description_placeholders={
                "province": PROVINCES.get(self._province, self._province)
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SinopecOilOptionsFlow:
        """Create the options flow handler."""
        return SinopecOilOptionsFlow()


class SinopecOilOptionsFlow(OptionsFlow):
    """Manage options: location settings and vehicle management."""

    @property
    def _entry(self) -> ConfigEntry:
        """Return the config entry (compatible with old and new HA versions)."""
        entry = getattr(self, "config_entry", None)
        if entry is not None:
            return entry
        return self._config_entry  # type: ignore[attr-defined]

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._province: str | None = None
        self._area_id: str | None = None
        self._scan_interval: int | None = None
        self._areas: list[dict[str, Any]] = []
        self._settings_ready = False
        self._vehicle_name: str | None = None
        self._manage_vehicle: str | None = None

    # ------------------------------------------------------------------
    # 菜单
    # ------------------------------------------------------------------
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the management menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "settings",
                "add_vehicle",
                "edit_vehicle",
                "remove_vehicle",
                "clear_vehicle",
                "manage_records",
                "done",
            ],
        )

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish the options flow."""
        return self.async_create_entry(data=self._entry.options)

    # ------------------------------------------------------------------
    # 油价位置设置
    # ------------------------------------------------------------------
    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change province and scan interval."""
        errors: dict[str, str] = {}
        if user_input is not None:
            province = user_input[CONF_PROVINCE]
            try:
                self._areas = await _fetch_areas(province)
            except SinopecOilApiClientError:
                errors["base"] = "cannot_connect"
            else:
                self._province = province
                self._scan_interval = int(
                    user_input[CONF_SCAN_INTERVAL]
                )
                self._area_id = None
                self._settings_ready = True
                if self._areas:
                    return await self.async_step_area()
                return await self._async_save_settings()

        current_province = (
            self._entry.options.get(CONF_PROVINCE)
            or self._entry.data.get(CONF_PROVINCE, DEFAULT_PROVINCE)
        )
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
            step_id="settings", data_schema=schema, errors=errors
        )

    async def async_step_area(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose the price area (options flow)."""
        if user_input is not None:
            self._area_id = str(user_input[CONF_AREA])
            return await self._async_save_settings()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AREA,
                    default=(self._areas[0]["id"] if self._areas else None),
                ): _area_selector(self._areas),
            }
        )
        return self.async_show_form(step_id="area", data_schema=schema)

    async def _async_save_settings(self) -> ConfigFlowResult:
        """Write province/area/interval into options."""
        new_options = dict(self._entry.options)
        if self._province:
            new_options[CONF_PROVINCE] = self._province
            new_options.pop(CONF_AREA, None)
        if self._area_id:
            new_options[CONF_AREA] = self._area_id
        if self._scan_interval:
            new_options[CONF_SCAN_INTERVAL] = self._scan_interval
        self._settings_ready = False
        # 直接写入并 reload，然后返回菜单
        self.hass.config_entries.async_update_entry(
            self._entry, options=new_options
        )
        await self.hass.config_entries.async_reload(self._entry.entry_id)
        return await self.async_step_init()

    # ------------------------------------------------------------------
    # 车辆管理
    # ------------------------------------------------------------------
    def _vehicle_options(self) -> list[dict[str, str]]:
        """Return vehicle select options from the store."""
        store = self.hass.data.get(DOMAIN, {}).get("store")
        return [
            {"value": name, "label": name}
            for name in (store.vehicles if store else {})
        ]

    def _store(self):
        """Return the shared store (must exist while entry is loaded)."""
        return self.hass.data[DOMAIN]["store"]

    async def async_step_add_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a vehicle."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = (user_input.get(CONF_VEHICLE) or "").strip()
            if not name:
                errors[CONF_VEHICLE] = "vehicle_name_required"
            else:
                created = await self._store().async_add_vehicle(
                    name,
                    initial_odometer=user_input.get(CONF_INITIAL_ODOMETER),
                    fuel_type=user_input.get(CONF_FUEL_TYPE) or "92",
                )
                if created:
                    from homeassistant.helpers.dispatcher import (
                        async_dispatcher_send,
                    )

                    async_dispatcher_send(
                        self.hass, SIGNAL_VEHICLE_ADDED, name
                    )
                return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Optional(CONF_INITIAL_ODOMETER): ODOMETER_SELECTOR,
                vol.Optional(CONF_FUEL_TYPE, default="92"): FUEL_TYPE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="add_vehicle", data_schema=schema, errors=errors
        )

    async def async_step_edit_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing vehicle (initial odometer / default fuel type)."""
        store = self._store()

        if self._vehicle_name is not None:
            # 第二次提交：保存修改
            await store.async_update_vehicle(
                self._vehicle_name,
                initial_odometer=user_input.get(CONF_INITIAL_ODOMETER)
                if user_input
                else None,
                fuel_type=user_input.get(CONF_FUEL_TYPE) if user_input else None,
            )
            self._vehicle_name = None
            return await self.async_step_init()

        if not self._vehicle_options():
            return await self.async_step_init()

        if user_input is not None and CONF_VEHICLE in user_input:
            # 已选择车辆：显示编辑表单（带当前值）
            self._vehicle_name = user_input[CONF_VEHICLE]
            info = store.get_vehicle(self._vehicle_name) or {}
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_INITIAL_ODOMETER,
                        description={
                            "suggested_value": info.get("initial_odometer")
                        },
                    ): ODOMETER_SELECTOR,
                    vol.Optional(
                        CONF_FUEL_TYPE,
                        description={
                            "suggested_value": info.get("default_fuel_type")
                            or "92"
                        },
                    ): FUEL_TYPE_SELECTOR,
                }
            )
            return self.async_show_form(
                step_id="edit_vehicle",
                data_schema=schema,
                description_placeholders={"vehicle": self._vehicle_name},
            )

        # 第一步：选择要编辑的车辆
        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._vehicle_options(),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="edit_vehicle_select", data_schema=schema
        )

    async def async_step_remove_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a vehicle."""
        if not self._vehicle_options():
            return await self.async_step_init()
        if user_input is not None:
            name = user_input[CONF_VEHICLE]
            if await self._store().async_remove_vehicle(name):
                from homeassistant.helpers.dispatcher import (
                    async_dispatcher_send,
                )

                async_dispatcher_send(
                    self.hass, SIGNAL_VEHICLE_REMOVED, name
                )
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._vehicle_options(),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="remove_vehicle", data_schema=schema
        )

    async def async_step_clear_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Clear all refuel records of a vehicle (keep the vehicle)."""
        if not self._vehicle_options():
            return await self.async_step_init()
        if user_input is not None:
            await self._store().async_clear_vehicle(user_input[CONF_VEHICLE])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._vehicle_options(),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="clear_vehicle", data_schema=schema
        )

    async def async_step_manage_records(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Browse and delete individual refuel records of a vehicle."""
        store = self._store()

        # 第二阶段：选中记录并删除
        if self._manage_vehicle is not None:
            if user_input is not None and "record_index" in user_input:
                index = int(user_input["record_index"])
                removed = await store.async_delete_record(
                    self._manage_vehicle, index
                )
                if removed is not None:
                    _LOGGER.info(
                        "已删除加油记录：车辆=%s %s",
                        self._manage_vehicle,
                        removed.get("date"),
                    )
            self._manage_vehicle = None
            return await self.async_step_init()

        # 第一阶段：选择车辆
        if not self._vehicle_options():
            return await self.async_step_init()
        if user_input is not None and CONF_VEHICLE in user_input:
            self._manage_vehicle = user_input[CONF_VEHICLE]
            records = store.get_records_sorted(self._manage_vehicle)
            if not records:
                self._manage_vehicle = None
                return await self.async_step_init()
            options = []
            for rec in records:
                label = (
                    f"{str(rec.get('date', ''))[:16]} · "
                    f"{rec.get('volume', '?')} L · "
                    f"{rec.get('total_cost', '?')} 元"
                )
                odometer = rec.get("odometer")
                if odometer is not None:
                    label += f" · {odometer} km"
                options.append(
                    {"value": str(rec["index"]), "label": label}
                )
            schema = vol.Schema(
                {
                    vol.Required("record_index"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            )
            return self.async_show_form(
                step_id="manage_records",
                data_schema=schema,
                description_placeholders={
                    "vehicle": self._manage_vehicle,
                    "count": str(len(records)),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE): SelectSelector(
                    SelectSelectorConfig(
                        options=self._vehicle_options(),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="manage_records_select", data_schema=schema
        )
