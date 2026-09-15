"""Number entities of the built-in refuel form."""
from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SinopecOilRuntimeData
from .form import form_device, get_form_state
from .const import UNIT_KM, UNIT_LITER, UNIT_YUAN


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up the form number entities (only once across entries)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("form_created"):
        return
    domain_data["form_created"] = True
    runtime: SinopecOilRuntimeData = entry.runtime_data
    async_add_entities(
        [
            OdometerNumber(hass, runtime),
            VolumeNumber(hass, runtime),
            CostNumber(hass, runtime),
        ]
    )


class _FormNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for form number inputs (shared device/state).

    表单为临时状态：重启后清零（避免重启后旧值被误提交）。
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self, hass: HomeAssistant, runtime: SinopecOilRuntimeData
    ) -> None:
        """Initialize."""
        super().__init__(runtime.refuel_coordinator)
        self.hass = hass
        self._runtime = runtime
        self._attr_device_info = form_device()

    def _apply(self, value: float) -> None:
        """Apply a value to the form state (implemented by subclasses)."""
        raise NotImplementedError

    @property
    def native_value(self) -> float | None:
        """Current value from the shared form state."""
        raise NotImplementedError

    async def async_set_native_value(self, value: float) -> None:
        """Handle user input from the UI."""
        self._apply(value)
        self.async_write_ha_state()


class OdometerNumber(_FormNumberBase):
    """里程表读数（km）。"""

    _attr_name = "里程表读数"
    _attr_icon = "mdi:counter"
    _attr_native_min_value = 0
    _attr_native_max_value = 3000000
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UNIT_KM
    _attr_unique_id = "refuel_form_odometer"
    _attr_suggested_display_precision = 1

    def _apply(self, value: float) -> None:
        get_form_state(self.hass).odometer = value or None

    @property
    def native_value(self) -> float | None:
        return get_form_state(self.hass).odometer


class VolumeNumber(_FormNumberBase):
    """加油量（L，可选）。"""

    _attr_name = "加油量"
    _attr_icon = "mdi:gas-pump"
    _attr_native_min_value = 0
    _attr_native_max_value = 2000
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = UNIT_LITER
    _attr_unique_id = "refuel_form_volume"
    _attr_suggested_display_precision = 2

    def _apply(self, value: float) -> None:
        get_form_state(self.hass).volume = value or None

    @property
    def native_value(self) -> float | None:
        return get_form_state(self.hass).volume


class CostNumber(_FormNumberBase):
    """加油费用（元，可选）。"""

    _attr_name = "加油费用"
    _attr_icon = "mdi:cash"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = UNIT_YUAN
    _attr_unique_id = "refuel_form_cost"
    _attr_suggested_display_precision = 2

    def _apply(self, value: float) -> None:
        get_form_state(self.hass).total_cost = value or None

    @property
    def native_value(self) -> float | None:
        return get_form_state(self.hass).total_cost
