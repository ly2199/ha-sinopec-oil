"""Select entities of the built-in refuel form (vehicle / fuel type)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .button import SIGNAL_FORM_SUBMITTED
from .const import SIGNAL_VEHICLE_ADDED, SIGNAL_VEHICLE_REMOVED
from .coordinator import SinopecOilRuntimeData
from .form import FUEL_OPTIONS, claim_form_platform, form_device, get_form_state


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the form select entities (only once across entries)."""
    if not claim_form_platform(hass, entry.entry_id, "select"):
        return
    runtime: SinopecOilRuntimeData = entry.runtime_data
    async_add_entities([VehicleSelect(runtime), FuelSelect(runtime)])


class _FormSelectBase(CoordinatorEntity, SelectEntity):
    """Base class for form selects."""

    _attr_has_entity_name = True

    def __init__(self, runtime: SinopecOilRuntimeData) -> None:
        """Initialize."""
        super().__init__(runtime.refuel_coordinator)
        self._runtime = runtime
        self._attr_device_info = form_device()

    async def async_added_to_hass(self) -> None:
        """Refresh when vehicles change or the form resets."""
        await super().async_added_to_hass()
        for sig in (
            SIGNAL_VEHICLE_ADDED,
            SIGNAL_VEHICLE_REMOVED,
            SIGNAL_FORM_SUBMITTED,
        ):
            self.async_on_remove(
                async_dispatcher_connect(self.hass, sig, self._refresh)
            )

    async def _refresh(self, *_args) -> None:
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Handle user selection."""
        self._apply(option)
        self.async_write_ha_state()

    def _apply(self, option: str) -> None:
        """Write the selection into the shared form state."""
        raise NotImplementedError


class VehicleSelect(_FormSelectBase):
    """加油车辆（选项来自已配置车辆，动态更新）。

    切换车辆时自动预填该车的当前里程表读数
    （最后一条有里程的记录，无记录时回退初始里程）。
    """

    _attr_name = "车辆"
    _attr_icon = "mdi:car"
    _attr_unique_id = "refuel_form_vehicle"

    async def async_added_to_hass(self) -> None:
        """Pre-select the only vehicle once the entity is live."""
        await super().async_added_to_hass()
        self._auto_pick()

    async def _refresh(self, *_args) -> None:
        self._auto_pick()
        self.async_write_ha_state()

    def _auto_pick(self) -> None:
        """Select the single configured vehicle (property getters stay pure)."""
        state = get_form_state(self.hass)
        vehicles = list(self._runtime.store.vehicles)
        if state.vehicle in vehicles or len(vehicles) != 1:
            return
        self._apply(vehicles[0])

    def _apply(self, option: str) -> None:
        state = get_form_state(self.hass)
        state.vehicle = option
        # 预填当前里程，避免每次手动输入
        state.odometer = self._runtime.store.get_current_odometer(option)

    @property
    def options(self) -> list[str]:
        """All configured vehicles (dynamic)."""
        return list(self._runtime.store.vehicles)

    @property
    def current_option(self) -> str | None:
        """Selected vehicle, or None while it is unknown/removed."""
        state = get_form_state(self.hass)
        if state.vehicle in self._runtime.store.vehicles:
            return state.vehicle
        return None


class FuelSelect(_FormSelectBase):
    """油品类型（"自动"= 用车辆默认油品）。"""

    _attr_name = "油品类型"
    _attr_icon = "mdi:gas-station"
    _attr_unique_id = "refuel_form_fuel"

    def _apply(self, option: str) -> None:
        get_form_state(self.hass).fuel = option

    @property
    def options(self) -> list[str]:
        return FUEL_OPTIONS

    @property
    def current_option(self) -> str | None:
        return get_form_state(self.hass).fuel
